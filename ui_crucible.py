#!/usr/bin/env python3
"""
ui_crucible.py
RedTongue Crucible - Native PyQt6 Compiler Deck.
Compiles Python scripts into standalone executables via Nuitka.
English-only, optimized for low-RAM environments.
"""

import ast
import contextlib
import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from PyQt6.QtCore import QByteArray, QSettings, Qt, QThread, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QColor,
    QFont,
    QIcon,
    QPalette,
    QPixmap,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# =============================================================================
# THEME & CONSTANTS
# =============================================================================
C_BG = "#0d0d0d"
C_PANEL = "#121212"
C_INPUT = "#1a1a1a"
C_BORDER = "#222222"
C_RED = "#8b0000"
C_RED_HOVER = "#a52a2a"
C_WHITE = "#e0e0e0"
C_GRAY = "#888888"
C_SUCCESS = "#2ecc71"
C_ERROR = "#ff4444"

# Base64 encoded RedTongue logo (PNG)
LOGO_B64 = "iVBORw0KGgoAAAANSUhEUgAAAGAAAABgCAYAAADimHc4AAAACXBIWXMAAAsTAAALEwEAmpwYAAAB+0lEQVR4nO2du04DQRRFz0zGBhMTgxMT8QUTw0Ij0BgTgxMT8QUTwyJiwkagMTqJhYnFRMbGBhOTsBGTsBGTsI2NjS2Nf4nO3Tk7OzvbXf+8F3l3c3bvr5VyuZwzhJ2EhISEhISEhISEhISEhISEhISEhISEhISEhITkQOYD4CHQDqgFtgB3A0vcAt4BzWqV/wN/ASVAy3QNzAG1QD/wE2gCdYDzYD3wGzAd1AOjYBdwBfSrdIUYE2gGPgNLIAbYD2wQxXwlRyAu+AvUAW/AYaAZaAG2A8eBT8B6YD6wHFWwAF+B+uA5cAw0R51eAh3Aj8BSPRYetExOoD1OoT0+gBeYAi3AJbAH/ATj2QAPcRl2JJ3D/IlrKZ1uCcy7LfQJXtFqXgU+cdEN+Ar8ABVgMfgDvI4KZ0Q64BqqwQpUw5aB01TCvCdWSrnCdpBdwBHwb+S3/AQ+AyqJwFk4D5Wq0W3Mf1XN1V4A9Q8DPwNVAcZiQ7Bv4HSoDfQRf2Gf8Ql9T4Gd4/8vgj5j/ASSEhISEhISEhISEhISEhISEhISEhISEhISEhISA3IM8uen/Egnku1AAAAAElFTkSuQmCC"


# =============================================================================
# UTILITY & STYLING
# =============================================================================
def get_resource_path(filename):
    """Returns absolute path to resource file, handling PyInstaller bundled environments."""
    if "__compiled__" in globals() or hasattr(sys, "frozen"):
        local_path = Path(sys.executable).parent / filename
        if local_path.exists():
            return local_path
    base_path = Path(__file__).parent.resolve()
    return base_path / filename


def load_redtongue_logo(target_size=200):
    """Loads and scales the Crucible logo from resources."""
    local_logo = get_resource_path("crucible_logo.png")
    if local_logo.exists():
        pixmap = QPixmap(str(local_logo))
        if not pixmap.isNull():
            return pixmap.scaled(
                target_size,
                target_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
    pixmap = QPixmap()
    pixmap.loadFromData(QByteArray.fromBase64(LOGO_B64.encode()))
    return pixmap.scaled(
        target_size,
        target_size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"


class SectionCard(QFrame):
    def __init__(self, number, title, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setStyleSheet(f"border-left: 4px solid {C_RED}; border-radius: 4px;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        header_layout = QHBoxLayout()
        num_label = QLabel(str(number))
        num_label.setFixedSize(28, 28)
        num_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        num_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        num_label.setStyleSheet(
            f"background-color: {C_RED}; color: {C_WHITE}; border-radius: 14px;"
        )
        header_layout.addWidget(num_label)

        title_label = QLabel(title)
        title_label.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title_label.setStyleSheet(f"color: {C_WHITE};")
        header_layout.addWidget(title_label, 1)
        layout.addLayout(header_layout)

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(8)
        layout.addWidget(self.content)

    def addWidget(self, widget):
        self.content_layout.addWidget(widget)

    def addLayout(self, layout):
        self.content_layout.addLayout(layout)


class SmartLogOutput(QTextEdit):
    """Intelligent log display widget with syntax highlighting and auto-scroll."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(QFont("Consolas", 11))
        self.setReadOnly(True)
        # Build stylesheet with proper line breaks for PEP 8 compliance
        ss_edit = (
            f"QTextEdit {{ background-color: {C_INPUT}; color: {C_WHITE}; "
            f"border: 1px solid {C_BORDER}; border-radius: 4px; padding: 8px; }}\n"
            f"QScrollBar:vertical {{ background: {C_BG}; width: 8px; margin: 0px; }}\n"
            f"QScrollBar::handle:vertical {{ background: #333333; "
            f"border-radius: 4px; min-height: 20px; }}\n"
            f"QScrollBar::handle:vertical:hover {{ background: {C_RED}; }}\n"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical "
            "{{ height: 0px; }}"
        )
        self.setStyleSheet(ss_edit)

    def append_colored(self, text, color=None, bold=False):
        """Append colored text to log, auto-scrolling if at bottom."""
        scrollbar = self.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 20

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt = cursor.charFormat()
        fmt.setForeground(QColor(color if color else C_GRAY))
        fmt.setFontWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
        cursor.setCharFormat(fmt)
        cursor.insertText(text + "\n")

        if at_bottom:
            scrollbar.setValue(scrollbar.maximum())


class DataDropList(QListWidget):
    """List widget supporting drag-and-drop file operations."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.main_window = parent
        # Base stylesheet
        self._base_style = (
            f"QListWidget {{ background-color: {C_INPUT}; color: {C_WHITE}; "
            f"border: 1px solid {C_BORDER}; border-radius: 4px; "
            f"padding: 4px; font-size: 12px; }}\n"
            f"QListWidget::item:selected {{ background-color: {C_RED}; "
            f"color: {C_WHITE}; }}"
        )
        # Drag hover style
        self._hover_style = (
            f"QListWidget {{ background-color: {C_INPUT}; color: {C_WHITE}; "
            f"border: 2px dashed {C_RED}; border-radius: 4px; "
            f"padding: 4px; font-size: 12px; }}"
        )
        self.setStyleSheet(self._base_style)

    def dragEnterEvent(self, event):
        """Handle drag enter event with visual feedback."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(self._hover_style)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        """Restore base style on drag leave."""
        self.setStyleSheet(self._base_style)

    def dropEvent(self, event):
        """Handle file drop event."""
        self.setStyleSheet(self._base_style)
        if not self.main_window:
            return
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isfile(path):
                self.main_window.add_data_file(path)
            elif os.path.isdir(path):
                self.main_window.add_data_dir(path)


# =============================================================================
# WORKER THREAD
# =============================================================================
class NuitkaBuildThread(QThread):
    output = pyqtSignal(str, str)
    finished_build = pyqtSignal(bool, str, str)
    progress = pyqtSignal(int, str)

    def __init__(
        self, script_path, output_dir, python_exe, icon_path=None, options=None
    ):
        super().__init__()
        self.script_path = Path(script_path)
        self.output_dir = Path(output_dir)
        self.python_exe = python_exe
        self.icon_path = icon_path
        self.options = options or {}
        self.process = None
        self._kill = False

    def run(self):
        try:
            self.output.emit("=" * 60, "info")
            self.output.emit("RedTongue Crucible — Starting Build", "info")
            self.output.emit("=" * 60, "info")

            self.progress.emit(5, "Checking tools...")
            try:
                result = subprocess.run(
                    [self.python_exe, "-m", "nuitka", "--version"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode != 0:
                    self.output.emit("  ERROR: Nuitka is not available", "error")
                    self.finished_build.emit(False, "Nuitka not installed", "")
                    return
                version = result.stdout.strip().split("\n")[0]
                self.output.emit(f"  Nuitka version: {version}", "success")
            except FileNotFoundError as e:
                self.output.emit(f"  ERROR: Nuitka executable not found: {e}", "error")
                self.finished_build.emit(False, "Nuitka not installed", "")
                return
            except subprocess.TimeoutExpired as e:
                err_msg = f"  ERROR: Nuitka version check timed out: {e}"
                self.output.emit(err_msg, "error")
                self.finished_build.emit(False, "Nuitka check timeout", "")
                return

            self.progress.emit(10, "Preparing icon...")
            prepared_icon = self.prepare_icon() if self.icon_path else None
            if prepared_icon:
                self.output.emit("  Icon prepared.", "success")

            self.progress.emit(15, "Building instructions...")
            cmd = [self.python_exe, "-m", "nuitka", "--standalone", "--onefile"]

            if self.options.get("tkinter"):
                cmd.append("--enable-plugin=tk-inter")
            if self.options.get("pyqt6"):
                cmd.append("--enable-plugin=pyqt6")
            if self.options.get("lto"):
                cmd.append("--lto=yes")
            if self.options.get("remove_build"):
                cmd.append("--remove-output")

            jobs = self.options.get("jobs", 0)
            if jobs > 0:
                cmd.append(f"--jobs={jobs}")

            if prepared_icon:
                flag = (
                    "--windows-icon-from-ico"
                    if sys.platform == "win32"
                    else "--linux-icon"
                )
                cmd.append(f"{flag}={prepared_icon}")

            cmd.append(f"--output-dir={self.output_dir}")

            for data_spec in self.options.get("data_files", []):
                cmd.append(f"--include-data-files={data_spec}")
                self.output.emit(f"  Including file: {data_spec.split('=')[0]}", "info")

            for dir_spec in self.options.get("data_dirs", []):
                cmd.append(f"--include-data-dir={dir_spec}")
                self.output.emit(
                    f"  Including directory: {dir_spec.split('=')[0]}", "info"
                )

            if sys.platform == "win32":
                if self.options.get("app_name"):
                    cmd.append(f"--windows-product-name={self.options.get('app_name')}")
                if self.options.get("app_version"):
                    cmd.append(
                        f"--windows-product-version={self.options.get('app_version')}"
                    )
                if self.options.get("app_company"):
                    cmd.append(
                        f"--windows-company-name={self.options.get('app_company')}"
                    )
                if self.options.get("run_as_admin"):
                    cmd.append("--windows-uac-admin")

            for pkg in self.options.get("include_packages", []):
                cmd.append(f"--include-package={pkg}")
                self.output.emit(f"  Forcing include: {pkg}", "info")

            for pkg in self.options.get("exclude_packages", []):
                cmd.append(f"--nofollow-import-to={pkg}")
                self.output.emit(f"  Excluding module: {pkg}", "info")

            if self.options.get("follow_imports", True):
                cmd.append("--follow-imports")
            if sys.platform == "win32" and self.options.get("windowed", True):
                cmd.append("--windows-disable-console")

            if self.options.get("upx"):
                upx_binary = self.ensure_upx()
                if upx_binary:
                    cmd.append(f"--upx-binary={upx_binary}")
                    self.output.emit("  Using UPX for extra compression.", "success")
                else:
                    self.output.emit("  Skipping UPX compression.", "warning")

            cmd.append(str(self.script_path))
            self.output.emit(f"  CMD: {' '.join(cmd)}", "dim")
            self.output.emit("-" * 60, "dim")

            self.progress.emit(20, "Compiling executable...")
            kwargs = {}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                kwargs["start_new_session"] = True

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                cwd=str(self.output_dir),
                **kwargs,
            )

            for line in self.process.stdout:
                if self._kill:
                    break
                line = line.rstrip()
                if not line:
                    continue

                lower = line.lower()
                if "error" in lower or "failed" in lower:
                    level = "error"
                elif "warning" in lower:
                    level = "warning"
                elif "success" in lower or "created" in lower:
                    level = "success"
                else:
                    level = "dim"

                self.output.emit(f"  {line}", level)

                if "%" in line:
                    try:
                        pct = int(line.split("%")[0].strip().split()[-1])
                        self.progress.emit(max(20, min(pct, 95)), "Compiling...")
                    except (ValueError, IndexError):
                        pass

            if self._kill:
                self.output.emit("  BUILD CANCELLED BY USER", "error")
                self.finished_build.emit(False, "Build cancelled", "")
                return

            self.process.wait()
            self.progress.emit(95, "Finalizing...")

            if self.process.returncode == 0:
                exe_name = self.script_path.stem + (
                    ".exe" if sys.platform == "win32" else ""
                )
                found_exe = self.output_dir / exe_name
                if found_exe.exists():
                    size_str = format_size(found_exe.stat().st_size)
                    self.output.emit(f"  ✓ SUCCESS! Executable: {found_exe}", "success")
                    self.progress.emit(100, "Done!")
                    self.finished_build.emit(
                        True,
                        f"Executable: {found_exe}\nSize: {size_str}",
                        str(found_exe),
                    )
                else:
                    self.finished_build.emit(
                        True, str(self.output_dir), str(self.output_dir)
                    )
            else:
                self.output.emit(
                    f"  ✗ BUILD FAILED (code {self.process.returncode})", "error"
                )
                self.progress.emit(0, "Failed")
                self.finished_build.emit(
                    False, f"Nuitka exited with code {self.process.returncode}", ""
                )

        except subprocess.CalledProcessError as e:
            self.output.emit(f"  CRITICAL ERROR: Build process failed: {e!s}", "error")
            self.finished_build.emit(False, str(e), "")
        except FileNotFoundError as e:
            self.output.emit(f"  CRITICAL ERROR: Executable not found: {e!s}", "error")
            self.finished_build.emit(False, str(e), "")
        except TimeoutError as e:
            self.output.emit(f"  CRITICAL ERROR: Build timed out: {e!s}", "error")
            self.finished_build.emit(False, str(e), "")

    def ensure_upx(self):
        exe_name = "upx.exe" if sys.platform == "win32" else "upx"
        machine = platform.machine().lower()

        if sys.platform == "win32" and machine in {"amd64", "x86_64"}:
            url = "https://github.com/upx/upx/releases/download/v4.2.4/upx-4.2.4-win64.zip"
            platform_dir = "win64"
            expected_sha256 = (
                "22e9ef20e4c72aad85e32c71cbc9c086"
                "436c179456382aa75c0c24868456a671"
            )
        elif sys.platform in {"win32", "darwin"}:
            self.output.emit(
                "  Automatic UPX installation is unavailable on this platform.",
                "warning",
            )
            return None
        elif sys.platform.startswith("linux") and machine in {"amd64", "x86_64"}:
            url = "https://github.com/upx/upx/releases/download/v4.2.4/upx-4.2.4-amd64_linux.tar.xz"
            platform_dir = "linux-amd64"
            expected_sha256 = (
                "75cab4e57ab72fb4585ee45ff36388d2"
                "80c7afd72aa03e8d4b9c3cbddb474193"
            )
        else:
            self.output.emit(
                "  Automatic UPX installation is unavailable on this platform "
                "or CPU architecture.",
                "warning",
            )
            return None

        upx_dir = (
            Path.home() / ".redtongue_crucible" / "upx" / "v4.2.4" / platform_dir
        )
        verification_marker = upx_dir / ".verified_sha256"
        try:
            cache_verified = (
                verification_marker.read_text(encoding="ascii").strip()
                == expected_sha256
            )
        except OSError:
            cache_verified = False

        if cache_verified:
            for file in upx_dir.rglob(exe_name):
                return str(file)

        try:
            if upx_dir.is_symlink():
                upx_dir.unlink()
            else:
                shutil.rmtree(upx_dir, ignore_errors=True)
            upx_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.output.emit(f"  Failed to reset UPX cache: {e}", "warning")
            return None

        self.output.emit("  UPX requested. Downloading automatically...", "info")
        self.progress.emit(12, "Downloading UPX...")

        zip_path = upx_dir / "upx_download.zip"
        try:
            # Validate URL scheme to prevent SSRF
            parsed_url = urllib.parse.urlparse(url)
            if parsed_url.scheme not in ("https",):
                msg = f"Invalid URL scheme: {parsed_url.scheme}. Only HTTPS allowed."
                raise ValueError(msg)

            req = urllib.request.Request(
                url, headers={"User-Agent": "RedTongue Crucible"}
            )
            with (
                urllib.request.urlopen(req, timeout=30) as response,
                open(zip_path, "wb") as out_file,
            ):  # nosec B310 - URL scheme validated as HTTPS only
                archive_hash = hashlib.sha256()
                while chunk := response.read(1024 * 1024):
                    out_file.write(chunk)
                    archive_hash.update(chunk)

            if archive_hash.hexdigest() != expected_sha256:
                with contextlib.suppress(OSError):
                    zip_path.unlink()
                msg = "Downloaded UPX archive failed SHA-256 verification"
                raise ValueError(msg)

            self.output.emit("  Extracting UPX...", "info")
            if url.endswith(".zip"):
                with zipfile.ZipFile(zip_path, "r") as zip_ref:
                    # Validate paths before extraction
                    safe_members = []
                    upx_resolved = upx_dir.resolve()
                    for member in zip_ref.infolist():
                        member_path = (upx_dir / member.filename).resolve()
                        try:
                            member_path.relative_to(upx_resolved)
                        except ValueError:
                            msg = f"Unsafe path in archive: {member.filename}"
                            raise ValueError(msg)
                        safe_members.append(member)
                    zip_ref.extractall(upx_dir, members=safe_members)
            else:
                with tarfile.open(zip_path, "r:xz") as tar_ref:
                    # Validate members before extraction to prevent path traversal
                    safe_members = []
                    upx_resolved = upx_dir.resolve()
                    for member in tar_ref.getmembers():
                        # Skip dangerous members
                        if member.name.startswith("/") or ".." in member.name:
                            continue
                        # Additional safety: check resolved path
                        member_path = (upx_dir / member.name).resolve()
                        if not str(member_path).startswith(str(upx_resolved)):
                            continue
                        safe_members.append(member)
                    # Extract only validated members
                    tar_ref.extractall(upx_dir, members=safe_members, filter="data")
            os.remove(zip_path)

            for file in upx_dir.rglob(exe_name):
                if sys.platform != "win32":
                    # Set more restrictive permissions (owner read/write/execute only)
                    os.chmod(file, 0o700)
                verification_marker.write_text(expected_sha256, encoding="ascii")
                self.output.emit("  UPX installed successfully.", "success")
                return str(file)
        except urllib.error.URLError as e:
            err_msg = f"  Failed to download UPX: Network error - {e}"
            self.output.emit(err_msg, "warning")
            return None
        except zipfile.BadZipFile as e:
            err_msg = f"  Failed to download UPX: Corrupted archive - {e}"
            self.output.emit(err_msg, "warning")
            return None
        except tarfile.ReadError as e:
            err_msg = f"  Failed to extract UPX: Invalid tar file - {e}"
            self.output.emit(err_msg, "warning")
            return None
        except OSError as e:
            err_msg = f"  Failed to process UPX: File system error - {e}"
            self.output.emit(err_msg, "warning")
            return None
        except ValueError as e:
            err_msg = f"  Failed to process UPX: {e}"
            self.output.emit(err_msg, "warning")
            return None

    def prepare_icon(self):
        if not self.icon_path:
            return None
        source = Path(self.icon_path)
        if not source.exists():
            return None

        temp_dir = Path(tempfile.gettempdir()) / "redtongue_icons"
        temp_dir.mkdir(exist_ok=True)

        if sys.platform == "win32":
            if source.suffix.lower() == ".ico":
                return str(source)
            ico_path = temp_dir / f"{source.stem}_converted.ico"
            try:
                from PIL import Image

                img = Image.open(source)
                if img.mode != "RGBA":
                    img = img.convert("RGBA")
                img.save(
                    ico_path,
                    format="ICO",
                    sizes=[
                        (16, 16),
                        (32, 32),
                        (48, 48),
                        (64, 64),
                        (128, 128),
                        (256, 256),
                    ],
                )
                return str(ico_path)
            except OSError as e:
                err_msg = f"  Icon conversion failed: File system error - {e}"
                self.output.emit(err_msg, "warning")
                return None
            except ImportError as e:
                err_msg = f"  Icon conversion failed: Pillow not installed - {e}"
                self.output.emit(err_msg, "warning")
                return None
            except ValueError as e:
                err_msg = f"  Icon conversion failed: Invalid image format - {e}"
                self.output.emit(err_msg, "warning")
                return None
        else:
            if source.suffix.lower() == ".png":
                return str(source)
            png_path = temp_dir / f"{source.stem}_converted.png"
            try:
                from PIL import Image

                img = Image.open(source)
                img = img.convert("RGBA" if img.mode == "RGBA" else "RGB")
                img.save(png_path, "PNG")
                return str(png_path)
            except FileNotFoundError as e:
                err_msg = f"  Icon conversion failed: Image not found - {e}"
                self.output.emit(err_msg, "warning")
                return None
            except OSError as e:
                err_msg = f"  Icon conversion failed: Cannot read image - {e}"
                self.output.emit(err_msg, "warning")
                return None
            except ImportError as e:
                err_msg = f"  Icon conversion failed: Pillow not installed - {e}"
                self.output.emit(err_msg, "warning")
                return None
            except ValueError as e:
                err_msg = f"  Icon conversion failed: Unsupported image format - {e}"
                self.output.emit(err_msg, "warning")
                return None

    def cancel(self):
        self._kill = True
        if self.process:
            try:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                        check=False,
                        capture_output=True,
                    )
                else:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                time.sleep(0.5)
                if self.process.poll() is None:
                    self.process.kill()
            except (OSError, ProcessLookupError):
                # Process already terminated or doesn't exist
                pass
            except subprocess.SubprocessError:
                # Taskkill failed on Windows
                pass


# =============================================================================
# MAIN WINDOW
# =============================================================================
class CrucibleWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("RedTongue", "Crucible")
        self.setWindowTitle("RedTongue Crucible")
        self.setMinimumSize(1000, 1050)

        self.script_path = None
        self.icon_path = None
        self.build_thread = None
        self._last_exe_path = None
        self.data_files = []
        self.data_dirs = []

        self.setup_ui()
        self.setup_menubar()
        self.apply_theme()
        self.restore_state()

    def setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background-color: {C_BG}; }}"
        )

        container = QWidget()
        container.setStyleSheet(f"background-color: {C_BG};")
        scroll.setWidget(container)
        self.setCentralWidget(scroll)

        main_layout = QVBoxLayout(container)
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(24, 24, 24, 24)

        # Header
        header = QHBoxLayout()
        header.setSpacing(16)
        logo_label = QLabel()
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_label.setPixmap(load_redtongue_logo(120))
        header.addWidget(logo_label)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(4)
        title_layout.addStretch()
        title = QLabel("RedTongue Crucible")
        title.setFont(QFont("Segoe UI", 28, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C_WHITE};")
        title_layout.addWidget(title)
        subtitle = QLabel("Turn your Python script into a standalone App (.exe)")
        subtitle.setFont(QFont("Segoe UI", 14, QFont.Weight.Normal))
        subtitle.setStyleSheet(f"color: {C_RED};")
        title_layout.addWidget(subtitle)
        title_layout.addStretch()
        header.addLayout(title_layout, 1)
        main_layout.addLayout(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {C_BORDER}; border: none;")
        main_layout.addWidget(sep)

        # 1. Script & Environment
        script_card = SectionCard(1, "Choose Your Python Script")
        script_input_layout = QHBoxLayout()
        self.script_edit = QLineEdit()
        self.script_edit.setPlaceholderText(
            "Drag and drop your .py file here, or click Browse..."
        )
        self.script_edit.setReadOnly(True)
        self.script_edit.setMinimumHeight(40)
        self.script_edit.setStyleSheet(
            f"QLineEdit {{ background-color: {C_INPUT}; color: {C_WHITE}; border: 1px solid {C_BORDER}; border-radius: 4px; padding: 8px; font-size: 13px; }}"
        )
        self.script_edit.mousePressEvent = lambda e: self.browse_script()
        self.script_edit.setAcceptDrops(True)
        self.script_edit.dragEnterEvent = self.script_drag_enter
        self.script_edit.dropEvent = self.script_drop
        script_input_layout.addWidget(self.script_edit, 1)

        browse_btn = QPushButton("Browse")
        browse_btn.setMinimumHeight(40)
        browse_btn.setStyleSheet(
            f"QPushButton {{ background-color: {C_RED}; color: {C_WHITE}; border: none; border-radius: 4px; padding: 8px 16px; font-weight: bold; }} QPushButton:hover {{ background-color: {C_RED_HOVER}; }}"
        )
        browse_btn.clicked.connect(self.browse_script)
        script_input_layout.addWidget(browse_btn)
        script_card.addLayout(script_input_layout)

        env_layout = QHBoxLayout()
        env_label = QLabel("Python Environment:")
        env_label.setFont(QFont("Segoe UI", 12))
        env_label.setStyleSheet(f"color: {C_GRAY};")
        env_layout.addWidget(env_label)

        self.env_edit = QLineEdit()
        self.env_edit.setText(sys.executable)
        self.env_edit.setMinimumHeight(32)
        self.env_edit.setStyleSheet(
            f"QLineEdit {{ background-color: {C_INPUT}; color: {C_WHITE}; border: 1px solid {C_BORDER}; border-radius: 4px; padding: 6px; font-size: 12px; }}"
        )
        env_layout.addWidget(self.env_edit, 1)

        env_browse_btn = QPushButton("...")
        env_browse_btn.setFixedSize(32, 32)
        env_browse_btn.setToolTip(
            "Leave this as-is if unsure. Only change it if you use Virtual Environments (venv)."
        )
        env_browse_btn.setStyleSheet(
            f"QPushButton {{ background-color: {C_INPUT}; color: {C_WHITE}; border: 1px solid {C_BORDER}; border-radius: 4px; font-weight: bold; }} QPushButton:hover {{ border-color: {C_RED}; }}"
        )
        env_browse_btn.clicked.connect(self.browse_env)
        env_layout.addWidget(env_browse_btn)
        script_card.addLayout(env_layout)
        main_layout.addWidget(script_card)

        # 2. Icon
        icon_card = SectionCard(2, "Choose an App Icon (Optional)")
        icon_input_layout = QHBoxLayout()
        self.icon_edit = QLineEdit()
        self.icon_edit.setPlaceholderText(
            "Drag and drop an image here, or click Browse..."
        )
        self.icon_edit.setReadOnly(True)
        self.icon_edit.setMinimumHeight(40)
        self.icon_edit.setStyleSheet(
            f"QLineEdit {{ background-color: {C_INPUT}; color: {C_WHITE}; border: 1px solid {C_BORDER}; border-radius: 4px; padding: 8px; font-size: 13px; }}"
        )
        self.icon_edit.mousePressEvent = lambda e: self.browse_icon()
        self.icon_edit.setAcceptDrops(True)
        self.icon_edit.dragEnterEvent = self.icon_drag_enter
        self.icon_edit.dropEvent = self.icon_drop
        icon_input_layout.addWidget(self.icon_edit, 1)

        icon_browse_btn = QPushButton("Browse")
        icon_browse_btn.setMinimumHeight(40)
        icon_browse_btn.setStyleSheet(
            f"QPushButton {{ background-color: {C_INPUT}; color: {C_GRAY}; border: 1px solid {C_BORDER}; border-radius: 4px; padding: 8px 16px; font-weight: bold; }} QPushButton:hover {{ border-color: {C_RED}; color: {C_WHITE}; }}"
        )
        icon_browse_btn.clicked.connect(self.browse_icon)
        icon_input_layout.addWidget(icon_browse_btn)
        icon_card.addLayout(icon_input_layout)
        main_layout.addWidget(icon_card)

        # 3. Data Files & Folders
        data_card = SectionCard(3, "Include Extra Files & Folders (Optional)")
        data_layout = QHBoxLayout()
        self.data_list = DataDropList(self)
        self.data_list.setMinimumHeight(100)
        data_layout.addWidget(self.data_list, 1)

        data_btn_layout = QVBoxLayout()
        auto_scan_btn = QPushButton("✨ Auto-Scan Script")
        auto_scan_btn.setMinimumHeight(32)
        auto_scan_btn.setStyleSheet(
            f"QPushButton {{ background-color: {C_INPUT}; color: #4DA6FF; border: 1px solid #4DA6FF; border-radius: 4px; padding: 6px; font-weight: bold; }} QPushButton:hover {{ background-color: #4DA6FF; color: black; }}"
        )
        auto_scan_btn.clicked.connect(self.auto_scan_for_files)
        data_btn_layout.addWidget(auto_scan_btn)

        add_data_btn = QPushButton("Add File")
        add_data_btn.setMinimumHeight(32)
        add_data_btn.setStyleSheet(
            f"QPushButton {{ background-color: {C_INPUT}; color: {C_GRAY}; border: 1px solid {C_BORDER}; border-radius: 4px; padding: 6px; font-weight: bold; }} QPushButton:hover {{ border-color: {C_RED}; color: {C_WHITE}; }}"
        )
        add_data_btn.clicked.connect(lambda: self.add_data_file())
        data_btn_layout.addWidget(add_data_btn)

        add_dir_btn = QPushButton("Add Folder")
        add_dir_btn.setMinimumHeight(32)
        add_dir_btn.setStyleSheet(
            f"QPushButton {{ background-color: {C_INPUT}; color: {C_GRAY}; border: 1px solid {C_BORDER}; border-radius: 4px; padding: 6px; font-weight: bold; }} QPushButton:hover {{ border-color: {C_RED}; color: {C_WHITE}; }}"
        )
        add_dir_btn.clicked.connect(lambda: self.add_data_dir())
        data_btn_layout.addWidget(add_dir_btn)

        rm_data_btn = QPushButton("Remove")
        rm_data_btn.setMinimumHeight(32)
        rm_data_btn.setStyleSheet(
            f"QPushButton {{ background-color: {C_INPUT}; color: {C_GRAY}; border: 1px solid {C_BORDER}; border-radius: 4px; padding: 6px; font-weight: bold; }} QPushButton:hover {{ border-color: {C_ERROR}; color: {C_WHITE}; }}"
        )
        rm_data_btn.clicked.connect(self.remove_data_item)
        data_btn_layout.addWidget(rm_data_btn)

        copy_code_btn = QPushButton("Copy Helper Code")
        copy_code_btn.setMinimumHeight(32)
        copy_code_btn.setStyleSheet(
            f"QPushButton {{ background-color: {C_INPUT}; color: {C_SUCCESS}; border: 1px solid {C_SUCCESS}; border-radius: 4px; padding: 6px; font-weight: bold; }} QPushButton:hover {{ background-color: {C_SUCCESS}; color: black; }}"
        )
        copy_code_btn.clicked.connect(self.copy_helper_code)
        data_btn_layout.addWidget(copy_code_btn)
        data_btn_layout.addStretch()
        data_layout.addLayout(data_btn_layout)
        data_card.addLayout(data_layout)
        main_layout.addWidget(data_card)

        # 4. App Details & Advanced Modules
        meta_card = SectionCard(4, "App Details (Optional)")
        meta_layout = QGridLayout()
        meta_layout.setVerticalSpacing(8)
        meta_layout.setHorizontalSpacing(8)
        meta_layout.addWidget(QLabel("App Name:"), 0, 0)
        self.app_name_edit = QLineEdit()
        self.app_name_edit.setPlaceholderText("e.g., My Cool App")
        self.app_name_edit.setMinimumHeight(32)
        self.app_name_edit.setStyleSheet(
            f"QLineEdit {{ background-color: {C_INPUT}; color: {C_WHITE}; border: 1px solid {C_BORDER}; border-radius: 4px; padding: 6px; font-size: 12px; }}"
        )
        meta_layout.addWidget(self.app_name_edit, 0, 1)

        meta_layout.addWidget(QLabel("Version:"), 0, 2)
        self.app_version_edit = QLineEdit()
        self.app_version_edit.setPlaceholderText("e.g., 1.0.0")
        self.app_version_edit.setMinimumHeight(32)
        self.app_version_edit.setStyleSheet(self.app_name_edit.styleSheet())
        meta_layout.addWidget(self.app_version_edit, 0, 3)

        meta_layout.addWidget(QLabel("Company:"), 1, 0)
        self.app_company_edit = QLineEdit()
        self.app_company_edit.setPlaceholderText("e.g., RedTongue")
        self.app_company_edit.setMinimumHeight(32)
        self.app_company_edit.setStyleSheet(self.app_name_edit.styleSheet())
        meta_layout.addWidget(self.app_company_edit, 1, 1)

        meta_layout.addWidget(QLabel("Force Include:"), 1, 2)
        self.include_pkg_edit = QLineEdit()
        self.include_pkg_edit.setPlaceholderText("uvicorn, dotenv")
        self.include_pkg_edit.setMinimumHeight(32)
        self.include_pkg_edit.setStyleSheet(self.app_name_edit.styleSheet())
        meta_layout.addWidget(self.include_pkg_edit, 1, 3)

        meta_layout.addWidget(QLabel("Exclude:"), 2, 0)
        self.exclude_pkg_edit = QLineEdit()
        self.exclude_pkg_edit.setPlaceholderText("tkinter, unittest, pydoc")
        self.exclude_pkg_edit.setMinimumHeight(32)
        self.exclude_pkg_edit.setStyleSheet(self.app_name_edit.styleSheet())
        meta_layout.addWidget(self.exclude_pkg_edit, 2, 1)
        meta_card.addLayout(meta_layout)
        main_layout.addWidget(meta_card)

        # 5. Build Options
        options_card = SectionCard(5, "App Settings")
        adv_layout = QVBoxLayout()
        self.pyqt_check = QCheckBox("My app is a Desktop GUI (PyQt6)")
        self.pyqt_check.setFont(QFont("Segoe UI", 12))
        self.pyqt_check.setStyleSheet(
            f"QCheckBox {{ color: {C_WHITE}; spacing: 8px; padding: 4px; }} QCheckBox::indicator {{ width: 18px; height: 18px; border: 1px solid {C_BORDER}; border-radius: 3px; background: {C_INPUT}; }} QCheckBox::indicator:checked {{ background: {C_RED}; border-color: {C_RED}; }}"
        )
        adv_layout.addWidget(self.pyqt_check)

        self.tk_check = QCheckBox("My app uses Tkinter")
        self.tk_check.setFont(QFont("Segoe UI", 12))
        self.tk_check.setStyleSheet(self.pyqt_check.styleSheet())
        adv_layout.addWidget(self.tk_check)

        self.lto_check = QCheckBox("Make App Smaller & Faster (Takes longer to build)")
        self.lto_check.setChecked(True)
        self.lto_check.setFont(QFont("Segoe UI", 12))
        self.lto_check.setStyleSheet(self.pyqt_check.styleSheet())
        adv_layout.addWidget(self.lto_check)

        self.upx_check = QCheckBox("Compress App Extra Small (Auto-downloads UPX)")
        self.upx_check.setFont(QFont("Segoe UI", 12))
        self.upx_check.setStyleSheet(self.pyqt_check.styleSheet())
        adv_layout.addWidget(self.upx_check)

        self.admin_check = QCheckBox("Run App as Administrator (Requires UAC prompt)")
        self.admin_check.setFont(QFont("Segoe UI", 12))
        self.admin_check.setStyleSheet(self.pyqt_check.styleSheet())
        adv_layout.addWidget(self.admin_check)
        options_card.addLayout(adv_layout)

        sys_layout = QHBoxLayout()
        sys_label = QLabel("Build Speed (CPU Cores):")
        sys_label.setFont(QFont("Segoe UI", 12))
        sys_label.setStyleSheet(f"color: {C_GRAY};")
        sys_layout.addWidget(sys_label)

        self.threads_spin = QSpinBox()
        self.threads_spin.setMinimum(0)
        self.threads_spin.setMaximum(64)
        self.threads_spin.setValue(0)
        self.threads_spin.setFixedHeight(32)
        self.threads_spin.setStyleSheet(
            f"QSpinBox {{ background-color: {C_INPUT}; color: {C_WHITE}; border: 1px solid {C_BORDER}; border-radius: 4px; padding: 4px; font-size: 12px; }}"
        )
        sys_layout.addWidget(self.threads_spin)
        sys_layout.addStretch()
        options_card.addLayout(sys_layout)
        main_layout.addWidget(options_card)

        # Build Button
        self.build_btn = QPushButton("  BUILD MY APP NOW  ")
        self.build_btn.setMinimumHeight(50)
        self.build_btn.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        self.build_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.build_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {C_RED}; color: {C_WHITE}; border: none; border-radius: 4px; }}
            QPushButton:hover {{ background-color: {C_RED_HOVER}; }}
            QPushButton:pressed {{ background-color: #660000; }}
            QPushButton:disabled {{ background-color: #333333; color: #666666; }}
        """)
        self.build_btn.clicked.connect(self.start_build)
        main_layout.addWidget(self.build_btn)

        self.progress = QProgressBar()
        self.progress.setMinimumHeight(24)
        self.progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress.setStyleSheet(f"""
            QProgressBar {{ background-color: {C_INPUT}; color: {C_WHITE}; border: 1px solid {C_BORDER}; border-radius: 4px; text-align: center; font-size: 12px; font-weight: bold; }}
            QProgressBar::chunk {{ background-color: {C_RED}; border-radius: 4px; }}
        """)
        main_layout.addWidget(self.progress)

        # Log
        log_card = SectionCard(6, "Build Log (What's happening behind the scenes)")
        self.log_output = SmartLogOutput()
        self.log_output.setMinimumHeight(150)
        log_card.addWidget(self.log_output)
        main_layout.addWidget(log_card, 1)

        self.log("RedTongue Crucible is ready.", "info")

    def auto_scan_for_files(self):
        if not self.script_path:
            QMessageBox.warning(
                self,
                "Hold On!",
                "You forgot to choose a Python script first. Please drag and drop your .py file into Step 1.",
            )
            return

        script_dir = Path(self.script_path).parent
        found_files = 0
        try:
            with open(self.script_path, encoding="utf-8") as f:
                file_content = f.read()
            tree = ast.parse(file_content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    val = node.value
                    if "." in val and len(val) < 100 and not val.startswith("http"):
                        clean_val = val.replace("\\", "/").split("/")[-1]
                        if clean_val.endswith(".py"):
                            continue
                        potential_path = script_dir / clean_val
                        if potential_path.exists() and potential_path.is_file():
                            spec = f"{potential_path}={clean_val}"
                            if spec not in self.data_files:
                                self.data_files.append(spec)
                                self.data_list.addItem(
                                    f"[File]  {clean_val} (Auto-scanned)"
                                )
                                found_files += 1
            if found_files > 0:
                self.log(
                    f"  ✨ Auto-Scan found {found_files} missing data file(s)!",
                    "success",
                )
            else:
                self.log("  Auto-Scan finished. No new data files found.", "info")
        except SyntaxError:
            QMessageBox.warning(self, "Scan Failed", "Syntax Error in script.")
        except FileNotFoundError:
            QMessageBox.warning(self, "Scan Failed", "Script file not found.")
        except PermissionError:
            QMessageBox.warning(
                self, "Scan Failed", "Permission denied reading script."
            )
        except UnicodeDecodeError:
            QMessageBox.warning(
                self, "Scan Failed", "Script contains invalid characters."
            )

    def copy_helper_code(self):
        snippet = """import sys
from pathlib import Path
def get_resource_path(filename):
    if "__compiled__" in globals() or hasattr(sys, "frozen"):
        base_path = Path(sys.executable).parent
    else:
        base_path = Path(__file__).parent.resolve()
    return base_path / filename
"""
        QApplication.clipboard().setText(snippet)
        QMessageBox.information(
            self, "Code Copied!", "Paste this at the top of your script."
        )

    def save_profile(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Build Profile", "", "Crucible Profile (*.crucible)"
        )
        if not path:
            return
        profile = {
            "script": self.script_path,
            "icon": self.icon_path,
            "env": self.env_edit.text(),
            "app_name": self.app_name_edit.text(),
            "app_version": self.app_version_edit.text(),
            "app_company": self.app_company_edit.text(),
            "include_pkg": self.include_pkg_edit.text(),
            "exclude_pkg": self.exclude_pkg_edit.text(),
            "pyqt": self.pyqt_check.isChecked(),
            "tk": self.tk_check.isChecked(),
            "lto": self.lto_check.isChecked(),
            "upx": self.upx_check.isChecked(),
            "admin": self.admin_check.isChecked(),
            "threads": self.threads_spin.value(),
            "data_files": self.data_files,
            "data_dirs": self.data_dirs,
        }
        with open(path, "w") as f:
            json.dump(profile, f, indent=4)
        self.log(f"  Profile saved to {path}", "success")

    def load_profile(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Build Profile", "", "Crucible Profile (*.crucible)"
        )
        if not path:
            return
        with open(path) as f:
            profile = json.load(f)
        if profile.get("script"):
            self.set_script_path(profile["script"])
        if profile.get("icon"):
            self.set_icon_path(profile["icon"])
        self.env_edit.setText(profile.get("env", sys.executable))
        self.app_name_edit.setText(profile.get("app_name", ""))
        self.app_version_edit.setText(profile.get("app_version", ""))
        self.app_company_edit.setText(profile.get("app_company", ""))
        self.include_pkg_edit.setText(profile.get("include_pkg", ""))
        self.exclude_pkg_edit.setText(profile.get("exclude_pkg", ""))
        self.pyqt_check.setChecked(profile.get("pyqt", False))
        self.tk_check.setChecked(profile.get("tk", False))
        self.lto_check.setChecked(profile.get("lto", True))
        self.upx_check.setChecked(profile.get("upx", False))
        self.admin_check.setChecked(profile.get("admin", False))
        self.threads_spin.setValue(profile.get("threads", 0))
        self.data_files = profile.get("data_files", [])
        self.data_dirs = profile.get("data_dirs", [])
        self.data_list.clear()
        for d in self.data_files:
            self.data_list.addItem(f"[File]  {d.split('=')[1] if '=' in d else d}")
        for d in self.data_dirs:
            self.data_list.addItem(f"[Dir]   {d.split('=')[1] if '=' in d else d}")

    def check_and_install_nuitka(self):
        try:
            result = subprocess.run(
                [self.env_edit.text(), "-m", "nuitka", "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                return True
        except (
            FileNotFoundError,
            subprocess.TimeoutExpired,
            subprocess.SubprocessError,
        ):
            pass

        reply = QMessageBox.question(
            self,
            "Missing Tool",
            "Nuitka (the engine that compiles your app) is not installed in the selected Python environment. Would you like Crucible to install it for you automatically?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                subprocess.run(
                    [self.env_edit.text(), "-m", "pip", "install", "nuitka"], check=True
                )
                return True
            except (subprocess.CalledProcessError, FileNotFoundError, TimeoutError):
                return False
        return False

    def browse_env(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select python.exe",
            "",
            "python.exe" if sys.platform == "win32" else "All Files (*)",
        )
        if path:
            self.env_edit.setText(path)

    def add_data_file(self, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Select File")
        if path:
            spec = f"{path}={Path(path).name}"
            self.data_files.append(spec)
            self.data_list.addItem(f"[File]  {Path(path).name}")

    def add_data_dir(self, path=None):
        if path is None:
            path = QFileDialog.getExistingDirectory(self, "Select Folder")
        if path:
            spec = f"{path}={Path(path).name}"
            self.data_dirs.append(spec)
            self.data_list.addItem(f"[Dir]   {Path(path).name}")

    def remove_data_item(self):
        for item in self.data_list.selectedItems():
            row = self.data_list.row(item)
            self.data_list.takeItem(row)
            if item.text().startswith("[File]"):
                self.data_files.pop(row)
            else:
                self.data_dirs.pop(row)

    def script_drag_enter(self, event):
        if event.mimeData().hasUrls() and event.mimeData().urls()[
            0
        ].toLocalFile().endswith(".py"):
            event.acceptProposedAction()

    def script_drop(self, event):
        self.set_script_path(event.mimeData().urls()[0].toLocalFile())

    def icon_drag_enter(self, event):
        if event.mimeData().hasUrls() and event.mimeData().urls()[
            0
        ].toLocalFile().lower().endswith((".png", ".jpg", ".jpeg", ".ico")):
            event.acceptProposedAction()

    def icon_drop(self, event):
        self.set_icon_path(event.mimeData().urls()[0].toLocalFile())

    def browse_script(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose Your Python Script", "", "Python (*.py)"
        )
        if path:
            self.set_script_path(path)

    def browse_icon(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose an App Icon", "", "Images (*.png *.jpg *.jpeg *.ico)"
        )
        if path:
            self.set_icon_path(path)

    def set_script_path(self, path):
        self.script_path = path
        self.script_edit.setText(path)
        if not self.app_name_edit.text():
            self.app_name_edit.setText(Path(path).stem.replace("_", " ").title())

    def set_icon_path(self, path):
        self.icon_path = path
        self.icon_edit.setText(path)

    def start_build(self):
        if not self.script_path:
            QMessageBox.warning(
                self,
                "Hold On!",
                "You forgot to choose a Python script first. Please drag and drop your .py file into Step 1.",
            )
            return

        if not self.check_and_install_nuitka():
            return

        include_pkgs = (
            [p.strip() for p in self.include_pkg_edit.text().split(",") if p.strip()]
            if self.include_pkg_edit.text().strip()
            else []
        )
        exclude_pkgs = (
            [p.strip() for p in self.exclude_pkg_edit.text().split(",") if p.strip()]
            if self.exclude_pkg_edit.text().strip()
            else []
        )

        options = {
            "pyqt6": self.pyqt_check.isChecked(),
            "tkinter": self.tk_check.isChecked(),
            "lto": self.lto_check.isChecked(),
            "upx": self.upx_check.isChecked(),
            "remove_build": True,
            "jobs": self.threads_spin.value(),
            "data_files": self.data_files,
            "data_dirs": self.data_dirs,
            "app_name": self.app_name_edit.text().strip(),
            "app_version": self.app_version_edit.text().strip(),
            "app_company": self.app_company_edit.text().strip(),
            "include_packages": include_pkgs,
            "exclude_packages": exclude_pkgs,
            "run_as_admin": self.admin_check.isChecked(),
        }

        self.build_btn.setEnabled(False)
        self.build_btn.setText("  BUILDING... (Click to Cancel)  ")
        self.progress.setValue(0)

        with contextlib.suppress(TypeError):
            self.build_btn.clicked.disconnect()
        self.build_btn.clicked.connect(self.cancel_build)

        self.build_thread = NuitkaBuildThread(
            self.script_path,
            str(Path(self.script_path).parent),
            self.env_edit.text(),
            self.icon_path,
            options,
        )
        self.build_thread.output.connect(self.log)
        self.build_thread.progress.connect(self.progress.setValue)
        self.build_thread.finished_build.connect(self.build_finished)
        self.build_thread.start()

    def cancel_build(self):
        if self.build_thread and self.build_thread.isRunning():
            self.build_thread.cancel()

    def build_finished(self, success, message, exe_path):
        self.build_btn.setEnabled(True)
        self.build_btn.setText("  BUILD MY APP NOW  ")
        with contextlib.suppress(TypeError):
            self.build_btn.clicked.disconnect()
        self.build_btn.clicked.connect(self.start_build)

        if success:
            self.progress.setValue(100)
            self.log(f"  ✓ {message}", "success")
            if exe_path:
                self._last_exe_path = exe_path
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle("Success!")
                msg_box.setText(f"Your app was built successfully!\n{message}")
                open_btn = msg_box.addButton(
                    "Open Folder", QMessageBox.ButtonRole.AcceptRole
                )
                test_btn = msg_box.addButton(
                    "Test App Now", QMessageBox.ButtonRole.AcceptRole
                )
                msg_box.addButton("Close", QMessageBox.ButtonRole.RejectRole)
                msg_box.exec()

                if msg_box.clickedButton() == open_btn:
                    self.open_folder(exe_path)
                elif msg_box.clickedButton() == test_btn:
                    self.test_app(exe_path)
        else:
            self.log(f"  ✗ {message}", "error")
            self.progress.setValue(0)
            QMessageBox.critical(
                self,
                "Build Failed",
                "Oops! Something went wrong during the build.\nCheck the log below to see what happened.\nTip: If a module is missing, try typing its name in the 'Force Include Modules' box.",
            )

    def test_app(self, path):
        if path and Path(path).exists():
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen([path])

    def open_folder(self, path):
        folder = str(Path(path).parent)
        if sys.platform == "win32":
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])

    def log(self, message, level="info"):
        colors = {
            "info": C_WHITE,
            "dim": C_GRAY,
            "success": C_SUCCESS,
            "warning": "#ffaa00",
            "error": C_ERROR,
        }
        self.log_output.append_colored(message, colors.get(level, C_WHITE))

    def setup_menubar(self):
        menubar = self.menuBar()
        menubar.setStyleSheet(
            f"QMenuBar {{ background-color: {C_BG}; color: {C_WHITE}; font-size: 13px; }} QMenuBar::item:selected {{ background: {C_RED}; }}"
        )

        file_menu = menubar.addMenu("&File")
        save_profile_action = QAction("Save Build Profile", self)
        save_profile_action.triggered.connect(self.save_profile)
        file_menu.addAction(save_profile_action)

        load_profile_action = QAction("Load Build Profile", self)
        load_profile_action.triggered.connect(self.load_profile)
        file_menu.addAction(load_profile_action)

        file_menu.addSeparator()
        clear_action = QAction("Clear Log", self)
        clear_action.triggered.connect(self.log_output.clear)
        file_menu.addAction(clear_action)

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    def apply_theme(self):
        self.setStyleSheet(
            f"QMainWindow, QWidget {{ background-color: {C_BG}; color: {C_WHITE}; font-family: 'Segoe UI'; }}"
        )
        self.setWindowIcon(QIcon(load_redtongue_logo(64)))

    def save_state(self):
        self.settings.setValue("window/geometry", self.saveGeometry())

    def restore_state(self):
        geometry = self.settings.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            screen = QApplication.primaryScreen().geometry()
            self.move(
                (screen.width() - self.width()) // 2,
                (screen.height() - self.height()) // 2,
            )

    def closeEvent(self, event):
        if self.build_thread and self.build_thread.isRunning():
            reply = QMessageBox.question(
                self,
                "Build Running",
                "Cancel and quit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.build_thread.cancel()
                self.build_thread.wait(2000)
                self.save_state()
                event.accept()
            else:
                event.ignore()
        else:
            self.save_state()
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("RedTongue Crucible")
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(C_BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(C_WHITE))
    palette.setColor(QPalette.ColorRole.Base, QColor(C_INPUT))
    palette.setColor(QPalette.ColorRole.Text, QColor(C_WHITE))
    palette.setColor(QPalette.ColorRole.Button, QColor(C_INPUT))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(C_WHITE))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(C_RED))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(C_WHITE))
    app.setPalette(palette)

    window = CrucibleWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
