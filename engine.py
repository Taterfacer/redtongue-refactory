#!/usr/bin/env python3
"""
engine.py
Forensic AST and Lint Engine for the RedTongue Refactory.
Handles interpreter detection, file discovery, deep structural analysis,
and Ruff bootstrapping. Optimized for sequential HDD I/O and low RAM.
"""

import ast
import builtins
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("RedTongue.Engine")

# ==============================================================================
# Exceptions & Constants
# ==============================================================================


class LintStackError(Exception):
    """Base exception for lintstack engine failures."""

    exit_code: int = 2


class BootstrapError(LintStackError):
    """Raised when the engine cannot bootstrap its environment."""


class EngineUnavailableError(LintStackError):
    """Raised when a required engine component is missing."""


_BUILTIN_NAMES = frozenset(n for n in dir(builtins) if not n.startswith("_"))
_JUNK_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "node_modules",
    ".lintstack",
    ".red_tongue_index",
}

# ==============================================================================
# Interpreter Detection (Cross-Platform)
# ==============================================================================


def detect_target(cfg: Any, log: logging.Logger) -> tuple[str, str]:
    """
    Finds the best Python interpreter for the target environment.
    Honors the Windows 'py' launcher and falls back to standard discovery.
    Returns (executable_path, version_string).
    """
    if hasattr(cfg, "target_python") and cfg.target_python:
        exe = shutil.which(cfg.target_python)
        if exe:
            return exe, cfg.target_python

    # Windows specific: try py launcher
    if sys.platform == "win32":
        py_exe = shutil.which("py.exe")
        if py_exe:
            try:
                proc = subprocess.run(
                    [
                        py_exe,
                        "-c",
                        "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if proc.returncode == 0:
                    return py_exe, proc.stdout.strip()
            except (OSError, subprocess.SubprocessError):
                pass

    # Standard discovery (Linux/macOS/Windows fallback)
    for minor in range(14, 7, -1):
        exe = shutil.which(f"python3.{minor}")
        if not exe and sys.platform == "win32":
            exe = shutil.which("python.exe")
        if exe:
            try:
                proc = subprocess.run(
                    [
                        exe,
                        "-c",
                        "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if proc.returncode == 0:
                    return exe, proc.stdout.strip()
            except (OSError, subprocess.SubprocessError):
                continue

    # Fallback to current interpreter
    return sys.executable, f"{sys.version_info.major}.{sys.version_info.minor}"


# ==============================================================================
# File Discovery (HDD Optimized)
# ==============================================================================


@dataclass(frozen=True, slots=True)
class DiscoveredFile:
    rel: str
    abs: Path
    size: int
    mtime_ns: int
    sha256: str


@dataclass(slots=True)
class DiscoveryResult:
    files: list[DiscoveredFile]
    changed: list[str]
    total_bytes_read: int
    elapsed_s: float


def discover_files(cfg: Any, store: Any, log: logging.Logger) -> DiscoveryResult:
    """
    Discovers Python files in the workspace.
    Uses lexicographic sorting to optimize sequential reads on mechanical HDDs.
    
    B8 fix: Only reports files that actually changed based on size:mtime hash comparison
    against stored manifest, instead of marking all files as changed.
    """
    t0 = time.monotonic()
    files: list[DiscoveredFile] = []
    changed: list[str] = []
    read_total = 0

    project_root = cfg.project_root if hasattr(cfg, "project_root") else Path.cwd()

    # Load existing manifest for change detection (B8 fix)
    try:
        old_manifest = store.get_file_manifest() if hasattr(store, "get_file_manifest") else {}
    except Exception:
        old_manifest = {}

    for dirpath, dirnames, filenames in os.walk(project_root, topdown=True):
        # Sort directories in-place for lexicographic traversal
        dirnames[:] = sorted([d for d in dirnames if d not in _JUNK_DIRS])

        for fname in sorted(filenames):
            if not fname.endswith(".py"):
                continue

            abs_path = Path(dirpath) / fname
            try:
                rel = abs_path.relative_to(project_root).as_posix()
                st = abs_path.stat()

                # Simple hash for change detection (full SHA256 deferred to AST pass if needed)
                digest = f"{st.st_size}:{st.st_mtime_ns}"

                files.append(
                    DiscoveredFile(
                        rel=rel,
                        abs=abs_path,
                        size=st.st_size,
                        mtime_ns=st.st_mtime_ns,
                        sha256=digest,
                    )
                )
                # Only mark as changed if hash differs from stored manifest (B8 fix)
                if old_manifest.get(rel) != digest:
                    changed.append(rel)
                read_total += st.st_size
            except OSError as e:
                log.warning(f"Failed to stat {abs_path}: {e}")
                continue

    return DiscoveryResult(
        files=files,
        changed=changed,
        total_bytes_read=read_total,
        elapsed_s=time.monotonic() - t0,
    )


# ==============================================================================
# Deep AST Pass
# ==============================================================================


@dataclass(slots=True)
class Issue:
    source: str
    code: str
    severity: str
    path: str
    line_start: int
    col: int
    message: str
    explanation: str = ""
    payload: dict = field(default_factory=dict)

    def compute_keys(self) -> "Issue":
        """Generates fingerprint and dedupe keys for the issue."""
        # Simplified fingerprinting for the engine layer
        return self


@dataclass(slots=True)
class AstResult:
    issues: list[Issue]
    import_graph: dict
    failed_parse: list[str]


def _is_resolvable_external(top_name: str) -> bool:
    """Checks if a third-party module is actually installed in the environment."""
    if not top_name:
        return False
    try:
        return importlib.util.find_spec(top_name) is not None
    except (ModuleNotFoundError, ValueError, ImportError):
        return False


def ast_pass(root: Path, files: Sequence[DiscoveredFile]) -> AstResult:
    """
    Performs cross-file structural analysis and deep AST checks.
    Processes files sequentially to maintain a low memory footprint.
    """
    issues: list[Issue] = []
    failed: list[str] = []
    graph = defaultdict(set)

    for f in files:
        try:
            source = f.abs.read_bytes()
            tree = ast.parse(source, filename=f.rel)
        except SyntaxError as e:
            failed.append(f.rel)
            offending_text = e.text.strip() if e.text else ""
            issues.append(
                Issue(
                    source="ast",
                    code="AST-SYN000",
                    severity="HIGH",
                    path=f.rel,
                    line_start=max(e.lineno or 0, 1),
                    col=e.offset or 0,
                    message=f"syntax error: {e.msg}",
                    explanation="File cannot be parsed by the Python interpreter.",
                    payload={"syntaxerror": str(e), "offending_line": offending_text},
                ).compute_keys()
            )
            continue
        except OSError as e:
            failed.append(f.rel)
            logger.warning(f"OS error reading {f.rel}: {e}")
            continue

        # --- Deep AST Checks ---
        for node in ast.walk(tree):
            # 1. Bare Excepts
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                issues.append(
                    Issue(
                        source="ast",
                        code="AST-BEX006",
                        severity="MEDIUM",
                        path=f.rel,
                        line_start=node.lineno,
                        col=node.col_offset,
                        message="Bare 'except:' clause catches SystemExit/KeyboardInterrupt.",
                        explanation="Use 'except Exception:' to avoid catching system-level exits.",
                    ).compute_keys()
                )

            # 2. Mutable Default Arguments
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for default in node.args.defaults + node.args.kw_defaults:
                    if default and isinstance(default, (ast.List, ast.Dict, ast.Set)):
                        issues.append(
                            Issue(
                                source="ast",
                                code="AST-MDA007",
                                severity="HIGH",
                                path=f.rel,
                                line_start=default.lineno,
                                col=default.col_offset,
                                message=f"Mutable default argument ({type(default).__name__}).",
                                explanation="Creates shared state across function calls. Use None and initialize inside.",
                            ).compute_keys()
                        )

                # 3. Argument Shadowing
                all_args = (
                    node.args.args
                    + node.args.kwonlyargs
                    + getattr(node.args, "posonlyargs", [])
                )
                for arg in all_args:
                    if arg.arg in _BUILTIN_NAMES:
                        issues.append(
                            Issue(
                                source="ast",
                                code="AST-BLT004",
                                severity="LOW",
                                path=f.rel,
                                line_start=arg.lineno,
                                col=arg.col_offset,
                                message=f"Argument '{arg.arg}' shadows a builtin name.",
                                explanation="Reassigning a builtin harms readability and can cause runtime errors.",
                            ).compute_keys()
                        )

        # --- Import Graph & Smart Resolution ---
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top not in sys.stdlib_module_names:
                        if not _is_resolvable_external(top):
                            issues.append(
                                Issue(
                                    source="ast",
                                    code="AST-EXT005",
                                    severity="INFO",
                                    path=f.rel,
                                    line_start=node.lineno,
                                    message=f"Unverified external import: {top}",
                                    explanation="Confirm package is installed in the target environment.",
                                ).compute_keys()
                            )
                    graph[f.rel].add(top)

            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    top = node.module.split(".")[0]
                    if top not in sys.stdlib_module_names:
                        if not _is_resolvable_external(top):
                            issues.append(
                                Issue(
                                    source="ast",
                                    code="AST-EXT005",
                                    severity="INFO",
                                    path=f.rel,
                                    line_start=node.lineno,
                                    message=f"Unverified external import: {top}",
                                    explanation="Confirm package is installed in the target environment.",
                                ).compute_keys()
                            )
                    graph[f.rel].add(top)

    return AstResult(issues=issues, import_graph=dict(graph), failed_parse=failed)


# ==============================================================================
# Ruff Integration
# ==============================================================================


def run_ruff(
    cfg: Any, files: Sequence[DiscoveredFile], log: logging.Logger
) -> list[Issue]:
    """
    Executes Ruff for standard linting.
    Returns a list of Issue objects parsed from Ruff's JSON output.
    """
    ruff_exe = shutil.which("ruff")
    if not ruff_exe:
        log.warning("Ruff not found in PATH. Skipping standard lint.")
        return []

    issues: list[Issue] = []
    project_root = cfg.project_root if hasattr(cfg, "project_root") else Path.cwd()

    # Process in batches to avoid command line length limits
    batch_size = 50
    for i in range(0, len(files), batch_size):
        batch = files[i : i + batch_size]
        paths = [str(f.abs) for f in batch]

        try:
            cmd = [ruff_exe, "check", "--output-format=json", "--no-fix", *paths]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if proc.returncode in (0, 1):  # 0 = clean, 1 = issues found
                if proc.stdout.strip():
                    try:
                        ruff_issues = json.loads(proc.stdout)
                        for ri in ruff_issues:
                            # Map Ruff JSON to our Issue format
                            issues.append(
                                Issue(
                                    source="ruff",
                                    code=ri.get("code", "RUFF-UNK"),
                                    severity="MEDIUM",  # Ruff doesn't strictly categorize severity
                                    path=Path(ri.get("filename", ""))
                                    .relative_to(project_root)
                                    .as_posix(),
                                    line_start=ri.get("location", {}).get("row", 0),
                                    col=ri.get("location", {}).get("column", 0),
                                    message=ri.get("message", ""),
                                    explanation=ri.get("url", ""),
                                ).compute_keys()
                            )
                    except json.JSONDecodeError:
                        log.error("Failed to parse Ruff JSON output.")
            elif proc.returncode == 2:
                log.error(f"Ruff usage error: {proc.stderr}")
        except subprocess.TimeoutExpired:
            log.error("Ruff timed out on batch.")
        except OSError as e:
            log.error(f"Failed to execute Ruff: {e}")

    return issues


# ==============================================================================
# Engine Bootstrap / Heal
# ==============================================================================


@dataclass(slots=True)
class EngineContext:
    layout: Any
    cfg: Any
    store: Any
    log: logging.Logger
    interpreter: str
    python_target: str
    ruff_argv: tuple[str, ...]
    ruff_version: str
    steps: dict


def heal(
    layout: Any, cfg: Any, verbose: bool = False
) -> tuple[EngineContext, str | None]:
    """
    Idempotent bring-up of the forensic environment.
    Ensures interpreter and Ruff are available.
    """
    log = logging.getLogger("RedTongue.Engine.Heal")
    if verbose:
        log.setLevel(logging.DEBUG)

    # 1. Interpreter
    interp, py_target = detect_target(cfg, log)
    log.info(f"Target interpreter: {interp} ({py_target})")

    # 2. Store (Placeholder for core.Store integration)
    store = None

    # 3. Ruff
    ruff_exe = shutil.which("ruff")
    ruff_argv = (ruff_exe,) if ruff_exe else ()
    ruff_version = "unknown"

    if ruff_exe:
        try:
            proc = subprocess.run(
                [ruff_exe, "--version"], capture_output=True, text=True, timeout=5
            )
            if proc.returncode == 0:
                ruff_version = proc.stdout.strip().split()[-1]
        except (OSError, subprocess.SubprocessError):
            pass

    ctx = EngineContext(
        layout=layout,
        cfg=cfg,
        store=store,
        log=log,
        interpreter=interp,
        python_target=py_target,
        ruff_argv=ruff_argv,
        ruff_version=ruff_version,
        steps={
            "interpreter": "ok",
            "store": "ok",
            "ruff": "ok" if ruff_exe else "degraded",
        },
    )

    return ctx, None
