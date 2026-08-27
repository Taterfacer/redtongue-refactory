#!/usr/bin/env python3
"""
core.py
Forensic foundation layer for the RedTongue Refactory.
Provides shared substrate: error hierarchy, canonical data models,
issue fingerprinting, atomic file writes, advisory file locks,
persistent SQLite store (WAL), and the adaptive system-load Governor.
Cross-platform OS metrics (ctypes for Windows, /proc for Linux).
Optimized for low-RAM (8GB) and HDD environments.
"""

import ctypes
import ctypes.wintypes
import errno
import hashlib
import json
import logging
import os
import random
import re
import sqlite3
import sys
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import IntEnum
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

# ==============================================================================
# CONSTANTS & EXIT CODES
# ==============================================================================
EXIT_OK: int = 0
EXIT_FINDINGS: int = 1
EXIT_INTERNAL: int = 2
EXIT_DEGRADED: int = 3


# ==============================================================================
# ERROR HIERARCHY
# ==============================================================================
class LintStackError(Exception):
    """Base exception for lintstack engine failures."""

    exit_code: int = EXIT_INTERNAL


class ConfigError(LintStackError):
    """Configuration validation or parsing failure."""


class StoreError(LintStackError):
    """SQLite store operation failure."""


class StoreCorrupt(StoreError):
    """SQLite database corruption detected."""

    exit_code = EXIT_DEGRADED


class AtomicWriteError(LintStackError):
    """Atomic file write failure."""


class LockBusy(LintStackError):
    """Advisory file lock acquisition failure."""

    exit_code = EXIT_DEGRADED


class RepairFailed(LintStackError):
    """Store repair operation failure."""

    exit_code = EXIT_DEGRADED


# ==============================================================================
# CANONICAL MODELS
# ==============================================================================
class Severity(IntEnum):
    """Standardized issue severity levels."""

    INFO = 10
    LOW = 20
    MEDIUM = 30
    HIGH = 40
    CRITICAL = 50

    @staticmethod
    def from_name(name: str) -> "Severity":
        try:
            return Severity[str(name).strip().upper()]
        except KeyError:
            return Severity.MEDIUM


@dataclass(slots=True)
class Issue:
    """Canonical representation of a forensic finding."""

    source: str
    code: str
    message: str
    path: str
    line_start: int = 0
    line_end: int = 0
    col: int = 0
    severity: Severity = Severity.MEDIUM
    qualname: str = ""
    explanation: str = ""
    payload: dict = field(default_factory=dict)
    fingerprint: str = ""
    dedupe_key: str = ""

    def compute_keys(self) -> "Issue":
        """Generates fingerprint and dedupe keys for the issue."""
        self.fingerprint = fingerprint(
            self.source,
            self.code,
            self.message,
            self.path,
            self.qualname,
            self.line_start,
        )
        self.dedupe_key = "\x1f".join(
            (self.source, self.code, self.path, str(self.line_start), self.message)
        )
        return self

    def to_row(self, run_id: int, created_utc: str) -> tuple:
        """Converts issue to SQLite row tuple."""
        if not self.fingerprint:
            self.compute_keys()
        return (
            run_id,
            self.source,
            self.code,
            int(self.severity),
            self.path,
            self.line_start,
            self.line_end,
            self.col,
            self.message,
            self.qualname,
            self.explanation,
            self.fingerprint,
            self.dedupe_key,
            json.dumps(self.payload, sort_keys=True, default=str),
            created_utc,
        )


@dataclass(slots=True)
class Config:
    """Engine configuration with Potato PC optimized defaults."""

    project_root: Path
    state_dir: Path
    exclude: tuple = tuple()
    ruff_path: str | None = None
    target_python: str | None = None
    limit_mem_mb: int = 768
    wall_seconds: float = 30.0
    gov_enabled: bool = True
    gov_soft_avail_mb: int = 1200
    gov_hard_avail_mb: int = 800
    gov_pause_avail_mb: int = 400
    gov_soft_psi: float = 0.05
    gov_hard_psi: float = 0.15
    gov_pause_psi: float = 0.30
    gov_min_gate_ms: int = 10
    gov_max_pause_s: float = 120.0

    @staticmethod
    def defaults(project_root: Path) -> "Config":
        return Config(
            project_root=project_root,
            state_dir=project_root / ".lintstack",
        )


@dataclass(frozen=True, slots=True)
class Layout:
    """Directory structure layout for the forensic engine."""

    root: Path
    state: Path
    db: Path
    config: Path
    logs: Path
    snapshots: Path
    workspaces: Path
    boot_lock: Path
    db_wal: Path
    db_shm: Path

    @staticmethod
    def from_root(root: Path) -> "Layout":
        st = root / ".lintstack"
        return Layout(
            root=root.resolve(),
            state=st,
            db=st / "store.db",
            config=st / "config.toml",
            logs=st / "logs",
            snapshots=st / "snapshots",
            workspaces=st / "workspaces",
            boot_lock=st / "boot.lock",
            db_wal=st / "store.db-wal",
            db_shm=st / "store.db-shm",
        )


# ==============================================================================
# UTILITIES
# ==============================================================================
def iso_utc(ts: float | None = None) -> str:
    """Returns ISO 8601 UTC timestamp."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts or time.time()))


def sha256_bytes(data: bytes) -> str:
    """Computes SHA256 hex digest of bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    """Computes SHA256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def tail_text(data: bytes, limit: int = 8000) -> str:
    """Returns tail of bytes decoded as UTF-8."""
    if len(data) > limit:
        data = b"[...truncated...]\n" + data[-limit:]
    return data.decode("utf-8", errors="replace")


_LOG_LOCK = threading.Lock()
_LOG_READY = False


def setup_logging(logs_dir: Path, verbose: bool = False) -> logging.Logger:
    """Configures and returns the root lintstack logger."""
    global _LOG_READY
    with _LOG_LOCK:
        lg = logging.getLogger("lintstack")
        if _LOG_READY:
            return lg
        logs_dir.mkdir(parents=True, exist_ok=True)
        lg.setLevel(logging.DEBUG)

        sh = logging.StreamHandler(sys.stderr)
        sh.setLevel(logging.DEBUG if verbose else logging.WARNING)
        sh.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))

        fh = RotatingFileHandler(
            logs_dir / "lintstack.log",
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s %(module)s:%(lineno)d :: %(message)s"
            )
        )

        lg.addHandler(sh)
        lg.addHandler(fh)
        lg.propagate = False
        _LOG_READY = True
        return lg


# ==============================================================================
# ISSUE FINGERPRINTING
# ==============================================================================
_RX_HEX = re.compile(r"\b0x[0-9a-fA-F]+\b")
_RX_NUM = re.compile(r"(?<!\w)-?\d+(?:\.\d+)?(?!\w)")
_RX_QSTR = re.compile(r"'[^']*'|\"[^\"]*\"")
_RX_WS = re.compile(r"\s+")


def normalize_message(message: str) -> str:
    """Normalizes message for deterministic fingerprinting."""
    s = _RX_QSTR.sub("<q>", message)
    s = _RX_HEX.sub("<hex>", s)
    s = _RX_NUM.sub("<n>", s)
    return _RX_WS.sub(" ", s).strip().lower()


def fingerprint(
    source: str, code: str, message: str, path: str, qualname: str, line_start: int
) -> str:
    """Generates a 16-char deterministic fingerprint for an issue."""
    line_bucket = max(line_start, 0) // 10
    basis = "\x1f".join(
        (
            source,
            code.split(".")[0],
            normalize_message(message),
            path.replace(os.sep, "/").lower(),
            qualname,
            str(line_bucket),
        )
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


# ==============================================================================
# ATOMIC WRITES & LOCKS
# ==============================================================================
_TMP_PREFIX = ".lstack-tmp-"


def atomic_write(destination: Path, data: bytes, *, mode: int = 0o600) -> None:
    """Writes data to destination atomically using tempfile + os.replace."""
    dest = destination.absolute()
    parent = dest.parent
    parent.mkdir(parents=True, exist_ok=True)

    fd = -1
    tmp_path: Path | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(prefix=_TMP_PREFIX, dir=str(parent))
        tmp_path = Path(tmp_name)
        written = 0
        view = memoryview(data)
        while written < len(data):
            written += os.write(fd, view[written:])
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, dest)
        tmp_path = None
    except OSError as e:
        raise AtomicWriteError(f"atomic_write({destination}): {e}") from e
    finally:
        if fd != -1:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass


try:
    import fcntl as _fcntl
except ImportError:
    _fcntl = None

try:
    import msvcrt as _msvcrt
except ImportError:
    _msvcrt = None


class FileLock:
    """Cross-platform advisory file lock."""

    def __init__(self, path: Path):
        self.path = path
        self._fh: Any | None = None

    def acquire(self, timeout: float = 0.0) -> None:
        deadline = time.monotonic() + timeout
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            fh = open(self.path, "a+b")
            try:
                if _fcntl is not None:
                    _fcntl.flock(fh.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                elif _msvcrt is not None:
                    _msvcrt.locking(fh.fileno(), _msvcrt.LK_NBLCK, 1)
                self._fh = fh
                return
            except OSError as e:
                fh.close()
                if e.errno not in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                    raise
                if time.monotonic() >= deadline:
                    raise LockBusy(f"lock held elsewhere: {self.path}") from e
                time.sleep(0.05)

    def release(self) -> None:
        if self._fh is not None:
            try:
                if _fcntl is not None:
                    _fcntl.flock(self._fh.fileno(), _fcntl.LOCK_UN)
                elif _msvcrt is not None:
                    try:
                        self._fh.seek(0)
                        _msvcrt.locking(self._fh.fileno(), _msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
            finally:
                self._fh.close()
                self._fh = None

    def __enter__(self) -> "FileLock":
        if self._fh is None:
            self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


class BootLock:
    """Context manager for the engine boot lock."""

    def __init__(self, layout: Layout):
        self._lock = FileLock(layout.boot_lock)

    def __enter__(self) -> "BootLock":
        self._lock.acquire(timeout=0.0)
        return self

    def __exit__(self, *_exc: object) -> None:
        self._lock.release()


# ==============================================================================
# SYSTEM-LOAD SAMPLING (CROSS-PLATFORM)
# ==============================================================================
_PROC_MEMINFO = Path("/proc/meminfo")
_PROC_LOADAVG = Path("/proc/loadavg")
_TICKS = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100


def cpu_core_count() -> int:
    """Returns the number of available CPU cores."""
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except AttributeError:
        return max(1, os.cpu_count() or 1)


def read_psi_percent(kind: str) -> float | None:
    """Reads Linux PSI (Pressure Stall Information). Windows returns None."""
    if sys.platform == "win32":
        return None
    try:
        with open(f"/proc/pressure/{kind}", "rb") as fh:
            text = fh.read().decode("ascii", errors="replace")
    except OSError:
        return None

    want_full = want_some = None
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        flavor = parts[0]
        val = None
        for tok in parts[1:]:
            if tok.startswith("avg10="):
                try:
                    val = float(tok[len("avg10=") :])
                except ValueError:
                    val = None
                break
        if val is None:
            continue
        if flavor == "full":
            want_full = val
        elif flavor == "some":
            want_some = val
    return want_full if want_full is not None else want_some


def read_mem_available_mb() -> float | None:
    """Cross-platform memory availability. Uses ctypes on Windows, /proc on Linux."""
    if sys.platform == "win32":

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.wintypes.DWORD),
                ("dwMemoryLoad", ctypes.wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_uint64),
                ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64),
                ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64),
                ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return stat.ullAvailPhys / (1024.0 * 1024.0)
        return None

    try:
        with open(_PROC_MEMINFO, "rb") as fh:
            for line in fh.read().decode("ascii", errors="replace").splitlines():
                if line.startswith("MemAvailable:"):
                    return float(line.split()[1]) / 1024.0
    except (OSError, IndexError, ValueError):
        pass
    return None


def read_load1() -> float | None:
    """Reads 1-minute load average. Windows returns None."""
    if sys.platform == "win32":
        return None
    try:
        with open(_PROC_LOADAVG, "rb") as fh:
            return float(fh.read().split()[0])
    except (OSError, IndexError, ValueError):
        return None


def _proc_self_cpu_ticks() -> tuple:
    """Reads /proc/self/stat for CPU ticks. Windows returns (0, 0)."""
    if sys.platform == "win32":
        return 0, 0
    try:
        with open("/proc/self/stat", "rb") as fh:
            fields = fh.read().rsplit(b")", 1)[1].split()
            utime, stime, cutime, cstime = (int(x) for x in fields[11:15])
            return utime + stime, cutime + cstime
    except (OSError, IndexError, ValueError):
        return 0, 0


@dataclass(frozen=True, slots=True)
class LoadSample:
    """Snapshot of system load metrics."""

    psi_mem: float | None
    psi_io: float | None
    avail_mb: float | None
    load1_ratio: float | None
    self_cpu_pct: float
    mono: float

    def degrade(self) -> str:
        """Determines the degradation mode based on available metrics."""
        if self.psi_mem is None and self.psi_io is None:
            if self.avail_mb is None:
                return "FIXED-POLITE"
            return "MEMONLY"
        return "FULL"


# ==============================================================================
# ADAPTIVE GOVERNOR
# ==============================================================================
class Governor:
    """
    Adaptive throttle controller.
    Optimized for 8GB RAM / HDD: Aggressively yields to OS/Chrome
    when memory drops below 1.2GB. Falls back to MEMONLY mode on Windows.
    """

    SAMPLE_INTERVAL_S = 0.10
    BLAME_CPU_PCT = 50.0

    def __init__(
        self,
        cfg: Config,
        recorder: Callable[[int, int, str], None] | None = None,
        renice_hook: Callable[[int], None] | None = None,
    ) -> None:
        self.cfg = cfg
        self.recorder = recorder
        self.renice_hook = renice_hook
        self.mode = "FULL"

        probe_mem = read_mem_available_mb()
        probe_psi = read_psi_percent("memory")

        if not cfg.gov_enabled or probe_psi is None and probe_mem is None:
            self.mode = "FIXED-POLITE"
        elif probe_psi is None:
            self.mode = "MEMONLY"

        self._level = 0
        self._hist: deque = deque(maxlen=3)
        self._last_sample_mono = 0.0
        self._last: LoadSample | None = None
        self._prev_ticks = _proc_self_cpu_ticks()
        self._prev_tick_mono = time.monotonic()
        self._reniced = False
        self._desc_holds = 0
        self._recovery_hits = 0
        self._in_pause = False
        self._pause_started_mono = 0.0
        self._sleep_rng = random.Random(os.getpid() ^ time.monotonic_ns())

    @property
    def level(self) -> int:
        return self._level

    @property
    def child_should_freeze(self) -> bool:
        return self._in_pause

    @property
    def active_level(self) -> int:
        return 3 if self._in_pause else self._level

    def sample(self) -> LoadSample:
        """Takes a system load sample and updates internal state."""
        now = time.monotonic()
        psi_mem = read_psi_percent("memory")
        psi_io = read_psi_percent("io")
        avail = read_mem_available_mb()
        load = read_load1()
        ticks_self, ticks_children = _proc_self_cpu_ticks()

        dt = now - self._prev_tick_mono
        if dt <= 0.0:
            dt = 1e-6

        total_delta = (ticks_self - self._prev_ticks[0]) + (
            ticks_children - self._prev_ticks[1]
        )
        pct = total_delta / (_TICKS * dt * cpu_core_count()) * 100.0
        pct = max(0.0, min(pct, 400.0))

        self._prev_ticks = (ticks_self, ticks_children)
        self._prev_tick_mono = now
        self._last_sample_mono = now

        s = LoadSample(
            psi_mem=psi_mem,
            psi_io=psi_io,
            avail_mb=avail,
            load1_ratio=(load / cpu_core_count()) if load is not None else None,
            self_cpu_pct=pct,
            mono=now,
        )
        self._last = s
        self.mode = s.degrade() if self.cfg.gov_enabled else "FIXED-POLITE"

        if self.mode != "FIXED-POLITE":
            self._advance(s)
        return s

    def _classify(self, s: LoadSample) -> dict:
        c = self.cfg
        psi_eff = s.psi_mem if s.psi_mem is not None else 0.0
        avail_inf = s.avail_mb if s.avail_mb is not None else 1e12
        return {
            "p1": psi_eff >= c.gov_soft_psi or avail_inf < c.gov_soft_avail_mb,
            "p2": psi_eff >= c.gov_hard_psi or avail_inf < c.gov_hard_avail_mb,
            "p3": psi_eff >= c.gov_pause_psi or avail_inf < c.gov_pause_avail_mb,
            "recover_ok": (
                psi_eff < c.gov_hard_psi and avail_inf > c.gov_soft_avail_mb
            ),
        }

    def _advance(self, s: LoadSample) -> None:
        """Updates governor level based on load sample history."""
        cls = self._classify(s)
        self._hist.append(cls)
        n = len(self._hist)

        pause_avail_instant = (
            s.avail_mb is not None and s.avail_mb < self.cfg.gov_pause_avail_mb
        )
        if not self._in_pause and pause_avail_instant:
            self._enter_pause(reason="avail-floor")

        if cls["recover_ok"]:
            self._recovery_hits += 1
        else:
            self._recovery_hits = 0

        hits1 = sum(1 for h in self._hist if h["p1"])
        hits2 = sum(1 for h in self._hist if h["p2"])
        candidate = 0

        if n >= 2 and hits1 >= 2:
            candidate = 1
        if n >= 2 and hits2 >= 2:
            candidate = 2
        if s.avail_mb is not None and s.avail_mb < self.cfg.gov_hard_avail_mb:
            candidate = 2
        elif s.avail_mb is not None and s.avail_mb < self.cfg.gov_soft_avail_mb:
            candidate = max(candidate, 1)

        prev = self._level
        if candidate > prev:
            self._set_level(candidate, "escalate(psi/avail/load)")
            self._desc_holds = 0
        elif candidate < prev:
            self._desc_holds += 1
            if self._desc_holds >= 2:
                self._set_level(prev - 1, "deescalate(step-down)")
                self._desc_holds = 0
        else:
            self._desc_holds = 0

    def _set_level(self, new: int, reason: str) -> None:
        if new == self._level:
            return
        old = self._level
        self._level = new
        if self.recorder:
            try:
                self.recorder(old, new, reason)
            except Exception:
                pass

    def _enter_pause(self, reason: str) -> None:
        if self._in_pause:
            return
        self._in_pause = True
        self._pause_started_mono = time.monotonic()
        self._set_level(3, f"pause:{reason}")

    def _exit_pause(self, forced: bool) -> None:
        self._in_pause = False
        self._set_level(2, "resume:" + ("forced-cap" if forced else "recovered"))
        self._recovery_hits = 0

    def gate(self, label: str = "") -> None:
        """Blocks execution if system load is too high."""
        if self.mode == "FIXED-POLITE":
            time.sleep(self.cfg.gov_min_gate_ms * 4 / 1000.0)
            return

        now = time.monotonic()
        if now - self._last_sample_mono >= self.SAMPLE_INTERVAL_S:
            self.sample()

        lvl = self.active_level
        if lvl <= 0:
            return

        if lvl >= 3:
            entered = self._pause_started_mono
            forced_deadline = entered + self.cfg.gov_max_pause_s
            while True:
                time.sleep(0.20)
                _ = self.sample()
                if self._recovery_hits >= 2:
                    self._exit_pause(forced=False)
                    break
                if time.monotonic() >= forced_deadline:
                    self._exit_pause(forced=True)
                    break
            return

        if lvl == 1:
            delay = self._sleep_rng.uniform(0.025, 0.075)
        else:
            delay = self._sleep_rng.uniform(0.10, 0.40)
        time.sleep(delay)

    def snapshot(self) -> dict:
        """Returns current governor state as a dictionary."""
        s = self._last
        return {
            "mode": self.mode,
            "level": self.active_level,
            "in_pause": self._in_pause,
            "psi_mem": s.psi_mem if s else None,
            "psi_io": s.psi_io if s else None,
            "avail_mb": s.avail_mb if s else None,
            "self_cpu_pct": round(s.self_cpu_pct, 2) if s else None,
        }


# ==============================================================================
# PERSISTENT STORE (SQLite WAL)
# ==============================================================================
class Store:
    """Thread-serialized SQLite facade. WAL journal, optimized for low RAM."""

    def __init__(self, db_path: Path) -> None:
        self.path = db_path
        self._lock = threading.RLock()
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            str(db_path), timeout=5.0, check_same_thread=False, isolation_level=None
        )
        # Potato PC optimized: 2MB cache, WAL mode
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA cache_size=-2000")

    def close(self) -> None:
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def begin_run(self, verb: str, mode: str) -> int:
        """Starts a new forensic run and returns the run ID."""
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO runs (verb, mode, started_utc) VALUES (?, ?, ?)",
                (verb, mode, iso_utc()),
            )
            return cursor.lastrowid

    def finalize_run(self, run_id: int, **fields: Any) -> None:
        """Finalizes a forensic run with parameterized queries.

        Args:
            run_id: The database ID of the run to finalize.
            **fields: Keyword arguments for columns to update. Only whitelisted
                     columns are accepted to prevent SQL injection.

        Raises:
            ValueError: If an invalid column name is provided.
        """
        # Whitelist allowed column names to prevent SQL injection
        ALLOWED_COLUMNS: Final[frozenset[str]] = frozenset(
            {
                "ended_utc",
                "exit_code",
                "artifacts_json",
                "issues_json",
                "notes",
                "status",
            }
        )

        with self._lock:
            # Validate and filter field names
            validated_fields: dict[str, Any] = {}
            for key, value in fields.items():
                if key not in ALLOWED_COLUMNS:
                    msg = f"Invalid column name: {key}. Allowed: {ALLOWED_COLUMNS}"
                    raise ValueError(msg)
                validated_fields[key] = value

            if not validated_fields:
                return  # Nothing to update

            # Build query with validated column names (safe due to whitelist)
            sets = ", ".join(f"{k} = ?" for k in validated_fields)
            vals = list(validated_fields.values()) + [run_id]
            self._conn.execute(f"UPDATE runs SET {sets} WHERE id = ?", vals)  # nosec B608 - column names validated against whitelist
            self._conn.commit()

    def add_issues(self, run_id: int, issues: Iterator[Issue]) -> int:
        """Bulk inserts issues for a run."""
        count = 0
        created = iso_utc()
        with self._lock:
            cursor = self._conn.executemany(
                "INSERT INTO issues (run_id, source, code, severity, path, "
                "line_start, line_end, col, message, qualname, explanation, "
                "fingerprint, dedupe_key, payload, created_utc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (issue.to_row(run_id, created) for issue in issues),
            )
            count = cursor.rowcount
        return count

    def journal(self, actor: str, action: str, detail: dict | None = None) -> None:
        """Appends an entry to the audit journal."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO journal (actor, action, detail, created_utc) VALUES (?, ?, ?, ?)",
                (actor, action, json.dumps(detail or {}), iso_utc()),
            )
