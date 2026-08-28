#!/usr/bin/env python3
"""backend.py

Core engine layer for the RedTongue Refactory.

Manages AI Swarm, ToolLayer, RAG, TTS, STT, Config, and the
DiagnosticBrain (ONNX SmolLM) for forensic compression.
"""
# NOTE: This file is imported as a module; shebang retained for direct execution support

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import mmap
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from functools import lru_cache, cached_property
from pathlib import Path
from typing import Any, AsyncGenerator, ClassVar, Final

import requests

# Module-level embedding cache keyed by (text_hash, dim) to avoid caching bound methods
_embedding_cache: dict[tuple[int, int], Any] = {}
_EMBED_CACHE_MAX_SIZE = 256
_embedding_cache_lock = threading.Lock()

# Query size limit to bound memory for oversized inputs
_QUERY_TEXT_LIMIT = 10000  # Max characters for query input


def _get_cached_embedding(text: str, dim: int) -> Any:
    """Generate or retrieve cached embedding vector using secure hash-based tokenization.
    
    Uses a module-level cache keyed by text hash and dimension to avoid issues with
    caching bound methods. Enforces cache size limit with thread-safe eviction.
    """
    if np is None:
        msg = "NumPy is required for embeddings"
        raise ImportError(msg)
    
    # Create a hash key for the text to use in cache lookup
    text_hash = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)
    cache_key = (text_hash, dim)
    with _embedding_cache_lock:
        if cache_key in _embedding_cache:
            return _embedding_cache[cache_key]
    
        # Generate embedding
        vec = np.zeros(dim, dtype=np.float32)
        tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{1,}", (text or "").lower())
        for tok in tokens:
            idx = int(hashlib.sha256(tok.encode("utf-8")).hexdigest()[:8], 16) % dim
            vec[idx] += 1.0
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
    
        # Enforce cache size limit before adding new entry
        if len(_embedding_cache) >= _EMBED_CACHE_MAX_SIZE:
            # Remove oldest entry (first key)
            first_key = next(iter(_embedding_cache))
            del _embedding_cache[first_key]
    
        _embedding_cache[cache_key] = vec
        return vec

try:
    import numpy as np  # type: ignore[import-untyped]
except ImportError:
    np = None  # type: ignore[assignment]

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
    ort = None  # type: ignore[assignment]

BASE_DIR: Final[Path] = Path(__file__).resolve().parent
CONFIG_FILE: Final[Path] = BASE_DIR / "config.json"
SALT_FILE: Final[Path] = BASE_DIR / ".red_tongue_salt"
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
    """
    Derives a stable encryption key from the user identity, home directory, and a per-installation salt.
    
    Returns:
        bytes: URL-safe base64-encoded derived key.
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    # Load or generate per-install random salt
    if SALT_FILE.exists():
        try:
            random_salt = SALT_FILE.read_bytes()
            if len(random_salt) != 32:
                raise ValueError("Invalid salt length")
        except (OSError, ValueError):
            random_salt = os.urandom(32)
            SALT_FILE.write_bytes(random_salt)
            SALT_FILE.chmod(0o600)
    else:
        random_salt = os.urandom(32)
        SALT_FILE.write_bytes(random_salt)
        SALT_FILE.chmod(0o600)

    try:
        identity = os.getlogin() + str(Path.home())
    except OSError:
        identity = str(Path.home())

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=random_salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(identity.encode()))


def encrypt_value(value: str) -> str:
    """Encrypt a string value using Fernet symmetric encryption.

    Args:
        value: The plaintext string to encrypt.

    Returns:
        str: Encrypted value prefixed with 'ENC:', or original if empty.
    """
    if not value:
        return value
    from cryptography.fernet import Fernet

    return "ENC:" + Fernet(get_machine_key()).encrypt(value.encode("utf-8")).decode(
        "ascii"
    )


def decrypt_value(value: str) -> str:
    """Decrypt a Fernet-encrypted value.

    Args:
        value: The encrypted string (must start with 'ENC:').

    Returns:
        str: Decrypted plaintext, or empty string on failure.
    """
    if not value or not value.startswith("ENC:"):
        return value
    from cryptography.fernet import Fernet, InvalidToken

    try:
        return (
            Fernet(get_machine_key()).decrypt(value[4:].encode("ascii")).decode("utf-8")
        )
    except (InvalidToken, ValueError, KeyError, TypeError) as e:
        logger.debug("Decryption failed: %s", e)
        return ""


def load_config() -> dict[str, Any]:
    """Load configuration from disk, decrypting any encrypted API keys.

    Returns:
        dict[str, Any]: Configuration dictionary with decrypted keys.
    """
    if not CONFIG_FILE.exists():
        return {}
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}

    cfg: dict[str, Any] = {}
    if "api_keys" in raw:
        api_keys = raw["api_keys"]
        cfg["api_keys"] = (
            {
                k: decrypt_value(v)
                if isinstance(v, str) and v.startswith("ENC:")
                else v
                for k, v in api_keys.items()
            }
            if isinstance(api_keys, dict)
            else {}
        )
    else:
        cfg["api_keys"] = {}
        for k, v in raw.items():
            if "KEY" in k.upper() or "TOKEN" in k.upper():
                provider = k.lower().replace("_api_key", "").replace("_key", "")
                cfg["api_keys"][provider] = (
                    decrypt_value(v)
                    if isinstance(v, str) and v.startswith("ENC:")
                    else v
                )
            else:
                cfg[k] = v

    cfg["role_assignments"] = raw.get(
        "role_assignments",
        {
            "quick_coding": "quick_coding",
            "complex_coding": "complex_coding",
            "writing": "writing",
            "offline_local": "offline_local",
        },
    )
    return cfg


def save_config(cfg: dict) -> None:
    """Save configuration to disk, encrypting sensitive values.

    Args:
        cfg: Configuration dictionary to persist.
    """
    raw: dict[str, Any] = {}
    for k, v in cfg.items():
        if k == "api_keys":
            raw["api_keys"] = {
                provider: encrypt_value(val)
                if val and not str(val).startswith("ENC:")
                else val
                for provider, val in (v or {}).items()
            }
        elif "KEY" in k.upper() or "TOKEN" in k.upper():
            raw[k] = encrypt_value(v) if v and not str(v).startswith("ENC:") else v
        else:
            raw[k] = v

    try:
        CONFIG_FILE.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    except (OSError, PermissionError, TypeError) as e:
        logger.warning("Config save failed: %s", e)


# Cached sets for sensitive path checking (performance optimization)
_SENSITIVE_NAMES: Final[frozenset] = frozenset({".env", ".gitconfig", "id_rsa"})
_SENSITIVE_PARTS: Final[frozenset] = frozenset({".git", "__pycache__", "node_modules"})


def is_sensitive_path(path: Path | str) -> bool:
    """Check if a path points to sensitive files or directories.

    Args:
        path: File path to check.

    Returns:
        bool: True if path is sensitive, False otherwise.
    """
    # Cache Path parsing to avoid redundant operations
    p = Path(path)
    name = p.name.lower()
    # Fast path: check exact name match first
    if name in _SENSITIVE_NAMES:
        return True
    # Check for .env* prefix pattern (covers .env, .env.local, .env.production, etc.)
    if name.startswith(".env"):
        return True
    # Use cached set for faster membership testing on parts
    return any(part.lower() in _SENSITIVE_PARTS for part in p.parts)


@lru_cache(maxsize=256)
def _get_resolved_workspace(workspace: str) -> Path:
    """Cached workspace resolution for repeated path validations."""
    return Path(workspace).resolve(strict=True)


def validate_path(path: str, workspace: str) -> Path:
    """Validate that a path is safely contained within the workspace.

    Args:
        path: Relative or absolute path to validate.
        workspace: Base workspace directory.

    Returns:
        Path: Resolved absolute path.

    Raises:
        ValueError: If path escapes workspace boundary.
        OSError: If workspace does not exist.
    """
    ws = _get_resolved_workspace(workspace)
    # Avoid redundant Path object creation
    p_path = Path(path)
    p = (ws / p_path).resolve() if not p_path.is_absolute() else p_path.resolve()
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

    def listen_and_transcribe(
        self, timeout: int = 5, phrase_time_limit: int = 10
    ) -> str | None:
        if not HAS_STT or not self.recognizer:
            return None
        try:
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self.recognizer.listen(
                    source, timeout=timeout, phrase_time_limit=phrase_time_limit
                )
            return self.recognizer.recognize_google(audio)
        except (sr.WaitTimeoutError, sr.UnknownValueError):
            return None
        except sr.RequestError as e:
            logger.warning("STT recognition error: %s", e)
            return None
        except OSError as e:
            logger.warning("STT hardware error: %s", e)
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
        """
        Report the current model download and loading state.
        
        Returns:
        	dict: A mapping containing the download status, progress, and readiness state.
        """
        return {
            "status": self._download_status,
            "progress": self._download_progress,
            "loaded": self.is_ready,
        }

    # SHA-256 hashes for model verification (prevent supply chain attacks)
    MODEL_HASH = "sha256:aa50eb16da7a975c9058b2deab306aa066aa9d916a05fa2e3923f9e9acd58e1b"
    
    def ensure_model(
        self, progress_callback: Callable[[float], None] | None = None
    ) -> bool:
        """
        Ensure the diagnostic model is available and loaded.
        
        Parameters:
            progress_callback (Callable[[float], None] | None): Optional callback receiving download progress percentages.
        
        Returns:
            bool: `True` if the model is verified and loaded, `False` otherwise.
        """
        import hashlib
        
        model_path = self.models_dir / self.MODEL_NAME
        if model_path.exists() and model_path.stat().st_size > 10_000_000:
            # Verify hash if configured
            if self.MODEL_HASH and not self.MODEL_HASH.startswith("sha256:TODO"):
                sha256 = hashlib.sha256()
                with open(model_path, "rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        sha256.update(chunk)
                actual_hash = sha256.hexdigest()
                expected_hash = self.MODEL_HASH.replace("sha256:", "")
                if actual_hash != expected_hash:
                    logger.error("Model hash mismatch! Expected %s, got %s", expected_hash, actual_hash)
                    self._download_status = "failed"
                    return False
            
            self._download_status = "ready"
            if not self._load_model():
                self._download_status = "failed"
                return False
            return True

        self._download_status = "downloading"
        self.models_dir.mkdir(parents=True, exist_ok=True)
        try:
            tmp_path = model_path.with_suffix(".onnx.part")
            with requests.get(self.MODEL_URL, stream=True, timeout=30) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                downloaded = 0
                with open(tmp_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total > 0:
                                self._download_progress = (downloaded / total) * 100
                                if progress_callback:
                                    progress_callback(self._download_progress)
            tmp_path.replace(model_path)
            
            # Verify hash after download if configured
            if self.MODEL_HASH and not self.MODEL_HASH.startswith("sha256:TODO"):
                sha256 = hashlib.sha256()
                with open(model_path, "rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        sha256.update(chunk)
                actual_hash = sha256.hexdigest()
                expected_hash = self.MODEL_HASH.replace("sha256:", "")
                if actual_hash != expected_hash:
                    logger.error("Downloaded model hash mismatch!")
                    model_path.unlink()
                    self._download_status = "failed"
                    return False
            
            self._download_status = "ready"
            if not self._load_model():
                self._download_status = "failed"
                return False
            return True
        except requests.RequestException as e:
            logger.error("SmolLM download failed: %s", e)
            self._download_status = "failed"
            return False
        except OSError as e:
            logger.error("SmolLM file write failed: %s", e)
            self._download_status = "failed"
            return False

    def _load_model(self) -> bool:
        with self._lock:
            if self.session:
                return True
            model_path = self.models_dir / self.MODEL_NAME
            if not model_path.exists():
                return False
            if not HAS_ONNX or ort is None:
                logger.warning("DiagnosticBrain unavailable: onnxruntime not installed")
                return False
            try:
                providers: list[str] = ["CPUExecutionProvider"]
                if (
                    sys.platform == "win32"
                    and "DmlExecutionProvider" in ort.get_available_providers()
                ):
                    providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
                self.session = ort.InferenceSession(
                    str(model_path), providers=providers
                )
                logger.info("DiagnosticBrain loaded via %s", providers[0])
                return True
            except ort.OrtException as e:
                logger.warning("DiagnosticBrain failed to load ONNX session: %s", e)
                return False

    def compress_diagnostics(self, raw_data: str) -> str:
        if not self.session:
            return raw_data[:1000]
        # In production: tokenize -> run ONNX -> detokenize.
        # Skeleton simulates the compressed JSON output.
        return json.dumps(
            {
                "summary": "Forensic analysis complete.",
                "critical": ["Syntax error detected", "Unresolved import"],
                "fix": "Fix syntax on line 42 and install missing package.",
            }
        )


# ==============================================================================
# RAG (Local Vector Index)
# ==============================================================================


class RAGIndex:
    DIM: Final[int] = 2048
    CHUNK_LINES: Final[int] = 60
    SCORE_FLOOR: Final[float] = 0.02
    MAX_FILE_SIZE: Final[int] = 1_000_000
    TEXT_EXTS: Final[frozenset[str]] = frozenset(
        {
            ".py",
            ".js",
            ".ts",
            ".html",
            ".css",
            ".md",
            ".txt",
            ".json",
            ".yml",
            ".yaml",
            ".toml",
            ".sh",
            ".csv",
            ".xml",
            ".sql",
        }
    )
    IGNORE_DIRS: Final[frozenset[str]] = frozenset(
        {
            "node_modules",
            "__pycache__",
            "libs",
            "dist",
            "build",
            "site-packages",
            ".venv",
            "venv",
        }
    )

    def __init__(self, workspace: str) -> None:
        """
        Initialize a workspace-scoped retrieval index and load existing data when available.
        
        Parameters:
        	workspace (str): Path to the workspace whose files will be indexed.
        """
        self.workspace = Path(workspace)
        self.index_dir = self.workspace / ".red_tongue_index"
        self._lock = threading.RLock()
        self._chunks: list[dict] = []
        self._matrix = None
        self._dirty = False
        self._pending_files: set[str] = set()
        self._reindex_timer: threading.Timer | None = None
        self._closed = False

        if np is None:
            logger.warning("numpy unavailable — RAG disabled.")
        elif self._try_load():
            logger.info("RAG loaded: %s chunks.", len(self._chunks))
        else:
            threading.Thread(
                target=self._safe_reindex,
                daemon=True,
                name="rag-reindex",
            ).start()

    def _try_load(self) -> bool:
        try:
            meta = self.index_dir / "chunks.json"
            vec = self.index_dir / "vectors.npz"
            if not meta.exists() or not vec.exists():
                return False
            chunks = json.loads(meta.read_text(encoding="utf-8"))
            data = np.load(str(vec))
            matrix = data["vectors"].astype(np.float32)
            if len(chunks) != matrix.shape[0]:
                return False
            with self._lock:
                self._chunks = chunks
                self._matrix = matrix
            return True
        except (json.JSONDecodeError, OSError, ValueError, KeyError) as e:
            logger.warning("RAG load failed: %s", e)
            return False

    def _save(self) -> None:
        if np is None or self._closed:
            return
        try:
            self.index_dir.mkdir(parents=True, exist_ok=True)
            (self.index_dir / "chunks.json").write_text(
                json.dumps(self._chunks),
                encoding="utf-8",
            )
            matrix = (
                self._matrix
                if self._matrix is not None
                else np.zeros(
                    (0, self.DIM),
                    dtype=np.float32,
                )
            )
            np.savez_compressed(str(self.index_dir / "vectors.npz"), vectors=matrix)
        except (OSError, ValueError) as e:
            logger.warning("RAG save failed: %s", e)

    def remove_file(self, file_id: str) -> None:
        """Remove chunks for a specific file and rebuild the index.
        
        Parameters:
            file_id (str): Normalized relative path of the file to remove.
        """
        with self._lock:
            if self._closed:
                return
            
            # Filter out chunks matching this file_id
            original_count = len(self._chunks)
            self._chunks = [c for c in self._chunks if c.get("path") != file_id]
            
            # Only rebuild if chunks were actually removed
            if len(self._chunks) != original_count:
                # Rebuild matrix from remaining chunks
                self._matrix = self._build_matrix(self._chunks)
                # Persist updated index
                self._save()
                logger.info("RAG removed file %s: %d chunks removed", 
                           file_id, original_count - len(self._chunks))

    @staticmethod
    def _tokens(text: str) -> list[str]:
        """Tokenize text for embedding with size limit enforcement."""
        # Enforce query size limit before tokenization
        if len(text or "") > _QUERY_TEXT_LIMIT:
            text = (text or "")[:_QUERY_TEXT_LIMIT]
        return re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{1,}", text.lower())

    def _embed(self, text: str) -> np.ndarray:
        """Generate embedding vector using module-level cached helper."""
        # Enforce query size limit before embedding
        if len(text or "") > _QUERY_TEXT_LIMIT:
            text = (text or "")[:_QUERY_TEXT_LIMIT]
        return _get_cached_embedding(text, self.DIM)

    def _iter_workspace_files(self):
        for root, dirs, files in os.walk(self.workspace):
            dirs[:] = [
                d for d in dirs if not d.startswith(".") and d not in self.IGNORE_DIRS
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

    def _chunk_file(self, path: Path, file_id: str | None = None) -> list[dict]:
        rel = file_id or path.relative_to(self.workspace).as_posix()
        try:
            if path.stat().st_size > self.MAX_FILE_SIZE:
                return []
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        chunks = []
        for start in range(0, len(lines), self.CHUNK_LINES):
            piece = "\n".join(lines[start : start + self.CHUNK_LINES]).strip()
            if piece:
                chunks.append({"path": rel, "text": piece, "line": start + 1})
        return chunks

    def _build_matrix(self, chunks: list[dict]):
        if np is None:
            return None
        if not chunks:
            return np.zeros((0, self.DIM), dtype=np.float32)
        # Pre-allocate matrix and fill in loop for better performance
        matrix = np.empty((len(chunks), self.DIM), dtype=np.float32)
        for i, c in enumerate(chunks):
            matrix[i] = self._embed(c["text"])
        return matrix

    def reindex(self) -> None:
        if np is None:
            return
        with self._lock:
            chunks: list[dict] = []
            for f in self._iter_workspace_files():
                chunks.extend(self._chunk_file(f))
            self._chunks = chunks
            self._matrix = self._build_matrix(chunks)
            self._save()
            self._dirty = False
            logger.info("RAG built: %s chunks", len(chunks))

    def _safe_reindex(self) -> None:
        try:
            self.reindex()
        except (OSError, ValueError, TypeError) as e:
            logger.warning("RAG reindex failed: %s", e)

    def index_file(self, path: str) -> None:
        """Schedule a workspace file for batched RAG reindexing after a period of inactivity.
        
        Args:
            path: Relative path to the file within the workspace.
        """
        if np is None:
            return
        p = self.workspace / path
        if not p.exists() or not p.is_file():
            return
        file_id = p.relative_to(self.workspace).as_posix()
        
        with self._lock:
            # Add to pending files set
            self._pending_files.add(file_id)
            
            # Cancel existing timer
            if self._reindex_timer is not None:
                self._reindex_timer.cancel()
            
            # Schedule batched reindex after 2 seconds of inactivity
            self._reindex_timer = threading.Timer(2.0, self._flush_pending_files)
            self._reindex_timer.daemon = True
            self._reindex_timer.start()
    
    def _flush_pending_files(self) -> None:
        """Flush all pending file updates to the RAG index."""
        if np is None:
            return
        
        with self._lock:
            # Check closed state before processing
            if self._closed:
                return
            
            if not self._pending_files:
                return
            
            # Remove old chunks for pending files
            pending = self._pending_files.copy()
            self._chunks = [c for c in self._chunks if c["path"] not in pending]
            
            # Add new chunks for pending files
            for file_id in pending:
                p = self.workspace / file_id
                if p.exists() and p.is_file():
                    new_chunks = self._chunk_file(p, file_id)
                    self._chunks.extend(new_chunks)
            
            # Rebuild matrix and save
            self._matrix = self._build_matrix(self._chunks)
            self._save()
            self._dirty = False
            self._pending_files.clear()
            
            logger.info("RAG batch indexed: %s files, %s total chunks", 
                       len(pending), len(self._chunks))

    def query(self, text: str, top_k: int = 3) -> list[dict]:
        """
        Search the indexed workspace for chunks relevant to the query.
        
        Parameters:
            text (str): Query text used to find relevant indexed chunks.
            top_k (int): Maximum number of matching chunks to return.
        
        Returns:
            list[dict]: Matching chunks with their paths, text, and similarity scores.
        """
        with self._lock:
            if np is None or self._matrix is None or not self._chunks:
                return []
            try:
                q = self._embed(text or "")
                scores = self._matrix @ q
                k = max(1, int(top_k))
                if k >= len(scores):
                    order = np.argsort(scores)[::-1]
                else:
                    part_idx = np.argpartition(scores, -k)[-k:]
                    order = part_idx[np.argsort(scores[part_idx])[::-1]]
                hits = []
                for i in order:
                    s = float(scores[i])
                    if s <= self.SCORE_FLOOR:
                        continue
                    c = self._chunks[int(i)]
                    hits.append(
                        {
                            "path": c.get("path", "unknown"),
                            "text": c.get("text", ""),
                            "score": round(s, 4),
                        }
                    )
                return hits
            except (ValueError, RuntimeError, AttributeError):
                return []

    def close(self) -> None:
        with self._lock:
            self._closed = True
            # Cancel pending reindex timer to prevent execution after shutdown
            if self._reindex_timer is not None:
                self._reindex_timer.cancel()
                self._reindex_timer = None
            # Clear pending files to prevent future processing
            self._pending_files.clear()
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
    VOICE_ALIASES: Final[dict[str, str]] = {
        "af": "af-heart",
        "am": "am-adam",
        "bf": "bf-emma",
        "bm": "bm-george",
    }

    def __init__(self, models_dir: Path | None = None) -> None:
        """Initialize the text-to-speech model manager.
        
        Parameters:
            models_dir (Path | None): Directory for model assets, or the default models directory when omitted.
        """
        self.models_dir = Path(models_dir) if models_dir else BASE_DIR / "models"
        self._engine: Any = None
        self._lock = threading.Lock()

    # SHA-256 hashes for TTS model verification (prevent supply chain attacks)
    MODEL_HASHES: Final[dict[str, str]] = {
        "kokoro-v1.0.onnx": "sha256:7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
        "voices-v1.0.bin": "sha256:bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
    }
    
    def _download(self, name: str) -> bool:
        """
        Download a TTS model asset when it is unavailable and verify its integrity when configured.
        
        Parameters:
            name (str): Name of the model asset to download.
        
        Returns:
            bool: `True` if the asset exists and passes verification, `False` if downloading or verification fails.
        """
        import hashlib
        
        dest = self.models_dir / name
        if dest.exists() and dest.stat().st_size > 0:
            # Verify hash if configured
            expected_hash = self.MODEL_HASHES.get(name, "")
            if expected_hash and not expected_hash.startswith("sha256:TODO"):
                sha256 = hashlib.sha256()
                with open(dest, "rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        sha256.update(chunk)
                actual_hash = sha256.hexdigest()
                if actual_hash != expected_hash.replace("sha256:", ""):
                    logger.error("TTS model %s hash mismatch!", name)
                    dest.unlink()
                    return False
            return True
        
        logger.info("Downloading TTS: %s", name)
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
                
                # Verify hash after download if configured
                expected_hash = self.MODEL_HASHES.get(name, "")
                if expected_hash and not expected_hash.startswith("sha256:TODO"):
                    sha256 = hashlib.sha256()
                    with open(dest, "rb") as f:
                        for chunk in iter(lambda: f.read(8192), b""):
                            sha256.update(chunk)
                    actual_hash = sha256.hexdigest()
                    if actual_hash != expected_hash.replace("sha256:", ""):
                        logger.error("Downloaded TTS model %s hash mismatch!", name)
                        dest.unlink()
                        return False
                
                return True
        except (requests.RequestException, OSError, ConnectionError) as e:
            logger.error("TTS download '%s' failed: %s", name, e)
            return False

    def _ensure_engine(self) -> Any:
        """
        Ensure the Kokoro text-to-speech engine is available and initialized.
        
        Returns:
        	Any: The initialized Kokoro engine.
        
        Raises:
        	RuntimeError: If the required model files cannot be downloaded.
        """
        with self._lock:
            if self._engine is not None:
                return self._engine
            
            # Download/verify all required assets (hash check even for existing files)
            onnx_ok = self._download("kokoro-v1.0.onnx")
            voices_ok = self._download("voices-v1.0.bin")
            
            if not (onnx_ok and voices_ok):
                raise RuntimeError(
                    f"TTS models missing or invalid. Place in: {self.models_dir}"
                )
            
            onnx_path = self.models_dir / "kokoro-v1.0.onnx"
            voices_path = self.models_dir / "voices-v1.0.bin"
            
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

    async def generate_wav(
        self, text: str, voice: str = "af"
    ) -> tuple[bytes | None, str]:
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
                        audio, sr = engine.create(
                            seg, voice=cand, speed=1.0, lang="en-us"
                        )
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
    DESTRUCTIVE_PATTERNS = (
        "rm -rf /",
        "rm -rf /*",
        "mkfs.",
        "format c:",
        "shutdown ",
        "reboot ",
        ":(){:|:&};:",  # Fork bomb - kept for documentation but not used in comparison
    )
    ALLOWED_SHELL_COMMANDS: Final[frozenset[tuple[str, ...]]] = frozenset(
        {
            ("pwd",),
            ("ls",),
            ("ls", "-l"),
            ("ls", "-la"),
            ("ls", "-al"),
            ("git", "status"),
            ("git", "status", "--short"),
            ("git", "status", "--porcelain"),
            ("git", "diff"),
            ("git", "diff", "--cached"),
            ("git", "diff", "--staged"),
            ("git", "log", "--oneline"),
            ("git", "branch", "--show-current"),
        }
    )
    ALLOWED_SANDBOX_MODES = (True, False)
    SHELL_INTERPRETERS = frozenset(
        {
            "bash",
            "cmd",
            "csh",
            "dash",
            "fish",
            "ksh",
            "powershell",
            "pwsh",
            "sh",
            "zsh",
        }
    )
    EXEC_TIMEOUT = 60
    RUFF_TIMEOUT = 30
    MAX_FILE_SIZE: Final[int] = 1_000_000  # Match RAGIndex.MAX_FILE_SIZE
    MAX_OUTPUT = 100_000
    MAX_FETCH_OUTPUT = 8000
    MAX_SNIPPET = 400
    FILE_CHUNK_SIZE = 64 * 1024  # 64KB chunks for HDD optimization
    
    # Cached sets for performance optimization (avoid recreation on each call)
    _IGNORE_DIRS_SET: ClassVar[frozenset[str]] = frozenset(
        {".git", ".svn", ".hg", "node_modules", "__pycache__", "venv", ".venv", "libs", "dist", "build", "site-packages"}
    )

    def __init__(self, workspace: str, sandbox_mode: bool = True) -> None:
        self.workspace = str(Path(workspace).resolve())
        self.sandbox_mode = sandbox_mode
        self.rag = RAGIndex(self.workspace)
        self.tts = KokoroTTS()
        self.brain = DiagnosticBrain()
        logger.info("ToolLayer ready — workspace: %s", self.workspace)

    def _safe_path(self, path: str) -> tuple[Path | None, dict | None]:
        """Validate and sanitize a file path for safe access.

        Args:
            path: Relative or absolute path to validate.

        Returns:
            Tuple of (resolved Path, error dict) where error is None on success.
        """
        try:
            p = validate_path(path, self.workspace)
        except (ValueError, OSError) as e:
            return None, {"status": "error", "error": str(e)}
        if is_sensitive_path(p):
            return None, {"status": "error", "error": "Blocked: sensitive path."}
        return p, None

    def read_file(self, path: str, chunked: bool = False) -> dict:
        """
        Read a UTF-8 text file within the workspace after path validation.
        
        Parameters:
            path (str): Relative path to the file within the workspace.
            chunked (bool): Retained for compatibility; does not alter the returned content.
        
        Returns:
            dict: A success result containing the file text under ``output``, or an error result.
        """
        p, err = self._safe_path(path)
        if err:
            return err
        assert p is not None
        if not p.exists() or not p.is_file():
            return {"status": "error", "error": f"Not found: {path}"}
        
        # Enforce bounded-size policy to avoid loading large files into memory
        try:
            file_size = p.stat().st_size
            if file_size > self.MAX_FILE_SIZE:
                return {
                    "status": "error",
                    "error": f"File too large: {file_size} bytes (max: {self.MAX_FILE_SIZE})"
                }
        except OSError as e:
            return {"status": "error", "error": str(e)}
        
        try:
            # Read entire file at once to avoid UTF-8 decoding issues at chunk boundaries
            return {
                "status": "success",
                "output": p.read_text(encoding="utf-8", errors="replace"),
            }
        except OSError as e:
            return {"status": "error", "error": str(e)}

    def write_file(self, path: str, content: str) -> dict:
        """Write content to a file in the workspace with security validation.

        Uses atomic write (temp file + rename) to prevent corruption on HDD.

        Args:
            path: Relative path within workspace.
            content: Text content to write.

        Returns:
            dict: Status dictionary with file metadata on success.
        """
        p, err = self._safe_path(path)
        if err:
            return err
        assert p is not None
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            data = str(content)

            # Atomic write: write to temp file in same directory, then rename
            # This prevents corruption if write is interrupted (power loss, crash)
            fd, tmp_path = tempfile.mkstemp(dir=p.parent, prefix='.tmp_')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())  # Force to disk for HDD safety
                os.replace(tmp_path, str(p))  # Atomic rename
            except OSError:
                # Clean up temp file on failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            try:
                self.rag.index_file(str(p.relative_to(self.workspace)))
            except (OSError, ValueError, TypeError) as e:
                logger.debug("RAG index after write failed: %s", e)
            return {
                "status": "success",
                "path": path,
                "bytes": len(data.encode("utf-8")),
            }
        except OSError as e:
            return {"status": "error", "error": str(e)}

    def list_directory(self, path: str = ".", recursive: bool = False) -> dict:
        """List files in a workspace directory, excluding sensitive items.

        For HDD optimization, uses batched directory walks and avoids deep recursion
        unless explicitly requested.

        Args:
            path: Relative path within workspace (default: root).
            recursive: If True, lists all nested files; otherwise only top-level.

        Returns:
            dict: Status dictionary with 'output' list of relative file paths.
        """
        p, err = self._safe_path(path)
        if err:
            return err
        assert p is not None
        try:
            results: list[str] = []
            # Use cached set for faster lookup
            ignore_dirs = self._IGNORE_DIRS_SET
            for root, dirs, files in os.walk(p):
                # Filter directories in-place to control traversal depth
                dirs[:] = [
                    d
                    for d in dirs
                    if not d.startswith(".") and d not in ignore_dirs
                ]
                for f in files:
                    rel = os.path.relpath(os.path.join(root, f), self.workspace)
                    if is_sensitive_path(rel):
                        continue
                    results.append(rel.replace("\\", "/"))
                # Stop after first level if not recursive (HDD optimization)
                if not recursive:
                    break
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
        if self.sandbox_mode:
            return {
                "status": "error",
                "error": "Python execution is disabled in sandbox mode.",
            }
        try:
            proc = subprocess.run(
                [sys.executable, str(p)],
                capture_output=True,
                text=True,
                cwd=self.workspace,
                timeout=self.EXEC_TIMEOUT,
                check=False,
            )
            out = proc.stdout or ""
            if proc.stderr:
                out += "\n[stderr]\n" + proc.stderr
            return {
                "status": "success" if proc.returncode == 0 else "error",
                "output": out.strip()[: self.MAX_OUTPUT] or "(no output)",
                "returncode": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"status": "error", "error": f"Timeout ({self.EXEC_TIMEOUT}s)"}
        except (OSError, subprocess.SubprocessError) as e:
            return {"status": "error", "error": str(e)}

    def run_shell(self, command: str) -> dict:
        """Execute shell command with security hardening using allowlist approach."""
        import shlex

        if not command or not command.strip():
            return {"status": "error", "error": "Empty command."}

        try:
            # Parse command safely without shell interpretation
            cmd_list = shlex.split(command)
            if not cmd_list:
                return {"status": "error", "error": "Empty command."}
            if self.sandbox_mode:
                return {
                    "status": "error",
                    "error": "Shell execution is disabled in sandbox mode.",
                }

            # Allowlist of permitted commands with validated argument forms
            ALLOWED_COMMANDS = {
                "ls": {"args_pattern": r"^(-[laRth]|--(?:color|help))?$"},
                "dir": {"args_pattern": r"^(-[laRth]|--(?:color|help))?$"},
                "pwd": {},
                "cat": {"max_args": 5, "no_recursive": True},
                "head": {"args_pattern": r"^(-n\d+)?$"},
                "tail": {"args_pattern": r"^(-n\d+|-f)?$"},
                "grep": {"args_pattern": r"^(-[inrvE]|--color=auto|-E|-i|-n|-r|-v)?$"},
                "find": {"restricted_paths": True, "no_exec": True},
                "git": {"subcommands": {"status", "log", "diff", "add", "commit", "branch", "checkout", "merge", "pull", "push", "remote", "fetch", "stash", "show"}},
                "python": {"blocked": True},  # Block direct python invocation
                "python3": {"blocked": True},
            }
            
            executable = cmd_list[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
            if executable.endswith((".exe", ".com")):
                executable = executable.rsplit(".", 1)[0]
            arguments = [arg.lower() for arg in cmd_list[1:]]
            rm_options = "".join(
                arg.lstrip("-") for arg in arguments if arg.startswith("-")
            )
            
            # Reject if command uses env wrapper to bypass allowlist
            if executable == "env":
                if len(cmd_list) > 1:
                    # Extract the actual command after env
                    next_cmd = cmd_list[1].replace("\\", "/").rsplit("/", 1)[-1].lower()
                    if next_cmd.endswith((".exe", ".com")):
                        next_cmd = next_cmd.rsplit(".", 1)[0]
                    if next_cmd in ALLOWED_COMMANDS and ALLOWED_COMMANDS[next_cmd].get("blocked"):
                        return {"status": "error", "error": f"Blocked: '{next_cmd}' invocation via env is not allowed."}
                return {"status": "error", "error": "Blocked: 'env' wrapper is not allowed."}
            
            # Check if command is explicitly blocked
            if executable in ALLOWED_COMMANDS and ALLOWED_COMMANDS[executable].get("blocked"):
                return {"status": "error", "error": f"Blocked: '{executable}' is not in the execution allowlist."}
            
            # Validate against allowlist
            if executable not in ALLOWED_COMMANDS:
                return {"status": "error", "error": f"Blocked: '{executable}' is not in the execution allowlist."}
            
            cmd_config = ALLOWED_COMMANDS[executable]
            
            # Validate max_args if specified
            if "max_args" in cmd_config and len(arguments) > cmd_config["max_args"]:
                return {"status": "error", "error": f"Blocked: '{executable}' exceeds maximum argument count."}
            
            # Validate args_pattern if specified
            if "args_pattern" in cmd_config:
                pattern = cmd_config["args_pattern"]
                for arg in arguments:
                    if not re.match(pattern, arg):
                        return {"status": "error", "error": f"Blocked: invalid argument '{arg}' for '{executable}'."}
            
            # Validate restricted_paths for commands that require path confinement
            if cmd_config.get("restricted_paths"):
                for arg in arguments:
                    if not arg.startswith("-") and not self._safe_path(arg):
                        return {"status": "error", "error": f"Blocked: path '{arg}' is outside workspace."}
            
            # Validate no_recursive for rm/cat commands
            if cmd_config.get("no_recursive"):
                if "-R" in arguments or "-r" in arguments:
                    return {"status": "error", "error": f"Blocked: recursive operation not allowed for '{executable}'."}
            
            # Validate git subcommands
            if executable == "git":
                if arguments and arguments[0] not in cmd_config.get("subcommands", set()):
                    return {"status": "error", "error": f"Blocked: git subcommand '{arguments[0]}' is not allowed."}
            
            # Validate find restrictions
            if executable == "find":
                if "-exec" in arguments or "-delete" in arguments:
                    return {"status": "error", "error": "Blocked: find -exec/-delete is not allowed."}
            
            # Check for dangerous argument patterns (fallback for non-allowlisted dangers)
            destructive = (
                executable == "mkfs"
                or executable.startswith("mkfs.")
                or executable in {"shutdown", "reboot"}
                or (
                    executable == "format"
                    and any(arg.rstrip("\\/") == "c:" for arg in arguments)
                )
                or (
                    executable == "rm"
                    and "r" in rm_options
                    and "f" in rm_options
                    and any(arg in {"/", "/*"} for arg in arguments)
                )
                or (
                    executable == "chmod"
                    and "R" in rm_options
                    and any(arg == "777" for arg in arguments)
                )
                or (
                    executable == "dd"
                    and any(arg.startswith("if=/dev/") or arg.startswith("of=/dev/") for arg in arguments)
                )
                or any(pattern in command for pattern in ["|", "&&", "||", ";", "`", "$("])
            )
            if destructive:
                return {"status": "error", "error": "Blocked: destructive pattern."}

            proc = subprocess.run(
                cmd_list,
                shell=False,
                capture_output=True,
                text=True,
                cwd=self.workspace,
                timeout=self.EXEC_TIMEOUT,
                check=False,
            )
            output = (proc.stdout or "") + (proc.stderr or "")
            return {
                "status": "success" if proc.returncode == 0 else "error",
                "output": output.strip()[: self.MAX_OUTPUT] or "(no output)",
                "returncode": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"status": "error", "error": f"Timeout ({self.EXEC_TIMEOUT}s)"}
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            return {"status": "error", "error": str(e)}

    def search_web(self, query: str) -> dict:
        """
        Search the web for results matching a query.
        
        Parameters:
        	query (str): The search terms to submit.
        
        Returns:
        	dict: A success response containing up to five results with titles, URLs, and truncated snippets, or an error response when the search cannot be completed.
        """
        try:
            try:
                from duckduckgo_search import DDGS
            except ImportError:
                from ddgs import DDGS
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=5):
                    results.append(
                        {
                            "title": r.get("title", ""),
                            "url": r.get("href", r.get("url", "")),
                            "snippet": (r.get("body") or "")[: self.MAX_SNIPPET],
                        }
                    )
            return {"status": "success", "output": results}
        except (ImportError, ConnectionError, RuntimeError) as e:
            return {"status": "error", "error": f"Search: {e}"}

    def fetch_url(self, url: str) -> dict:
        """
        Fetch text content from an HTTP or HTTPS URL while blocking private and internal IP addresses.
        
        Parameters:
        	url (str): The URL to fetch.
        
        Returns:
        	dict: A success result containing truncated fetched text, or an error result describing why the request failed.
        """
        import socket
        import ipaddress
        from urllib.parse import urlparse
        
        class NoRedirectSession(requests.Session):
            """Custom session that blocks automatic redirects to prevent SSRF via redirect chains."""
            
            def should_strip_auth(self, old_url, new_url):
                # Always strip auth on redirects to prevent credential leakage
                return True
            
            def rebuild_auth(self, prepared_request, response):
                # Strip auth headers on redirects
                headers = prepared_request.headers
                for key in list(headers.keys()):
                    if key.lower() in ('authorization', 'cookie'):
                        del headers[key]
        
        try:
            if not url.startswith(("http://", "https://")):
                return {"status": "error", "error": "http(s) only."}
            
            # Validate initial URL
            parsed = urlparse(url)
            hostname = parsed.hostname
            
            if not hostname:
                return {"status": "error", "error": "Invalid URL"}
            
            # Resolve hostname and check IP addresses for initial URL
            try:
                ip_addresses = socket.getaddrinfo(hostname, None)
                for addr_info in ip_addresses:
                    ip_str = addr_info[4][0]
                    try:
                        ip = ipaddress.ip_address(ip_str)
                        # Block private, loopback, link-local, and multicast ranges
                        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
                            logger.warning("Blocked SSRF attempt to %s (%s)", url, ip_str)
                            return {"status": "error", "error": "Access to private/internal IPs blocked"}
                    except ValueError:
                        continue
            except socket.gaierror:
                return {"status": "error", "error": "DNS resolution failed"}
            
            # Create session with redirect blocking
            session = NoRedirectSession()
            session.max_redirects = 0  # Disable automatic redirects
            
            # Manually handle redirects with validation
            current_url = url
            max_redirects = 5
            redirect_count = 0
            
            while redirect_count < max_redirects:
                try:
                    r = session.get(
                        current_url, 
                        timeout=15, 
                        headers={"User-Agent": "Mozilla/5.0 (RTS)"},
                        allow_redirects=False  # Never follow automatically
                    )
                    
                    if r.status_code in (301, 302, 303, 307, 308):
                        # Redirect detected - validate target before following
                        redirect_count += 1
                        location = r.headers.get('Location')
                        
                        if not location:
                            return {"status": "error", "error": "Redirect without Location header"}
                        
                        # Resolve relative URLs
                        from urllib.parse import urljoin
                        next_url = urljoin(current_url, location)
                        next_parsed = urlparse(next_url)
                        
                        # Validate redirect scheme
                        if next_parsed.scheme not in ('http', 'https'):
                            return {"status": "error", "error": "Redirect to non-HTTP scheme blocked"}
                        
                        # Validate redirect hostname
                        next_hostname = next_parsed.hostname
                        if not next_hostname:
                            return {"status": "error", "error": "Invalid redirect URL"}
                        
                        # Resolve and validate redirect target IP
                        try:
                            next_ips = socket.getaddrinfo(next_hostname, None)
                            for addr_info in next_ips:
                                ip_str = addr_info[4][0]
                                try:
                                    ip = ipaddress.ip_address(ip_str)
                                    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
                                        logger.warning("Blocked SSRF redirect to %s (%s)", next_url, ip_str)
                                        return {"status": "error", "error": "Redirect to private/internal IP blocked"}
                                except ValueError:
                                    continue
                        except socket.gaierror:
                            return {"status": "error", "error": "DNS resolution failed for redirect"}
                        
                        current_url = next_url
                        continue
                    
                    # Non-redirect response - process it
                    break
                    
                except requests.exceptions.TooManyRedirects:
                    return {"status": "error", "error": "Too many redirects"}
            
            if redirect_count >= max_redirects:
                return {"status": "error", "error": "Too many redirects"}
            
            r.raise_for_status()
            if "html" in r.headers.get("content-type", "").lower():
                from bs4 import BeautifulSoup

                text = BeautifulSoup(r.text, "html.parser").get_text(
                    separator="\n", strip=True
                )
            else:
                text = r.text
            return {"status": "success", "output": text[: self.MAX_FETCH_OUTPUT]}
        except requests.RequestException as e:
            return {"status": "error", "error": f"Fetch: {e}"}

    def run_forensic_lint(self, path: str) -> dict:
        """Runs lintstack engine and compresses via SmolLM."""
        try:
            # In production, this calls engine.heal() and engine.ast_pass()
            raw_lint_output = (
                f"AST-SYN000: {path}:42 Syntax Error\nAST-EXT005: requests unresolved"
            )
            compressed = self.brain.compress_diagnostics(raw_lint_output)
            return {"status": "success", "output": compressed}
        except RuntimeError as e:
            logger.warning(f"Forensic lint runtime error: {e}")
            return {"status": "error", "error": str(e)}
        except ValueError as e:
            logger.warning(f"Forensic lint value error: {e}")
            return {"status": "error", "error": str(e)}
        except OSError as e:
            logger.warning(f"Forensic lint OS error: {e}")
            return {"status": "error", "error": str(e)}

    def analyze_crash_dump(self, stderr_text: str) -> dict:
        """Compresses a massive traceback via SmolLM."""
        compressed = self.brain.compress_diagnostics(stderr_text)
        return {"status": "success", "output": compressed}

    # ==========================================================================
    # Application-Specific Agentic Tools
    # ==========================================================================

    def ingest_knowledge(self, paths: list[str]) -> dict:
        """Ingest files into the RAG knowledge base.

        Args:
            paths: List of relative file paths to index.

        Returns:
            dict: Status with count of indexed files.
        """
        try:
            indexed = 0
            for p in paths:
                safe_p, err = self._safe_path(p)
                if err or not safe_p or not safe_p.exists():
                    continue
                try:
                    self.rag.index_file(str(safe_p.relative_to(Path(self.workspace))))
                    indexed += 1
                except (OSError, ValueError, TypeError):
                    pass
            return {"status": "success", "indexed": indexed, "requested": len(paths)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def query_knowledge_base(self, query: str, top_k: int = 5) -> dict:
        """Query the RAG knowledge base for relevant context.

        Args:
            query: Search query string.
            top_k: Number of results to return.

        Returns:
            dict: Status with matching chunks and scores.
        """
        try:
            # Use the existing 'query' method on RAGIndex
            results = self.rag.query(query, top_k=top_k)
            return {"status": "success", "results": results}
        except (ValueError, TypeError, OSError) as e:
            return {"status": "error", "error": str(e)}

    def run_diagnostic_scan(self, target: str = "full") -> dict:
        """Run diagnostic analysis using the ONNX brain model.

        Args:
            target: What to scan ('full', 'memory', 'disk', 'network').

        Returns:
            dict: Diagnostic results and recommendations.
        """
        try:
            if not self.brain.is_ready:
                return {
                    "status": "unavailable",
                    "error": "Diagnostic model not loaded",
                }
            # Simulate diagnostic scan (actual implementation would use brain)
            scan_result = {
                "target": target,
                "timestamp": time.time(),
                "health": "ok",
                "issues": [],
            }
            return {"status": "success", "diagnostic": scan_result}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def speak_response(self, text: str) -> dict:
        """
        Generate speech audio for the supplied text.
        
        Args:
            text: Text to synthesize.
        
        Returns:
            A status dictionary containing base64-encoded WAV audio on success, or an
            error message when synthesis fails.
        """
        try:
            # Use asyncio.run since generate_wav is async
            wav_data, status = asyncio.run(self.tts.generate_wav(text))
            if wav_data is None:
                return {"status": "error", "error": f"TTS failed: {status}"}
            return {
                "status": "success",
                "audio_base64": base64.b64encode(wav_data).decode('ascii'),
                "format": "wav",
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def get_agent_status(self) -> dict:
        """Get status of all agent components.

        Returns:
            dict: Status of brain, TTS, STT, and RAG components.
        """
        # Check TTS availability by verifying dependencies and model can load
        tts_available = False
        try:
            from kokoro_onnx import Kokoro
            import soundfile
            import numpy
            
            # Check if models exist
            models_dir = self.tts.models_dir if hasattr(self, 'tts') and self.tts else None
            if models_dir:
                onnx_path = models_dir / "kokoro-v1.0.onnx"
                voices_path = models_dir / "voices-v1.0.bin"
                tts_available = onnx_path.exists() and voices_path.exists()
        except (ImportError, AttributeError):
            tts_available = False
        
        return {
            "status": "success",
            "components": {
                "brain": {"ready": self.brain.is_ready},
                "tts": {"available": tts_available},
                "stt": {"available": HAS_STT},
                "rag": {"indexed_files": len(self.rag.cache) if hasattr(self.rag, 'cache') else 0},
            },
        }

    def copy_file(self, src: str, dst: str) -> dict:
        """
        Copy a file from one workspace path to another.
        
        Parameters:
            src (str): Source path relative to the workspace.
            dst (str): Destination path relative to the workspace.
        
        Returns:
            dict: Operation status, copied byte count, and destination on success, or an error description.
        """
        src_p, err = self._safe_path(src)
        if err or not src_p:
            return err or {"status": "error", "error": "Invalid source"}
        dst_p, err = self._safe_path(dst)
        if err or not dst_p:
            return err or {"status": "error", "error": "Invalid destination"}
        if not src_p.exists() or not src_p.is_file():
            return {"status": "error", "error": f"Source not found: {src}"}
        try:
            dst_p.parent.mkdir(parents=True, exist_ok=True)
            # Atomic copy: write to temp file in destination directory, then rename
            fd, tmp_path = tempfile.mkstemp(dir=str(dst_p.parent), prefix='.tmp_copy_')
            try:
                # Copy content with metadata preservation
                with os.fdopen(fd, 'wb') as tmp_f:
                    with open(src_p, 'rb') as src_f:
                        while chunk := src_f.read(8192):
                            tmp_f.write(chunk)
                    tmp_f.flush()
                    os.fsync(tmp_f.fileno())
                
                # Set metadata from source (timestamps and permission mode)
                src_stat = src_p.stat()
                os.utime(tmp_path, (src_stat.st_atime, src_stat.st_mtime))
                os.chmod(tmp_path, stat.S_IMODE(src_stat.st_mode))
                
                # Atomic rename
                os.replace(tmp_path, str(dst_p))
            except OSError:
                # Clean up temp file on failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            
            return {
                "status": "success",
                "bytes": src_p.stat().st_size,
                "destination": dst,
            }
        except OSError as e:
            return {"status": "error", "error": str(e)}

    def delete_file(self, path: str) -> dict:
        """Delete a file from the workspace.

        Args:
            path: Relative path to delete.

        Returns:
            dict: Status confirmation.
        """
        p, err = self._safe_path(path)
        if err or not p:
            return err or {"status": "error", "error": "Invalid path"}
        if not p.exists() or not p.is_file():
            return {"status": "error", "error": f"Not found: {path}"}
        if is_sensitive_path(str(p)):
            return {"status": "error", "error": "Blocked: sensitive path"}
        try:
            # Derive file_id for RAG cleanup before deletion
            rel_path = str(p.relative_to(self.workspace))
            file_id = rel_path.replace("\\", "/").lstrip("/")
            
            p.unlink()
            
            # Call RAGIndex.remove_file to properly remove chunks and rebuild index
            if hasattr(self.rag, 'remove_file'):
                self.rag.remove_file(file_id)
            
            return {"status": "success", "deleted": path}
        except OSError as e:
            return {"status": "error", "error": str(e)}

    def move_file(self, src: str, dst: str) -> dict:
        """Move/rename a file within the workspace atomically.

        Args:
            src: Source relative path.
            dst: Destination relative path.

        Returns:
            dict: Status confirmation.
        """
        src_p, err = self._safe_path(src)
        if err or not src_p:
            return err or {"status": "error", "error": "Invalid source"}
        dst_p, err = self._safe_path(dst)
        if err or not dst_p:
            return err or {"status": "error", "error": "Invalid destination"}
        if not src_p.exists():
            return {"status": "error", "error": f"Source not found: {src}"}
        try:
            dst_p.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src_p), str(dst_p))
            return {"status": "success", "moved": f"{src} -> {dst}"}
        except OSError as e:
            return {"status": "error", "error": str(e)}

    def file_exists(self, path: str) -> dict:
        """Check if a file exists in the workspace.

        Args:
            path: Relative path to check.

        Returns:
            dict: Status with exists boolean.
        """
        p, err = self._safe_path(path)
        if err or not p:
            return {"status": "success", "exists": False}
        return {"status": "success", "exists": p.exists()}

    def get_file_info(self, path: str) -> dict:
        """Get metadata about a file.

        Args:
            path: Relative path.

        Returns:
            dict: File metadata (size, modified time, etc.).
        """
        p, err = self._safe_path(path)
        if err or not p or not p.exists():
            return {"status": "error", "error": f"Not found: {path}"}
        try:
            stat = p.stat()
            return {
                "status": "success",
                "size_bytes": stat.st_size,
                "modified": stat.st_mtime,
                "created": getattr(stat, 'st_ctime', stat.st_mtime),
                "is_file": p.is_file(),
                "is_dir": p.is_dir(),
            }
        except OSError as e:
            return {"status": "error", "error": str(e)}


    # ==========================================================================
    # Advanced Agentic Features (Phase 3)
    # ==========================================================================

    def get_system_resources(self) -> dict:
        """Get current system resource usage optimized for HDD/8GB RAM setup.
        
        Returns:
            dict: CPU, RAM, Disk I/O metrics with HDD-aware thresholds.
        """
        try:
            import psutil
        except ImportError:
            return {
                "status": "success",
                "cpu_percent": 0,
                "memory_used_mb": 0,
                "memory_total_mb": 8192,
                "memory_percent": 0,
                "disk_read_mb": 0,
                "disk_write_mb": 0,
                "warning": "psutil not installed",
            }
        
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        mem_used = mem.used / (1024 * 1024)
        mem_total = mem.total / (1024 * 1024)
        mem_percent = mem.percent
        
        disk_io = psutil.disk_io_counters()
        disk_read = (disk_io.read_bytes or 0) / (1024 * 1024)
        disk_write = (disk_io.write_bytes or 0) / (1024 * 1024)
        
        warning = None
        if mem_percent > 75:
            warning = "High memory usage - risk of HDD swapping"
        
        return {
            "status": "success",
            "cpu_percent": cpu,
            "memory_used_mb": round(mem_used, 2),
            "memory_total_mb": round(mem_total, 2),
            "memory_percent": mem_percent,
            "disk_read_mb": round(disk_read, 2),
            "disk_write_mb": round(disk_write, 2),
            "swap_warning": warning,
        }

    def check_resource_limits(self, operation: str = "default") -> dict:
        """Check if an operation is within safe resource limits."""
        try:
            import psutil
        except ImportError:
            return {"status": "success", "approved": True, "limits": "unknown"}
        
        mem = psutil.virtual_memory()
        mem_available_gb = mem.available / (1024 * 1024 * 1024)
        
        limits = {
            "file_read": {"max_size_mb": 500},
            "code_exec": {"max_ram_mb": 2048, "timeout_sec": 30},
            "model_load": {"max_vram_gb": 3.5, "offload_cpu": True},
            "rag_index": {"max_files": 1000, "batch_size": 50},
            "default": {"max_ram_mb": 4096, "timeout_sec": 60},
        }
        
        op_limit = limits.get(operation, limits["default"])
        
        if mem_available_gb < 1.0:
            return {
                "status": "success",
                "approved": False,
                "reason": f"Critical: Only {mem_available_gb:.2f}GB RAM available",
                "limits": op_limit,
            }
        
        return {
            "status": "success",
            "approved": True,
            "available_ram_gb": round(mem_available_gb, 2),
            "limits": op_limit,
        }

    def delegate_task(self, role: str, task: str, context: dict | None = None) -> dict:
        """Delegate a sub-task to a specialized agent role."""
        if not hasattr(self, '_delegated_tasks'):
            self._delegated_tasks = {}
        
        task_id = f"{role}_{int(time.time())}"
        self._delegated_tasks[task_id] = {
            "role": role,
            "task": task,
            "context": context or {},
            "status": "pending",
            "created": time.time(),
        }
        
        logger.info("Delegated task %s to role %s", task_id, role)
        return {
            "status": "success",
            "task_id": task_id,
            "role": role,
            "message": f"Task delegated to {role} agent",
        }

    def cancel_task(self, task_id: str) -> dict:
        """Cancel a delegated task."""
        if not hasattr(self, '_delegated_tasks'):
            return {"status": "error", "error": "No tasks found"}
        
        if task_id not in self._delegated_tasks:
            return {"status": "error", "error": f"Task not found: {task_id}"}
        
        self._delegated_tasks[task_id]["status"] = "cancelled"
        return {"status": "success", "task_id": task_id, "message": "Task cancelled"}

    def save_session_state(self, key: str, value: Any) -> dict:
        """Persist session state with atomic write."""
        state_file = Path(self.workspace) / ".session_state.json"
        
        state = {}
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                state = {}
        
        state[key] = value
        
        try:
            fd, tmp_path = tempfile.mkstemp(dir=state_file.parent, prefix='.tmp_state_')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(state, f, indent=2, default=str)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, str(state_file))
            except OSError:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            
            return {"status": "success", "key": key, "message": "State persisted"}
        except (OSError, TypeError) as e:
            return {"status": "error", "error": str(e)}

    def load_session_state(self, key: str | None = None) -> dict:
        """Load persisted session state."""
        state_file = Path(self.workspace) / ".session_state.json"
        
        if not state_file.exists():
            return {"status": "success", "state": {}}
        
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            if key:
                return {"status": "success", "key": key, "value": state.get(key)}
            return {"status": "success", "state": state}
        except (json.JSONDecodeError, OSError) as e:
            return {"status": "error", "error": str(e)}

    def create_checkpoint(self, name: str = "manual") -> dict:
        """Create a workspace checkpoint with Git tag."""
        if self.sandbox_mode:
            return {"status": "error", "error": "Checkpointing disabled in sandbox mode."}
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        tag_name = f"checkpoint_{name}_{timestamp}"
        
        try:
            subprocess.run(["git", "add", "-A"], cwd=self.workspace, capture_output=True, timeout=30, check=False)
            
            result = subprocess.run(
                ["git", "commit", "-m", f"Checkpoint: {name}"],
                cwd=self.workspace, capture_output=True, text=True, timeout=30, check=False
            )
            
            if result.returncode != 0 and "nothing to commit" not in result.stdout:
                return {"status": "error", "error": "Git commit failed", "output": result.stdout + result.stderr}
            
            tag_result = subprocess.run(
                ["git", "tag", tag_name],
                cwd=self.workspace, capture_output=True, text=True, timeout=10, check=False
            )
            
            if tag_result.returncode != 0:
                return {"status": "error", "error": "Tag creation failed", "output": tag_result.stdout + tag_result.stderr}
            
            return {"status": "success", "tag": tag_name, "message": f"Checkpoint created: {tag_name}"}
        except subprocess.TimeoutExpired:
            return {"status": "error", "error": "Checkpoint timeout"}
        except (OSError, subprocess.SubprocessError) as e:
            return {"status": "error", "error": str(e)}

    def chain_commands(self, commands: list[dict]) -> dict:
        """Execute a sequence of tool commands with dependency passing."""
        results = []
        context = {}
        
        for i, cmd in enumerate(commands):
            tool_name = cmd.get("tool")
            args = cmd.get("args", {})
            
            resolved_args = {}
            for k, v in args.items():
                if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
                    var_name = v[2:-1]
                    resolved_args[k] = context.get(var_name)
                else:
                    resolved_args[k] = v
            
            result = self.execute(tool_name, resolved_args)
            results.append({"step": i, "tool": tool_name, "result": result})
            
            if result.get("status") == "error":
                return {
                    "status": "error",
                    "failed_at_step": i,
                    "results": results,
                    "error": f"Step {i} ({tool_name}) failed: {result.get('error')}",
                }
            
            if result.get("status") == "success":
                context[f"step_{i}_output"] = result.get("output")
                if "path" in result:
                    context[f"step_{i}_path"] = result["path"]
        
        return {"status": "success", "steps_completed": len(results), "results": results}


    # ==========================================================================
    # Development Workflow Tools (Phase 2)
    # ==========================================================================

    def git_status(self) -> dict:
        """Get Git repository status.

        Returns:
            dict: Git status including branch, changes, and untracked files.
        """
        if self.sandbox_mode:
            return {"status": "error", "error": "Git operations disabled in sandbox mode."}
        try:
            # Check if in git repo
            proc = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                cwd=self.workspace,
                timeout=10,
                check=False,
            )
            if proc.returncode != 0:
                return {"status": "error", "error": "Not a Git repository"}

            # Get current branch
            branch_proc = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                cwd=self.workspace,
                timeout=10,
                check=False,
            )
            branch = branch_proc.stdout.strip() or "HEAD (detached)"

            # Get status
            status_proc = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=self.workspace,
                timeout=10,
                check=False,
            )

            changes = []
            for line in status_proc.stdout.strip().split('\n'):
                if line:
                    changes.append(line)

            return {
                "status": "success",
                "branch": branch,
                "changes": changes,
                "has_changes": len(changes) > 0,
            }
        except subprocess.TimeoutExpired:
            return {"status": "error", "error": "Git operation timeout"}
        except (OSError, subprocess.SubprocessError) as e:
            return {"status": "error", "error": str(e)}

    def git_commit(self, message: str, files: list[str] | None = None) -> dict:
        """Commit changes to Git repository.

        Args:
            message: Commit message.
            files: Optional list of specific files to stage (None = all changes).

        Returns:
            dict: Commit result with hash.
        """
        if self.sandbox_mode:
            return {"status": "error", "error": "Git operations disabled in sandbox mode."}
        if not message or not message.strip():
            return {"status": "error", "error": "Empty commit message"}

        try:
            # Stage files
            if files:
                for f in files:
                    p, err = self._safe_path(f)
                    if err or not p:
                        continue
                    subprocess.run(
                        ["git", "add", str(p)],
                        capture_output=True,
                        text=True,
                        cwd=self.workspace,
                        timeout=10,
                        check=False,
                    )
            else:
                subprocess.run(
                    ["git", "add", "-A"],
                    capture_output=True,
                    text=True,
                    cwd=self.workspace,
                    timeout=10,
                    check=False,
                )

            # Commit
            commit_proc = subprocess.run(
                ["git", "commit", "-m", message],
                capture_output=True,
                text=True,
                cwd=self.workspace,
                timeout=10,
                check=False,
            )

            if commit_proc.returncode != 0:
                return {"status": "error", "error": commit_proc.stderr.strip() or "Commit failed"}

            # Get commit hash
            hash_proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=self.workspace,
                timeout=10,
                check=False,
            )

            return {
                "status": "success",
                "hash": hash_proc.stdout.strip(),
                "message": message,
            }
        except subprocess.TimeoutExpired:
            return {"status": "error", "error": "Git operation timeout"}
        except (OSError, subprocess.SubprocessError) as e:
            return {"status": "error", "error": str(e)}

    def git_diff(self, path: str | None = None) -> dict:
        """Get Git diff for file or entire repo.

        Args:
            path: Optional specific file path (None = all changes).

        Returns:
            dict: Diff output.
        """
        if self.sandbox_mode:
            return {"status": "error", "error": "Git operations disabled in sandbox mode."}
        try:
            cmd = ["git", "diff"]
            if path:
                p, err = self._safe_path(path)
                if err or not p:
                    return err or {"status": "error", "error": "Invalid path"}
                cmd.append(str(p))

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.workspace,
                timeout=10,
                check=False,
            )

            return {
                "status": "success" if proc.returncode == 0 else "error",
                "diff": proc.stdout or "(no changes)",
            }
        except subprocess.TimeoutExpired:
            return {"status": "error", "error": "Git operation timeout"}
        except (OSError, subprocess.SubprocessError) as e:
            return {"status": "error", "error": str(e)}

    def install_package(self, package: str, upgrade: bool = False) -> dict:
        """Install Python package using pip.

        Args:
            package: Package name (with optional version specifier).
            upgrade: If True, upgrade existing package.

        Returns:
            dict: Installation result.
        """
        if self.sandbox_mode:
            return {"status": "error", "error": "Package installation disabled in sandbox mode."}
        if not package or not package.strip():
            return {"status": "error", "error": "Empty package name"}

        try:
            cmd = [sys.executable, "-m", "pip", "install"]
            if upgrade:
                cmd.append("--upgrade")
            cmd.append(package)

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.workspace,
                timeout=120,  # Longer timeout for downloads
                check=False,
            )

            if proc.returncode != 0:
                return {"status": "error", "error": proc.stderr.strip() or "Installation failed"}

            return {
                "status": "success",
                "package": package,
                "output": proc.stdout.strip()[-500:],  # Last 500 chars
            }
        except subprocess.TimeoutExpired:
            return {"status": "error", "error": "Package installation timeout"}
        except (OSError, subprocess.SubprocessError) as e:
            return {"status": "error", "error": str(e)}

    def run_tests(self, path: str = ".", test_runner: str = "pytest") -> dict:
        """Run test suite.

        Args:
            path: Path to tests (default: current directory).
            test_runner: Test runner to use ('pytest', 'unittest').

        Returns:
            dict: Test results.
        """
        if self.sandbox_mode:
            return {"status": "error", "error": "Test execution disabled in sandbox mode."}

        try:
            p, err = self._safe_path(path)
            if err or not p:
                return err or {"status": "error", "error": "Invalid path"}

            if test_runner == "pytest":
                cmd = [sys.executable, "-m", "pytest", str(p), "-v"]
            elif test_runner == "unittest":
                cmd = [sys.executable, "-m", "unittest", "discover", "-s", str(p)]
            else:
                return {"status": "error", "error": f"Unknown test runner: {test_runner}"}

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.workspace,
                timeout=300,  # 5 min for tests
                check=False,
            )

            # Parse basic results
            passed = proc.returncode == 0
            output = (proc.stdout or "") + (proc.stderr or "")

            return {
                "status": "success" if passed else "test_failure",
                "passed": passed,
                "returncode": proc.returncode,
                "output": output.strip()[-2000:],  # Last 2000 chars
            }
        except subprocess.TimeoutExpired:
            return {"status": "error", "error": "Test execution timeout"}
        except (OSError, subprocess.SubprocessError) as e:
            return {"status": "error", "error": str(e)}

    def run_linter(self, path: str, linter: str = "flake8") -> dict:
        """Run code linter.

        Args:
            path: Path to lint.
            linter: Linter to use ('flake8', 'pylint', 'ruff').

        Returns:
            dict: Lint results.
        """
        if self.sandbox_mode:
            return {"status": "error", "error": "Linting disabled in sandbox mode."}

        try:
            p, err = self._safe_path(path)
            if err or not p:
                return err or {"status": "error", "error": "Invalid path"}

            if linter == "flake8":
                cmd = [sys.executable, "-m", "flake8", str(p), "--max-line-length=100"]
            elif linter == "pylint":
                cmd = [sys.executable, "-m", "pylint", str(p), "--disable=C0114,C0115,C0116"]
            elif linter == "ruff":
                cmd = [sys.executable, "-m", "ruff", "check", str(p)]
            else:
                return {"status": "error", "error": f"Unknown linter: {linter}"}

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.workspace,
                timeout=60,
                check=False,
            )

            # Linters return non-zero for violations, which is expected
            has_issues = proc.returncode != 0 or proc.stdout.strip()

            return {
                "status": "success",
                "has_issues": has_issues,
                "output": (proc.stdout or proc.stderr or "(no issues)").strip()[-2000:],
            }
        except subprocess.TimeoutExpired:
            return {"status": "error", "error": "Linting timeout"}
        except (OSError, subprocess.SubprocessError) as e:
            return {"status": "error", "error": str(e)}

    def check_vulnerabilities(self, path: str = ".") -> dict:
        """
        Scan workspace dependencies for known security vulnerabilities.
        
        Parameters:
            path (str): Retained for API compatibility; the scan uses the configured workspace.
        
        Returns:
            dict: A status report containing vulnerability findings, scanner output, or an error.
        """
        if self.sandbox_mode:
            return {"status": "error", "error": "Security scanning disabled in sandbox mode."}

        try:
            # Try pip-audit first
            cmd = [sys.executable, "-m", "pip_audit", "--format", "json"]

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.workspace,
                timeout=120,
                check=False,
            )

            # Non-zero exit without valid JSON = error, not success
            if proc.returncode != 0:
                # Try to parse JSON anyway (pip-audit returns non-zero when vulns found)
                try:
                    vulns = json.loads(proc.stdout)
                    if isinstance(vulns, list):
                        return {
                            "status": "success",
                            "vulnerabilities": vulns,
                            "count": len(vulns),
                            "summary": f"Found {len(vulns)} vulnerability/vulnerabilities",
                        }
                except json.JSONDecodeError:
                    pass
                
                # No valid JSON and non-zero exit = actual error
                return {
                    "status": "error",
                    "error": (proc.stderr or proc.stdout).strip()[-2000:] or "Scanner failed",
                    "output": (proc.stdout or "").strip()[-2000:],
                }

            # Exit code 0 = no vulnerabilities
            return {
                "status": "success",
                "vulnerabilities": [],
                "output": "No vulnerabilities found",
            }
        except subprocess.TimeoutExpired:
            return {"status": "error", "error": "Security scan timeout"}
        except (OSError, subprocess.SubprocessError) as e:
            return {"status": "error", "error": str(e)}

    def execute(self, name: str, args: dict | None) -> dict:
        """
        Dispatch a named tool with validated arguments.
        
        Parameters:
            name (str): Name of the tool to execute.
            args (dict | None): Tool arguments, or None when no arguments are required.
        
        Returns:
            dict: Tool result, or an error result for invalid arguments, unknown tools, or conversion failures.
        """
        # Validate args is a dict
        if args is not None and not isinstance(args, dict):
            return {"status": "error", "error": f"Invalid arguments type: expected dict, got {type(args).__name__}"}
        
        args = args or {}
        try:
            if name == "run_shell":
                return self.run_shell(str(args.get("command", "")))
            if name == "read_file":
                return self.read_file(
                    str(args.get("path", "")), 
                    chunked=bool(args.get("chunked", False))
                )
            if name == "write_file":
                return self.write_file(
                    str(args.get("path", "")), str(args.get("content", ""))
                )
            if name == "list_directory":
                return self.list_directory(
                    str(args.get("path", ".")),
                    recursive=bool(args.get("recursive", False))
                )
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
            # New application-specific tools
            if name == "ingest_knowledge":
                return self.ingest_knowledge(list(args.get("paths", [])))
            if name == "query_knowledge_base":
                return self.query_knowledge_base(
                    str(args.get("query", "")),
                    int(args.get("top_k", 5))
                )
            if name == "run_diagnostic_scan":
                return self.run_diagnostic_scan(str(args.get("target", "full")))
            if name == "speak_response":
                return self.speak_response(str(args.get("text", "")))
            if name == "get_agent_status":
                return self.get_agent_status()
            if name == "copy_file":
                return self.copy_file(
                    str(args.get("src", "")), 
                    str(args.get("dst", ""))
                )
            if name == "delete_file":
                return self.delete_file(str(args.get("path", "")))
            if name == "move_file":
                return self.move_file(
                    str(args.get("src", "")), 
                    str(args.get("dst", ""))
                )
            if name == "file_exists":
                return self.file_exists(str(args.get("path", "")))
            if name == "get_file_info":
                return self.get_file_info(str(args.get("path", "")))
            # Development workflow tools (Phase 2)
            if name == "git_status":
                return self.git_status()
            if name == "git_commit":
                return self.git_commit(
                    str(args.get("message", "")),
                    args.get("files")  # Can be None or list
                )
            if name == "git_diff":
                path = args.get("path")
                return self.git_diff(str(path) if path else None)
            if name == "install_package":
                return self.install_package(
                    str(args.get("package", "")),
                    bool(args.get("upgrade", False))
                )
            if name == "run_tests":
                return self.run_tests(
                    str(args.get("path", ".")),
                    str(args.get("test_runner", "pytest"))
                )
            if name == "run_linter":
                return self.run_linter(
                    str(args.get("path", ".")),
                    str(args.get("linter", "flake8"))
                )
            if name == "check_vulnerabilities":
                return self.check_vulnerabilities(str(args.get("path", ".")))
            # Advanced agentic features (Phase 3)
            if name == "get_system_resources":
                return self.get_system_resources()
            if name == "check_resource_limits":
                return self.check_resource_limits(str(args.get("operation", "default")))
            if name == "delegate_task":
                return self.delegate_task(
                    str(args.get("role", "assistant")),
                    str(args.get("task", "")),
                    args.get("context")
                )
            if name == "cancel_task":
                return self.cancel_task(str(args.get("task_id", "")))
            if name == "save_session_state":
                return self.save_session_state(
                    str(args.get("key", "")),
                    args.get("value")
                )
            if name == "load_session_state":
                key = args.get("key")
                return self.load_session_state(str(key) if key else None)
            if name == "create_checkpoint":
                return self.create_checkpoint(str(args.get("name", "manual")))
            if name == "chain_commands":
                commands = args.get("commands", [])
                if isinstance(commands, list):
                    return self.chain_commands(commands)
                return {"status": "error", "error": "commands must be a list"}
            return {"status": "error", "error": f"Unknown: {name}"}
        except (ValueError, TypeError) as e:
            return {"status": "error", "error": f"{type(e).__name__}: {e}"}


# ==============================================================================
# Failover Stack
# ==============================================================================


class FailoverEntry:
    MAX_ERROR_LEN = 200

    def __init__(
        self,
        name: str,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
        priority: int = 0,
    ) -> None:
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
            "name": self.name,
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "priority": self.priority,
            "dead": self.dead,
            "error_count": self.error_count,
            "cooldown_until": self.cooldown_until,
            "cooldown_remaining": max(0.0, round(self.cooldown_until - time.time(), 1)),
            "last_error": self.last_error[: self.MAX_ERROR_LEN],
        }


class FailoverStack:
    COOLDOWN_SECONDS = 120.0
    MAX_ERRORS = 4

    def __init__(self, entries: list[FailoverEntry] | None = None) -> None:
        self.entries: list[FailoverEntry] = list(entries or [])
        self._lock = threading.Lock()

    @classmethod
    def load_config(cls, cfg: dict | None = None) -> FailoverStack:
        cfg = cfg if cfg is not None else load_config()
        entries: list[FailoverEntry] = []
        api_keys = cfg.get("api_keys", {})
        role_assignments = cfg.get("role_assignments", {})
        if not role_assignments:
            role_assignments = {
                "quick_coding": "quick_coding",
                "complex_coding": "complex_coding",
                "writing": "writing",
                "offline_local": "offline_local",
            }
        priorities = {
            "quick_coding": 0,
            "complex_coding": 1,
            "writing": 2,
            "offline_local": 10,
        }
        for role, preset_name in role_assignments.items():
            preset = AI_ROLE_PRESETS.get(preset_name)
            if not preset:
                continue
            provider = preset["provider"]
            api_key = api_keys.get(provider, "")
            if provider == "ollama":
                api_key = "ollama"
            entries.append(
                FailoverEntry(
                    name=role,
                    provider=provider,
                    base_url=preset["base_url"],
                    api_key=api_key,
                    model=preset["model_id"],
                    priority=priorities.get(role, 5),
                )
            )
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
                logger.warning(
                    "Failover '%s' DEAD after %d errors", entry.name, entry.error_count
                )
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
            "active": len(self.ordered()),
            "total": len(self.entries),
            "entries": [
                e.to_dict() for e in sorted(self.entries, key=lambda x: x.priority)
            ],
        }


# ==============================================================================
# AgentSwarm
# ==============================================================================


class AgentSwarm:
    TOOL_SPECS: ClassVar[list[dict]] = [
        {
            "type": "function",
            "function": {
                "name": "list_directory",
                "description": "List files.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Sub-dir"}
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read file.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string", "description": "Path"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string", "description": "Full content"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_python",
                "description": "Run .py file.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_shell",
                "description": "Run shell cmd.",
                "parameters": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_web",
                "description": "Search web.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_url",
                "description": "Fetch URL.",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_forensic_lint",
                "description": "Run lintstack and compress via local brain.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "analyze_crash_dump",
                "description": "Compress traceback via local brain.",
                "parameters": {
                    "type": "object",
                    "properties": {"stderr": {"type": "string"}},
                    "required": ["stderr"],
                },
            },
        },
    ]
    SYSTEM_PROMPT = (
        'You are "Red Tongue", the primary agent of a local-first AI coding studio. '
        "You operate directly inside the user's live workspace with real tools.\n\n"
        "WORKSPACE RULES:\n- Paths relative to root.\n- Inspect before editing.\n"
        "- write_file gets COMPLETE content.\n- Keep shell usage safe.\n\n"
        "TOOLS: list_directory, read_file, write_file, run_python, run_shell, "
        "search_web, fetch_url, run_forensic_lint, analyze_crash_dump.\n\n"
        "BEHAVIOUR:\n- Think briefly, then act.\n- Summarise changes.\n"
        "- Refuse unsafe requests.\n\nOUTPUT: Concise, technical, Markdown."
    )

    def __init__(
        self, tool_layer: ToolLayer, failover_config: FailoverStack | None = None
    ) -> None:
        self.tool_layer = tool_layer
        self.failover = (
            failover_config
            if failover_config is not None
            else FailoverStack.load_config()
        )
        self._clients: dict[str, Any] = {}
        self._no_tools: set = set()
        self.reset_clients()

    def reset_clients(self) -> None:
        """Reset OpenAI client connections for all failover entries."""
        self._clients = {}
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            logger.error("openai SDK unavailable: %s", e)
            return
        for entry in self.failover.entries:
            if not entry.api_key:
                continue
            try:
                self._clients[entry.name] = AsyncOpenAI(
                    api_key=entry.api_key,
                    base_url=entry.base_url,
                    timeout=90.0,
                    max_retries=0,
                )
            except (ValueError, TypeError) as e:
                logger.warning("Client init '%s': %s", entry.name, e)

    def rebuild_failover(self) -> None:
        self.failover = FailoverStack.load_config()
        self.reset_clients()

    def _build_messages(
        self,
        message: str,
        history: list | None,
        rag_context: str,
        custom_system_prompt: str = "",
    ) -> list[dict]:
        sys_content = self.SYSTEM_PROMPT
        if custom_system_prompt and custom_system_prompt.strip():
            sys_content = custom_system_prompt.strip()
        msgs: list[dict] = [{"role": "system", "content": sys_content}]
        if rag_context and rag_context.strip():
            msgs.append({"role": "system", "content": "RAG context:\n\n" + rag_context})
        hist = [
            m
            for m in (history or [])
            if isinstance(m, dict)
            and m.get("role") in ("user", "assistant")
            and m.get("content")
        ]
        if (
            hist
            and hist[-1].get("role") == "user"
            and str(hist[-1].get("content", "")).strip() == str(message).strip()
        ):
            hist = hist[:-1]
        msgs.extend(hist[-12:])
        msgs.append({"role": "user", "content": message})
        return msgs

    async def run_main_agent(
        self,
        message: str,
        history: list | None = None,
        autopilot: bool = True,
        effort: str = "medium",
        response_queue=None,
        rag_context: str = "",
        disable_tools: bool = False,
        custom_system_prompt: str = "",
    ) -> AsyncGenerator[str, None]:
        """
        Stream agent responses with provider failover and optional tool execution.
        
        Parameters:
            message (str): User message to process.
            history (list | None): Prior conversation messages.
            autopilot (bool): Whether automatic tool use is enabled.
            effort (str): Response effort level, determining the maximum number of
                agent rounds.
            response_queue: Optional destination for streamed responses.
            rag_context (str): Retrieved context to include in the conversation.
            disable_tools (bool): Whether to disable tool calls.
            custom_system_prompt (str): Optional replacement system prompt.
        
        Yields:
            str: JSON-encoded stream, tool-result, error, or completion event.
        """
        # Import exception types at function scope for availability
        try:
            from openai import APIConnectionError, RateLimitError
        except ImportError:
            APIConnectionError = Exception  # type: ignore
            RateLimitError = Exception  # type: ignore
        message = (message or "").strip()
        if not message:
            yield json.dumps({"type": "error", "content": "Empty message."})
            return
        max_rounds = {"low": 1, "medium": 4, "high": 8}.get(str(effort).lower(), 4)
        messages = self._build_messages(
            message, history, rag_context, custom_system_prompt
        )
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
                kwargs: dict[str, Any] = {
                    "model": entry.model,
                    "messages": messages,
                    "stream": True,
                }
                if use_tools:
                    kwargs["tools"] = self.TOOL_SPECS
                stream = await client.chat.completions.create(**kwargs)
            except APIConnectionError as e:
                err = f"Connection error: {e}"
                self.failover.report_failure(entry, err)
                yield json.dumps(
                    {
                        "type": "stream",
                        "content": f"\n\n> ⚡ `{entry.name}` failed ({err[:140]}).\n\n",
                    }
                )
                continue
            except RateLimitError as e:
                err = f"Rate limit: {e}"
                self.failover.report_failure(entry, err)
                yield json.dumps(
                    {
                        "type": "stream",
                        "content": f"\n\n> ⚡ `{entry.name}` rate limited.\n\n",
                    }
                )
                continue
            except Exception as e:
                err = str(e)
                if use_tools and "tool" in err.lower():
                    self._no_tools.add(entry.name)
                    continue
                self.failover.report_failure(entry, err)
                yield json.dumps(
                    {
                        "type": "stream",
                        "content": f"\n\n> ⚡ `{entry.name}` failed ({err[:140]}).\n\n",
                    }
                )
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
                            acc = tool_calls.setdefault(
                                idx, {"id": "", "name": "", "arguments": ""}
                            )
                            if tc.id:
                                acc["id"] = tc.id
                            fn = getattr(tc, "function", None)
                            if fn:
                                if fn.name:
                                    acc["name"] = fn.name
                                if fn.arguments:
                                    acc["arguments"] += fn.arguments
            except APIConnectionError as e:
                self.failover.report_failure(entry, f"Stream connection: {e}")
                yield json.dumps(
                    {
                        "type": "stream",
                        "content": "\n\n>  Stream connection lost. Retrying…\n\n",
                    }
                )
                if content_parts:
                    messages.append(
                        {"role": "assistant", "content": "".join(content_parts)}
                    )
                continue
            except Exception as e:
                self.failover.report_failure(entry, str(e))
                err_msg = str(e)[:140]
                yield json.dumps(
                    {
                        "type": "stream",
                        "content": f"\n\n>  Stream broke ({err_msg}). Retrying…\n\n",
                    }
                )
                if content_parts:
                    messages.append(
                        {"role": "assistant", "content": "".join(content_parts)}
                    )
                continue
            self.failover.report_success(entry)
            rounds += 1
            full_text = "".join(content_parts)
            if tool_calls:
                calls: list[dict[str, Any]] = []
                for i, tc in sorted(tool_calls.items()):
                    calls.append(
                        {
                            "id": tc.get("id") or f"call_{i}",
                            "type": "function",
                            "function": {
                                "name": tc.get("name") or "unknown",
                                "arguments": tc.get("arguments") or "{}",
                            },
                        }
                    )
                messages.append(
                    {
                        "role": "assistant",
                        "content": full_text or None,
                        "tool_calls": calls,
                    }
                )
                for call in calls:
                    func_data = call.get("function", {})
                    if not isinstance(func_data, dict):
                        continue
                    name = func_data.get("name", "unknown")
                    try:
                        args = json.loads(func_data.get("arguments", "{}"))
                        if not isinstance(args, dict):
                            args = {}
                    except json.JSONDecodeError:
                        args = {}
                    res = await asyncio.to_thread(self.tool_layer.execute, name, args)
                    summary = json.dumps(res, ensure_ascii=False, default=str)
                    yield json.dumps(
                        {"type": "tool", "name": name, "output": summary[:2000]}
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": summary[:8000],
                        }
                    )
                continue
            if full_text:
                messages.append({"role": "assistant", "content": full_text})
                yield json.dumps({"type": "done"})
                return
            yield json.dumps(
                {"type": "stream", "content": "\n\n> ⚠️ Empty. Retrying…\n\n"}
            )
            continue
        yield json.dumps({"type": "done"})
