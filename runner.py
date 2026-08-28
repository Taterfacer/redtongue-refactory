#!/usr/bin/env python3
"""
runner.py
Cross-platform sandbox execution engine for the RedTongue Refactory.
Executes untrusted Python code with strict resource limits (CPU, Memory, Time).
Uses native OS primitives (rlimits on Linux, Process Groups on Windows) and
psutil for robust process tree termination.
Optimized for low-RAM (8GB) environments to prevent OOM crashes.
"""

import contextlib
import logging
import os
import subprocess
import sys
from pathlib import Path

try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

logger = logging.getLogger("RedTongue.Runner")

# ==============================================================================
# CONSTANTS & LIMITS
# ==============================================================================
DEFAULT_TIMEOUT = 60
DEFAULT_MEMORY_LIMIT_MB = 512
DEFAULT_CPU_TIME_LIMIT = 30
MAX_OUTPUT_SIZE = 100_000


# ==============================================================================
# LINUX RESOURCE LIMITS
# ==============================================================================
def _linux_set_limits(memory_limit_mb: int, cpu_time_limit: int):
    """
    Sets resource limits for the child process on Linux.
    Must be called via preexec_fn in subprocess.Popen.
    """
    import resource

    # Memory limit (RLIMIT_AS sets the maximum size of the process's virtual memory)
    mem_bytes = memory_limit_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))

    # CPU time limit (seconds)
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_time_limit, cpu_time_limit + 2))

    # File size limit (prevent disk filling) - 50MB
    resource.setrlimit(resource.RLIMIT_FSIZE, (50 * 1024 * 1024, 50 * 1024 * 1024))

    # Create a new process group to isolate signals
    os.setsid()


# ==============================================================================
# PROCESS TREE MANAGEMENT
# ==============================================================================
def kill_process_tree(pid: int, timeout: float = 3.0) -> bool:
    """
    Kills a process and all its children.
    Cross-platform implementation using psutil.
    """
    if not HAS_PSUTIL:
        logger.warning("psutil not available. Cannot kill process tree safely.")
        return False

    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)

        # Terminate children first
        for child in children:
            with contextlib.suppress(psutil.NoSuchProcess):
                child.terminate()

        # Terminate parent
        with contextlib.suppress(psutil.NoSuchProcess):
            parent.terminate()

        # Wait for graceful shutdown
        gone, alive = psutil.wait_procs(children + [parent], timeout=timeout)

        # Force kill survivors
        for p in alive:
            with contextlib.suppress(psutil.NoSuchProcess):
                p.kill()

        return True
    except Exception as e:
        logger.error(f"Failed to kill process tree {pid}: {e}")
        return False


# ==============================================================================
# SANDBOX RUNNER
# ==============================================================================
class SandboxRunner:
    """
    Executes Python scripts in a controlled environment.
    Handles timeouts, memory limits, and output truncation.
    """

    def __init__(
        self,
        workspace: str,
        timeout: int = DEFAULT_TIMEOUT,
        memory_limit_mb: int = DEFAULT_MEMORY_LIMIT_MB,
        cpu_time_limit: int = DEFAULT_CPU_TIME_LIMIT,
    ):
        self.workspace = Path(workspace).resolve()
        self.timeout = timeout
        self.memory_limit_mb = memory_limit_mb
        self.cpu_time_limit = cpu_time_limit

    def execute(self, script_path: str) -> dict:
        """
        Executes a Python script and returns a result dictionary.

        Returns:
            dict: {
                "status": "success" | "error" | "timeout" | "oom",
                "output": str,
                "returncode": int,
                "killed": bool
            }
        """
        script = Path(script_path).resolve()

        # Security: Ensure script is within workspace
        try:
            script.relative_to(self.workspace)
        except ValueError:
            return {
                "status": "error",
                "output": "Security Error: Script is outside the workspace.",
                "returncode": -1,
                "killed": False,
            }

        if not script.exists() or not script.is_file():
            return {
                "status": "error",
                "output": f"File not found: {script_path}",
                "returncode": -1,
                "killed": False,
            }

        cmd = [sys.executable, "-u", str(script)]

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "cwd": str(self.workspace),
            "env": env,
            "bufsize": 1,
            "universal_newlines": True,
        }

        # Platform-specific setup
        preexec_fn = None
        creationflags = 0

        if sys.platform != "win32":

            def _set_limits() -> None:
                _linux_set_limits(self.memory_limit_mb, self.cpu_time_limit)

            preexec_fn = _set_limits
            kwargs["preexec_fn"] = preexec_fn
        else:
            # Windows: Create new process group, no console window
            creationflags = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            )
            kwargs["creationflags"] = creationflags

        proc = None
        killed = False
        status = "success"

        try:
            proc = subprocess.Popen(cmd, **kwargs)

            try:
                stdout, _ = proc.communicate(timeout=self.timeout)
                returncode = proc.returncode

                # Check for OOM on Linux (signal 9 / SIGKILL often means OOM killer)
                if returncode == -9 and sys.platform != "win32":
                    status = "oom"
                elif returncode != 0:
                    status = "error"

            except subprocess.TimeoutExpired:
                status = "timeout"
                killed = True
                kill_process_tree(proc.pid)
                stdout = f"[TIMEOUT] Process exceeded {self.timeout}s limit and was terminated.\n"
                returncode = -1

        except Exception as e:
            status = "error"
            stdout = f"[SYSTEM ERROR] {e!s}\n"
            returncode = -1

        # Truncate massive outputs to prevent UI freeze
        if stdout and len(stdout) > MAX_OUTPUT_SIZE:
            stdout = (
                stdout[:MAX_OUTPUT_SIZE]
                + "\n\n[OUTPUT TRUNCATED: Exceeded 100,000 characters]"
            )

        return {
            "status": status,
            "output": stdout or "(no output)",
            "returncode": returncode,
            "killed": killed,
        }

    def execute_inline(self, code: str) -> dict:
        """
        Executes a string of Python code by writing it to a temporary file.
        Useful for quick AI-generated snippets.
        """
        import tempfile

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".py",
                delete=False,
                dir=str(self.workspace),
                encoding="utf-8",
            ) as tmp:
                tmp.write(code)
                tmp_path = tmp.name

            return self.execute(tmp_path)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
