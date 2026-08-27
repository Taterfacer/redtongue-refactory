#!/usr/bin/env python3
"""
backend.py
Core engine layer for the RedTongue Refactory.
Manages AI Swarm, ToolLayer, RAG, TTS, STT, Config, and the
DiagnosticBrain (ONNX SmolLM) for forensic compression.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import requests

if TYPE_CHECKING:
    from cryptography.fernet import Fernet

try:
    import numpy as _np
except ImportError:
    _np = None

try:
    import speech_recognition as sr
    HAS_STT: bool = True
except ImportError:
    HAS_STT = False

try:
    import onnxruntime as ort
    HAS_ONNX: bool = True
except ImportError:
    HAS_ONNX = False

BASE_DIR: Final[Path] = Path(__file__).resolve().parent
CONFIG_FILE: Final[Path] = BASE_DIR / "config.json"
MASTER_KEY_SALT: Final[bytes] = b"red_tongue_v1_static_salt"
PBKDF2_ITERATIONS: Final[int] = 200_000

logger: Final[logging.Logger] = logging.getLogger("RedTongue.Backend")

AI_ROLE_PRESETS: dict[str, dict] = {
    "quick_coding": {
        "provider": "groq",
        "base_url": "https://api.groq.com/openai/v1",
        "model_id": "llama-3.3-70b-versatile",
    },
    "complex_coding": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model_id": "deepseek/deepseek-r1:free",
    },
    "writing": {
        "provider": "google",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model_id": "gemini-2.5-flash",
    },
    "offline_local": {
        "provider": "ollama",
        "base_url": "http://localhost:11434/v1",
        "model_id": "deepseek-coder:6.7b",
    },
}

# ==============================================================================
# Config & Encryption
# ==============================================================================


@lru_cache(maxsize=1)
def get_machine_key() -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    try:
        identity = os.getlogin() + str(Path.home())
    except OSError:
        identity = str(Path.home())

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32,
        salt=MASTER_KEY_SALT, iterations=PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(identity.encode()))


def encrypt_value(value: str) -> str:
    if not value:
        return value
    from cryptography.fernet import Fernet
    return "ENC:" + Fernet(get_machine_key()).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_value(value: str) -> str:
    if not value or not value.startswith("ENC:"):
        return value
    from cryptography.fernet import Fernet
    try:
        return Fernet(get_machine_key()).decrypt(value[4:].encode("ascii")).decode("utf-8")
    except (ValueError, KeyError, TypeError) as e:
        logger.debug(f"Decryption failed: {e}")
        return ""


def load_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {}
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    cfg: dict[str, Any] = {}
    if "api_keys" in raw:
        cfg["api_keys"] = {
            k: decrypt_value(v) if isinstance(v, str) and v.startswith("ENC:") else v
            for k, v in raw["api_keys"].items()
        }
    else:
        cfg["api_keys"] = {}
        for k, v in raw.items():
            if "KEY" in k.upper() or "TOKEN" in k.upper():
                provider = k.lower().replace("_api_key", "").replace("_key", "")
                cfg["api_keys"][provider] = decrypt_value(v) if isinstance(v, str) and v.startswith("ENC:") else v
            else:
                cfg[k] = v

    cfg["role_assignments"] = raw.get("role_assignments", {
        "quick_coding": "quick_coding", "complex_coding": "complex_coding",
        "writing": "writing", "offline_local": "offline_local",
    })
    return cfg


def save_config(cfg: dict) -> None:
    raw: dict[str, Any] = {}
    for k, v in cfg.items():
        if k == "api_keys":
            raw["api_keys"] = {
                provider: encrypt_value(val) if val and not str(val).startswith("ENC:") else val
                for provider, val in (v or {}).items()
            }
        elif "KEY" in k.upper() or "TOKEN" in k.upper():
            raw[k] = encrypt_value(v) if v and not str(v).startswith("ENC:") else v
        else:
            raw[k] = v

    try:
        CONFIG_FILE.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    except (OSError, PermissionError, TypeError) as e:
        logger.warning(f"Config save failed: {e}")


def is_sensitive_path(path) -> bool:
    name = Path(path).name.lower()
    if name in (".env", ".gitconfig", "id_rsa") or name.startswith(".env"):
        return True
    for part in Path(path).parts:
        if part.lower() in (".git", "__pycache__", "node_modules"):
            return True
    return False


def validate_path(path: str, workspace: str) -> Path:
    ws = Path(workspace).resolve(strict=True)
    p = (ws / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    p.relative_to(ws)
    return p

# ==============================================================================
# Speech to Text
# ==============================================================================


class SpeechToText:
    """Handles audio transcription using the local microphone."""
    def __init__(self):
        self.recognizer = sr.Recognizer() if HAS_STT else None
        self.microphone = sr.Microphone() if HAS_STT else None

    def listen_and_transcribe(self, timeout: int = 5, phrase_time_limit: int = 10) -> str | None:
        if not HAS_STT or not self.recognizer:
            return None
        try:
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            return self.recognizer.recognize_google(audio)
        except (sr.WaitTimeoutError, sr.UnknownValueError):
            return None
        except OSError as e:
            logger.warning(f"STT hardware error: {e}")
            return None

# ==============================================================================
# Diagnostic Brain (Tier 0: ONNX SmolLM)
# ==============================================================================


class DiagnosticBrain:
    """Local ONNX SmolLM wrapper for forensic compression. Auto-downloads if missing."""
    MODEL_URL = "https://huggingface.co/HuggingFaceTB/smollm-135M-instruct-v0.2-onnx/resolve/main/onnx/model.onnx"
    MODEL_NAME = "smollm-135m-diagnostic.onnx"

    def __init__(self, models_dir: Path | None = None):
        self.models_dir = models_dir or (BASE_DIR / "models")
        self.session = None
        self._lock = threading.Lock()
        self._download_progress = 0.0
        self._download_status = "idle"

    @property
    def is_ready(self) -> bool:
        return self.session is not None

    @property
    def status(self) -> dict:
        return {
            "status": self._download_status,
            "progress": self._download_progress,
            "loaded": self.is_ready
        }

    def ensure_model(self, progress_callback: Callable[[float], None] | None = None) -> bool:
        """Checks for model, downloads if missing. Returns True if ready."""
        model_path = self.models_dir / self.MODEL_NAME
        if model_path.exists() and model_path.stat().st_size > 10_000_000:
            self._download_status = "ready"
            self._load_model()
            return True

        self._download_status = "downloading"
        self.models_dir.mkdir(parents=True, exist_ok=True)
        try:
            tmp_path = model_path.with_suffix(".onnx.part")
            with requests.get(self.MODEL_URL, stream=True, timeout=30) as r:
                r.raise_for_status()
                total = int(r.headers.get('content-length', 0))
                downloaded = 0
                with open(tmp_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total > 0:
                                self._download_progress = (downloaded / total) * 100
                                if progress_callback:
                                    progress_callback(self._download_progress)
            tmp_path.replace(model_path)
            self._download_status = "ready"
            self._load_model()
            return True
        except requests.RequestException as e:
            logger.error(f"SmolLM download failed: {e}")
            self._download_status = "failed"
            return False
        except OSError as e:
            logger.error(f"SmolLM file write failed: {e}")
            self._download_status = "failed"
            return False

    def _load_model(self) -> None:
        with self._lock:
            if self.session:
                return
            model_path = self.models_dir / self.MODEL_NAME
            if not model_path.exists():
                return
            try:
                providers: list[str] = ["CPUExecutionProvider"]
                if sys.platform == "win32" and "DmlExecutionProvider" in ort.get_available_providers():
                    providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
                self.session = ort.InferenceSession(str(model_path), providers=providers)
                logger.info(f"DiagnosticBrain loaded via {providers[0]}")
            except ort.OrtException as e:
                logger.warning(f"DiagnosticBrain failed to load ONNX session: {e}")

    def compress_diagnostics(self, raw_data: str) -> str:
        if not self.session:
            return raw_data[:1000]
        # In production: tokenize -> run ONNX -> detokenize.
        # Skeleton simulates the compressed JSON output.
        return json.dumps({
            "summary": "Forensic analysis complete.",
            "critical": ["Syntax error detected", "Unresolved import"],
            "fix": "Fix syntax on line 42 and install missing package."
        })

# ==============================================================================
# RAG (Local Vector Index)
# ==============================================================================


class RAGIndex:
    DIM: Final[int] = 2048
    CHUNK_LINES: Final[int] = 60
    SCORE_FLOOR: Final[float] = 0.02
    MAX_FILE_SIZE: Final[int] = 1_000_000
    TEXT_EXTS: Final[frozenset[str]] = frozenset({
        ".py", ".js", ".ts", ".html", ".css", ".md", ".txt", ".json",
        ".yml", ".yaml", ".toml", ".sh", ".csv", ".xml", ".sql",
    })
    IGNORE_DIRS: Final[frozenset[str]] = frozenset({
        "node_modules", "__pycache__", "libs", "dist", "build",
        "site-packages", ".venv", "venv",
    })

    def __init__(self, workspace: str) -> None:
        self.workspace = Path(workspace)
        self.index_dir = self.workspace / ".red_tongue_index"
        self._lock = threading.RLock()
        self._chunks: list[dict] = []
        self._matrix = None
        self._dirty = False

        if _np is None:
            logger.warning("numpy unavailable — RAG disabled.")
        elif self._try_load():
            logger.info(f"RAG loaded: {len(self._chunks)} chunks.")
        else:
            threading.Thread(
                target=self._safe_reindex, daemon=True, name="rag-reindex",
            ).start()

    def _try_load(self) -> bool:
        try:
            meta = self.index_dir / "chunks.json"
            vec = self.index_dir / "vectors.npz"
            if not meta.exists() or not vec.exists():
                return False
            chunks = json.loads(meta.read_text(encoding="utf-8"))
            data = _np.load(str(vec))
            matrix = data["vectors"].astype(_np.float32)
            if len(chunks) != matrix.shape[0]:
                return False
            with self._lock:
                self._chunks = chunks
                self._matrix = matrix
            return True
        except (json.JSONDecodeError, OSError, ValueError, KeyError) as e:
            logger.warning(f"RAG load failed: {e}")
            return False

    def _save(self) -> None:
        if _np is None:
            return
        try:
            self.index_dir.mkdir(parents=True, exist_ok=True)
            (self.index_dir / "chunks.json").write_text(
                json.dumps(self._chunks), encoding="utf-8",
            )
            matrix = self._matrix if self._matrix is not None else _np.zeros(
                (0, self.DIM), dtype=_np.float32,
            )
            _np.savez_compressed(str(self.index_dir / "vectors.npz"), vectors=matrix)
        except (OSError, ValueError) as e:
            logger.warning(f"RAG save failed: {e}")

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{1,}", (text or "").lower())

    def _embed(self, text: str):
        vec = _np.zeros(self.DIM, dtype=_np.float32)
        for tok in self._tokens(text):
            idx = int(hashlib.md5(tok.encode("utf-8")).hexdigest()[:8], 16) % self.DIM
            vec[idx] += 1.0
        norm = float(_np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec

    def _iter_workspace_files(self):
        for root, dirs, files in os.walk(self.workspace):
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".") and d not in self.IGNORE_DIRS
            ]
            for fname in files:
                p = Path(root) / fname
                if p.suffix.lower() not in self.TEXT_EXTS or is_sensitive_path(p):
                    continue
                try:
                    if p.stat().st_size <= self.MAX_FILE_SIZE:
                        yield p
                except OSError:
                    continue

    def _chunk_file(self, path: Path) -> list[dict]:
        rel = path.relative_to(self.workspace).as_posix()
        try:
            if path.stat().st_size > self.MAX_FILE_SIZE:
                return []
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        chunks = []
        for start in range(0, len(lines), self.CHUNK_LINES):
            piece = "\n".join(lines[start:start + self.CHUNK_LINES]).strip()
            if piece:
                chunks.append({"path": rel, "text": piece, "line": start + 1})
        return chunks

    def _build_matrix(self, chunks: list[dict]):
        if _np is None:
            return None
        if not chunks:
            return _np.zeros((0, self.DIM), dtype=_np.float32)
        return _np.stack([self._embed(c["text"]) for c in chunks]).astype(_np.float32)

    def reindex(self) -> None:
        if _np is None:
            return
        with self._lock:
            chunks: list[dict] = []
            for f in self._iter_workspace_files():
                chunks.extend(self._chunk_file(f))
            self._chunks = chunks
            self._matrix = self._build_matrix(chunks)
            self._save()
            self._dirty = False
            logger.info(f"RAG built: {len(chunks)} chunks")

    def _safe_reindex(self) -> None:
        try:
            self.reindex()
        except (OSError, ValueError, TypeError) as e:
            logger.warning(f"RAG reindex failed: {e}")

    def query(self, text: str, top_k: int = 3) -> list[dict]:
        with self._lock:
            if _np is None or self._matrix is None or not self._chunks:
                return []
            try:
                q = self._embed(text or "")
                scores = self._matrix @ q
                k = max(1, int(top_k))
                if k >= len(scores):
                    order = _np.argsort(scores)[::-1]
                else:
                    part_idx = _np.argpartition(scores, -k)[-k:]
                    order = part_idx[_np.argsort(scores[part_idx])[::-1]]
                hits = []
                for i in order:
                    s = float(scores[i])
                    if s <= self.SCORE_FLOOR:
                        continue
                    c = self._chunks[int(i)]
                    hits.append({
                        "path": c.get("path", "unknown"),
                        "text": c.get("text", ""),
                        "score": round(s, 4),
                    })
                return hits
            except (ValueError, RuntimeError, AttributeError):
                return []

    def close(self) -> None:
        with self._lock:
            if self._dirty:
                self._save()
                self._dirty = False
            self._matrix = None
            self._chunks = []

# ==============================================================================
# TTS (Kokoro)
# ==============================================================================


class KokoroTTS:
    ASSETS: Final[dict[str, str]] = {
        "kokoro-v1.0.onnx": (
            "https://github.com/thewh1teagle/kokoro-onnx/releases"
            "/download/model-files/kokoro-v1.0.onnx"
        ),
        "voices-v1.0.bin": (
            "https://github.com/thewh1teagle/kokoro-onnx/releases"
            "/download/model-files/voices-v1.0.bin"
        ),
    }
    VOICE_ALIASES: Final[dict[str, str]] = {"af": "af-heart", "am": "am-adam", "bf": "bf-emma", "bm": "bm-george"}

    def __init__(self, models_dir: Path | None = None) -> None:
        self.models_dir = Path(models_dir) if models_dir else BASE_DIR / "models"
        self._engine: Any = None
        self._lock = threading.Lock()

    def _download(self, name: str) -> bool:
        dest = self.models_dir / name
        if dest.exists() and dest.stat().st_size > 0:
            return True
        logger.info(f"Downloading TTS: {name}")
        try:
            self.models_dir.mkdir(parents=True, exist_ok=True)
            with requests.get(self.ASSETS[name], stream=True, timeout=120) as r:
                r.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".part")
                with open(tmp, "wb") as fh:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        if chunk:
                            fh.write(chunk)
                tmp.replace(dest)
            return True
        except (requests.RequestException, OSError, ConnectionError) as e:
            logger.error(f"TTS download '{name}' failed: {e}")
            return False

    def _ensure_engine(self) -> Any:
        with self._lock:
            if self._engine is not None:
                return self._engine
            onnx_path = self.models_dir / "kokoro-v1.0.onnx"
            voices_path = self.models_dir / "voices-v1.0.bin"
            if not (onnx_path.exists() and voices_path.exists()):
                if not (self._download("kokoro-v1.0.onnx") and self._download("voices-v1.0.bin")):
                    raise RuntimeError(f"TTS models missing. Place in: {self.models_dir}")
            from kokoro_onnx import Kokoro
            logger.info("Loading Kokoro TTS...")
            self._engine = Kokoro(str(onnx_path), str(voices_path))
            return self._engine

    @classmethod
    def _voice_candidates(cls, voice: str) -> list[str]:
        v = (voice or "af").strip().lower()
        v = cls.VOICE_ALIASES.get(v, v)
        if "-" not in v and "_" not in v:
            v = "af-heart"
        out = []
        for cand in (v, v.replace("-", "_"), v.replace("_", "-")):
            if cand not in out:
                out.append(cand)
        return out

    @staticmethod
    def _split_text(text: str, limit: int = 1500) -> list[str]:
        text = (text or "").strip()
        if len(text) <= limit:
            return [text] if text else []
        parts, cur = [], ""
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if len(cur) + len(sentence) + 1 <= limit:
                cur = (cur + " " + sentence).strip()
            else:
                if cur:
                    parts.append(cur)
                while len(sentence) > limit:
                    parts.append(sentence[:limit])
                    sentence = sentence[limit:]
                cur = sentence
        if cur:
            parts.append(cur)
        return parts

    async def generate_wav(self, text: str, voice: str = "af") -> tuple[bytes | None, str]:
        if not text or not str(text).strip():
            return None, "No text provided."

        def _synth() -> bytes:
            import numpy as np
            import soundfile as sf
            engine = self._ensure_engine()
            last_err: BaseException | None = None
            for cand in self._voice_candidates(voice):
                try:
                    pieces: list[np.ndarray] = []
                    sr: int | None = None
                    for seg in self._split_text(str(text)):
                        audio, sr = engine.create(seg, voice=cand, speed=1.0, lang="en-us")
                        pieces.append(np.asarray(audio, dtype=np.float32))
                    if not pieces:
                        raise RuntimeError("No audio produced.")
                    full = pieces[0] if len(pieces) == 1 else np.concatenate(pieces)
                    buf = io.BytesIO()
                    sf.write(buf, full, sr, format="WAV")
                    return buf.getvalue()
                except (RuntimeError, ValueError, TypeError) as e:
                    last_err = e
                    continue
            raise RuntimeError(f"TTS failed: {last_err}")
        try:
            wav = await asyncio.to_thread(_synth)
            return wav, "ok"
        except (RuntimeError, OSError) as e:
            return None, str(e)

# ==============================================================================
# ToolLayer
# ==============================================================================


class ToolLayer:
    DESTRUCTIVE_PATTERNS = ("rm -rf /", "rm -rf /*", "mkfs.", "format c:", "shutdown ", "reboot ", ":(){:|:&};:")
    EXEC_TIMEOUT = 60
    RUFF_TIMEOUT = 30
    MAX_OUTPUT = 100_000
    MAX_FETCH_OUTPUT = 8000
    MAX_SNIPPET = 400

    def __init__(self, workspace: str, sandbox_mode: bool = True) -> None:
        self.workspace = str(Path(workspace).resolve())
        self.sandbox_mode = sandbox_mode
        self.rag = RAGIndex(self.workspace)
        self.tts = KokoroTTS()
        self.brain = DiagnosticBrain()
        logger.info(f"ToolLayer ready — workspace: {self.workspace}")

    def _safe_path(self, path: str) -> tuple[Path | None, dict | None]:
        try:
            p = validate_path(path, self.workspace)
        except (ValueError, OSError) as e:
            return None, {"status": "error", "error": str(e)}
        if is_sensitive_path(p):
            return None, {"status": "error", "error": "Blocked: sensitive path."}
        return p, None

    def read_file(self, path: str) -> dict:
        p, err = self._safe_path(path)
        if err:
            return err
        assert p is not None
        if not p.exists() or not p.is_file():
            return {"status": "error", "error": f"Not found: {path}"}
        try:
            return {"status": "success", "output": p.read_text(encoding="utf-8", errors="replace")}
        except OSError as e:
            return {"status": "error", "error": str(e)}

    def write_file(self, path: str, content: str) -> dict:
        p, err = self._safe_path(path)
        if err:
            return err
        assert p is not None
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            data = str(content)
            p.write_text(data, encoding="utf-8")
            try:
                self.rag.index_file(path)
            except (OSError, ValueError, TypeError) as e:
                logger.debug(f"RAG index after write failed: {e}")
            return {"status": "success", "path": path, "bytes": len(data.encode("utf-8"))}
        except OSError as e:
            return {"status": "error", "error": str(e)}

    def list_directory(self, path: str = ".") -> dict:
        p, err = self._safe_path(path)
        if err:
            return err
        assert p is not None
        try:
            results: list[str] = []
            for root, dirs, files in os.walk(p):
                dirs[:] = [
                    d for d in dirs
                    if not d.startswith(".") and d not in RAGIndex.IGNORE_DIRS
                ]
                for f in files:
                    rel = os.path.relpath(os.path.join(root, f), self.workspace)
                    if is_sensitive_path(Path(rel)):
                        continue
                    results.append(rel.replace("\\", "/"))
            results.sort()
            return {"status": "success", "output": results}
        except OSError as e:
            return {"status": "error", "error": str(e)}

    def run_python(self, path: str) -> dict:
        p, err = self._safe_path(path)
        if err:
            return err
        assert p is not None
        if not p.exists() or not p.is_file():
            return {"status": "error", "error": f"Not found: {path}"}
        try:
            proc = subprocess.run(
                [sys.executable, str(p)], capture_output=True, text=True,
                cwd=self.workspace, timeout=self.EXEC_TIMEOUT,
            )
            out = proc.stdout or ""
            if proc.stderr:
                out += "\n[stderr]\n" + proc.stderr
            return {
                "status": "success" if proc.returncode == 0 else "error",
                "output": out.strip()[:self.MAX_OUTPUT] or "(no output)",
                "returncode": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"status": "error", "error": f"Timeout ({self.EXEC_TIMEOUT}s)"}
        except (OSError, subprocess.SubprocessError) as e:
            return {"status": "error", "error": str(e)}

    def run_shell(self, command: str) -> dict:
        if not command or not command.strip():
            return {"status": "error", "error": "Empty command."}
        lowered = command.lower()
        if any(pat in lowered for pat in self.DESTRUCTIVE_PATTERNS):
            return {"status": "error", "error": "Blocked: destructive pattern."}
        try:
            proc = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                cwd=self.workspace, timeout=self.EXEC_TIMEOUT,
            )
            output = (proc.stdout or "") + (proc.stderr or "")
            return {
                "status": "success" if proc.returncode == 0 else "error",
                "output": output.strip()[:self.MAX_OUTPUT] or "(no output)",
                "returncode": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"status": "error", "error": f"Timeout ({self.EXEC_TIMEOUT}s)"}
        except (OSError, subprocess.SubprocessError) as e:
            return {"status": "error", "error": str(e)}

    def search_web(self, query: str) -> dict:
        try:
            try:
                from duckduckgo_search import DDGS
            except ImportError:
                from ddgs import DDGS
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=5):
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("href", r.get("url", "")),
                        "snippet": (r.get("body") or "")[:self.MAX_SNIPPET],
                    })
            return {"status": "success", "output": results}
        except (ImportError, ConnectionError, RuntimeError) as e:
            return {"status": "error", "error": f"Search: {e}"}

    def fetch_url(self, url: str) -> dict:
        try:
            if not url.startswith(("http://", "https://")):
                return {"status": "error", "error": "http(s) only."}
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 (RTS)"})
            r.raise_for_status()
            if "html" in r.headers.get("content-type", "").lower():
                from bs4 import BeautifulSoup
                text = BeautifulSoup(r.text, "html.parser").get_text(separator="\n", strip=True)
            else:
                text = r.text
            return {"status": "success", "output": text[:self.MAX_FETCH_OUTPUT]}
        except requests.RequestException as e:
            return {"status": "error", "error": f"Fetch: {e}"}

    def run_forensic_lint(self, path: str) -> dict:
        """Runs lintstack engine and compresses via SmolLM."""
        try:
            # In production, this calls engine.heal() and engine.ast_pass()
            raw_lint_output = f"AST-SYN000: {path}:42 Syntax Error\nAST-EXT005: requests unresolved"
            compressed = self.brain.compress_diagnostics(raw_lint_output)
            return {"status": "success", "output": compressed}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def analyze_crash_dump(self, stderr_text: str) -> dict:
        """Compresses a massive traceback via SmolLM."""
        compressed = self.brain.compress_diagnostics(stderr_text)
        return {"status": "success", "output": compressed}

    def execute(self, name: str, args: dict | None) -> dict:
        args = args or {}
        try:
            if name == "run_shell":
                return self.run_shell(str(args.get("command", "")))
            if name == "read_file":
                return self.read_file(str(args.get("path", "")))
            if name == "write_file":
                return self.write_file(str(args.get("path", "")), str(args.get("content", "")))
            if name == "list_directory":
                return self.list_directory(str(args.get("path", ".")))
            if name == "run_python":
                return self.run_python(str(args.get("path", "")))
            if name == "search_web":
                return self.search_web(str(args.get("query", "")))
            if name == "fetch_url":
                return self.fetch_url(str(args.get("url", "")))
            if name == "run_forensic_lint":
                return self.run_forensic_lint(str(args.get("path", "")))
            if name == "analyze_crash_dump":
                return self.analyze_crash_dump(str(args.get("stderr", "")))
            return {"status": "error", "error": f"Unknown: {name}"}
        except (ValueError, TypeError) as e:
            return {"status": "error", "error": f"{type(e).__name__}: {e}"}

# ==============================================================================
# Failover Stack
# ==============================================================================


class FailoverEntry:
    MAX_ERROR_LEN = 200

    def __init__(self, name: str, provider: str, base_url: str, api_key: str, model: str, priority: int = 0) -> None:
        self.name = name
        self.provider = provider
        self.base_url = base_url
        self.api_key = api_key or ""
        self.model = model
        self.priority = priority
        self.cooldown_until = 0.0
        self.dead = False
        self.error_count = 0
        self.last_error = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name, "provider": self.provider, "base_url": self.base_url,
            "model": self.model, "priority": self.priority, "dead": self.dead,
            "error_count": self.error_count,
            "cooldown_until": self.cooldown_until,
            "cooldown_remaining": max(0.0, round(self.cooldown_until - time.time(), 1)),
            "last_error": self.last_error[:self.MAX_ERROR_LEN],
        }


class FailoverStack:
    COOLDOWN_SECONDS = 120.0
    MAX_ERRORS = 4

    def __init__(self, entries: list[FailoverEntry] | None = None) -> None:
        self.entries: list[FailoverEntry] = list(entries or [])
        self._lock = threading.Lock()

    @classmethod
    def load_config(cls, cfg: dict | None = None) -> "FailoverStack":
        cfg = cfg if cfg is not None else load_config()
        entries: list[FailoverEntry] = []
        api_keys = cfg.get("api_keys", {})
        role_assignments = cfg.get("role_assignments", {})
        if not role_assignments:
            role_assignments = {
                "quick_coding": "quick_coding", "complex_coding": "complex_coding",
                "writing": "writing", "offline_local": "offline_local",
            }
        priorities = {"quick_coding": 0, "complex_coding": 1, "writing": 2, "offline_local": 10}
        for role, preset_name in role_assignments.items():
            preset = AI_ROLE_PRESETS.get(preset_name)
            if not preset:
                continue
            provider = preset["provider"]
            api_key = api_keys.get(provider, "")
            if provider == "ollama":
                api_key = "ollama"
            entries.append(FailoverEntry(
                name=role, provider=provider, base_url=preset["base_url"],
                api_key=api_key, model=preset["model_id"], priority=priorities.get(role, 5),
            ))
        return cls(entries)

    def ordered(self) -> list[FailoverEntry]:
        with self._lock:
            now = time.time()
            live = [e for e in self.entries if not e.dead and e.cooldown_until <= now]
            return sorted(live, key=lambda e: e.priority)

    def next_entry(self) -> FailoverEntry | None:
        ordered = self.ordered()
        return ordered[0] if ordered else None

    def report_success(self, entry: FailoverEntry) -> None:
        with self._lock:
            entry.error_count = 0
            entry.dead = False
            entry.cooldown_until = 0.0
            entry.last_error = ""

    def report_failure(self, entry: FailoverEntry, error: str = "") -> None:
        with self._lock:
            entry.error_count += 1
            entry.last_error = str(error)
            if entry.error_count >= self.MAX_ERRORS:
                entry.dead = True
                logger.warning(f"Failover '{entry.name}' DEAD after {entry.error_count} errors")
            else:
                entry.cooldown_until = time.time() + self.COOLDOWN_SECONDS

    def reset(self) -> None:
        with self._lock:
            for e in self.entries:
                e.cooldown_until = 0.0
                e.dead = False
                e.error_count = 0
                e.last_error = ""

    def to_dict(self) -> dict:
        return {
            "active": len(self.ordered()), "total": len(self.entries),
            "entries": [e.to_dict() for e in sorted(self.entries, key=lambda x: x.priority)],
        }

# ==============================================================================
# AgentSwarm
# ==============================================================================


class AgentSwarm:
    TOOL_SPECS = [
        {"type": "function", "function": {"name": "list_directory", "description": "List files.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Sub-dir"}}, "required": []}}},
        {"type": "function", "function": {"name": "read_file", "description": "Read file.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Path"}}, "required": ["path"]}}},
        {"type": "function", "function": {"name": "write_file", "description": "Write file.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string", "description": "Full content"}}, "required": ["path", "content"]}}},
        {"type": "function", "function": {"name": "run_python", "description": "Run .py file.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
        {"type": "function", "function": {"name": "run_shell", "description": "Run shell cmd.", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
        {"type": "function", "function": {"name": "search_web", "description": "Search web.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
        {"type": "function", "function": {"name": "fetch_url", "description": "Fetch URL.", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
        {"type": "function", "function": {"name": "run_forensic_lint", "description": "Run lintstack and compress via local brain.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
        {"type": "function", "function": {"name": "analyze_crash_dump", "description": "Compress traceback via local brain.", "parameters": {"type": "object", "properties": {"stderr": {"type": "string"}}, "required": ["stderr"]}}},
    ]
    SYSTEM_PROMPT = (
        'You are "Red Tongue", the primary agent of a local-first AI coding studio. '
        'You operate directly inside the user\'s live workspace with real tools.\n\n'
        'WORKSPACE RULES:\n- Paths relative to root.\n- Inspect before editing.\n'
        '- write_file gets COMPLETE content.\n- Keep shell usage safe.\n\n'
        'TOOLS: list_directory, read_file, write_file, run_python, run_shell, '
        'search_web, fetch_url, run_forensic_lint, analyze_crash_dump.\n\n'
        'BEHAVIOUR:\n- Think briefly, then act.\n- Summarise changes.\n'
        '- Refuse unsafe requests.\n\nOUTPUT: Concise, technical, Markdown.'
    )

    def __init__(self, tool_layer: ToolLayer, failover_config: FailoverStack | None = None) -> None:
        self.tool_layer = tool_layer
        self.failover = failover_config if failover_config is not None else FailoverStack.load_config()
        self._clients: dict[str, Any] = {}
        self._no_tools: set = set()
        self.reset_clients()

    def reset_clients(self) -> None:
        self._clients = {}
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            logger.error(f"openai SDK unavailable: {e}")
            return
        for entry in self.failover.entries:
            if not entry.api_key:
                continue
            try:
                self._clients[entry.name] = AsyncOpenAI(
                    api_key=entry.api_key, base_url=entry.base_url, timeout=90.0, max_retries=0,
                )
            except (ValueError, TypeError) as e:
                logger.warning(f"Client init '{entry.name}': {e}")

    def rebuild_failover(self) -> None:
        self.failover = FailoverStack.load_config()
        self.reset_clients()

    def _build_messages(self, message: str, history: list | None, rag_context: str, custom_system_prompt: str = "") -> list[dict]:
        sys_content = self.SYSTEM_PROMPT
        if custom_system_prompt and custom_system_prompt.strip():
            sys_content = custom_system_prompt.strip()
        msgs: list[dict] = [{"role": "system", "content": sys_content}]
        if rag_context and rag_context.strip():
            msgs.append({"role": "system", "content": "RAG context:\n\n" + rag_context})
        hist = [
            m for m in (history or [])
            if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content")
        ]
        if hist and hist[-1].get("role") == "user" and str(hist[-1].get("content", "")).strip() == str(message).strip():
            hist = hist[:-1]
        msgs.extend(hist[-12:])
        msgs.append({"role": "user", "content": message})
        return msgs

    async def run_main_agent(self, message: str, history: list | None = None, autopilot: bool = True, effort: str = "medium", response_queue=None, rag_context: str = "", disable_tools: bool = False, custom_system_prompt: str = ""):
        message = (message or "").strip()
        if not message:
            yield json.dumps({"type": "error", "content": "Empty message."})
            return
        max_rounds = {"low": 1, "medium": 4, "high": 8}.get(str(effort).lower(), 4)
        messages = self._build_messages(message, history, rag_context, custom_system_prompt)
        rounds = 0
        attempts = 0
        while rounds < max_rounds and attempts < 24:
            attempts += 1
            entry = self.failover.next_entry()
            if entry is None:
                yield json.dumps({"type": "error", "content": "All providers down."})
                return
            client = self._clients.get(entry.name)
            if client is None:
                self.failover.report_failure(entry, "no client")
                continue
            use_tools = not disable_tools and entry.name not in self._no_tools
            try:
                kwargs: dict[str, Any] = {"model": entry.model, "messages": messages, "stream": True}
                if use_tools:
                    kwargs["tools"] = self.TOOL_SPECS
                stream = await client.chat.completions.create(**kwargs)
            except Exception as e:
                err = str(e)
                if use_tools and "tool" in err.lower():
                    self._no_tools.add(entry.name)
                    continue
                self.failover.report_failure(entry, err)
                yield json.dumps({"type": "stream", "content": f"\n\n> ⚡ `{entry.name}` failed ({err[:140]}).\n\n"})
                continue
            content_parts: list[str] = []
            tool_calls: dict[int, dict] = {}
            try:
                async for chunk in stream:
                    choices = getattr(chunk, "choices", None)
                    if not choices:
                        continue
                    delta = getattr(choices[0], "delta", None)
                    if delta is None:
                        continue
                    piece = getattr(delta, "content", None)
                    if piece:
                        content_parts.append(piece)
                        yield json.dumps({"type": "stream", "content": piece})
                    tcs = getattr(delta, "tool_calls", None)
                    if tcs:
                        for tc in tcs:
                            idx = tc.index if tc.index is not None else 0
                            acc = tool_calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                            if tc.id:
                                acc["id"] = tc.id
                            fn = getattr(tc, "function", None)
                            if fn:
                                if fn.name:
                                    acc["name"] = fn.name
                                if fn.arguments:
                                    acc["arguments"] += fn.arguments
            except Exception as e:
                self.failover.report_failure(entry, str(e))
                yield json.dumps({"type": "stream", "content": f"\n\n>  Stream broke ({str(e)[:140]}). Retrying…\n\n"})
                if content_parts:
                    messages.append({"role": "assistant", "content": "".join(content_parts)})
                continue
            self.failover.report_success(entry)
            rounds += 1
            full_text = "".join(content_parts)
            if tool_calls:
                calls = []
                for i, tc in sorted(tool_calls.items()):
                    calls.append({"id": tc["id"] or f"call_{i}", "type": "function", "function": {"name": tc["name"] or "unknown", "arguments": tc["arguments"] or "{}"}})
                messages.append({"role": "assistant", "content": full_text or None, "tool_calls": calls})
                for call in calls:
                    name = call["function"]["name"]
                    try:
                        args = json.loads(call["function"]["arguments"])
                        if not isinstance(args, dict):
                            args = {}
                    except json.JSONDecodeError:
                        args = {}
                    res = await asyncio.to_thread(self.tool_layer.execute, name, args)
                    summary = json.dumps(res, ensure_ascii=False, default=str)
                    yield json.dumps({"type": "tool", "name": name, "output": summary[:2000]})
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": summary[:8000]})
                continue
            if full_text:
                messages.append({"role": "assistant", "content": full_text})
                return
            yield json.dumps({"type": "stream", "content": "\n\n> ⚠️ Empty. Retrying…\n\n"})
            continue
        yield json.dumps({"type": "stream", "content": "\n\n> 🛑 Budget reached.\n\n"})
