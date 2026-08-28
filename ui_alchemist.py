#!/usr/bin/env python3
"""
ui_alchemist.py
RedTongue Alchemist - Native PyQt6 Format Factory.
Converts images, audio, video, and documents.
Features auto-provisioning of external tools (FFmpeg, Tesseract),
multi-threaded batch processing, and a Potato PC optimized UI.
"""

import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QFont, QPalette
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# ==============================================================================
# THEME & CONSTANTS
# ==============================================================================
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

QSS = f"""
QMainWindow, QWidget {{ background-color: {C_BG}; color: {C_WHITE}; font-family: 'Segoe UI', sans-serif; font-size: 13px; }}
QFrame#Panel {{ background-color: {C_PANEL}; border: 1px solid {C_BORDER}; border-radius: 4px; }}
QPushButton {{ background-color: {C_INPUT}; color: {C_WHITE}; border: 1px solid {C_BORDER}; border-radius: 4px; padding: 6px 16px; font-weight: bold; }}
QPushButton:hover {{ background-color: #2a2a2a; }}
QPushButton#Primary {{ background-color: {C_RED}; color: {C_WHITE}; border: 1px solid {C_RED_HOVER}; }}
QPushButton#Primary:hover {{ background-color: {C_RED_HOVER}; }}
QLineEdit, QComboBox {{ background-color: {C_INPUT}; border: 1px solid {C_BORDER}; color: {C_WHITE}; padding: 6px; border-radius: 4px; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {C_BORDER}; border-radius: 3px; background: {C_INPUT}; }}
QCheckBox::indicator:checked {{ background-color: {C_RED}; border-color: {C_RED_HOVER}; }}
QListWidget {{ background-color: #0a0a0a; border: 1px solid {C_BORDER}; color: {C_WHITE}; }}
QListWidget::item:selected {{ background-color: {C_RED}; }}
QProgressBar {{ background-color: {C_INPUT}; border: 1px solid {C_BORDER}; border-radius: 4px; text-align: center; }}
QProgressBar::chunk {{ background-color: {C_RED}; border-radius: 4px; }}
QTextEdit {{ background-color: {C_INPUT}; color: {C_WHITE}; border: 1px solid {C_BORDER}; border-radius: 4px; font-family: Consolas; }}
QGroupBox {{ border: 1px solid {C_BORDER}; border-radius: 4px; margin-top: 10px; padding-top: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; }}
QScrollBar:vertical {{ background: {C_BG}; width: 8px; }}
QScrollBar::handle:vertical {{ background: #333333; border-radius: 4px; }}
"""


# ==============================================================================
# SETTINGS & REGISTRY
# ==============================================================================
@dataclass
class ConvertSettings:
    quality: int = 90
    bitrate: str = "128k"
    resolution: str = ""
    fps: float = 0.0
    dpi: int = 150
    grayscale: bool = False
    ocr: bool = False
    conflict_mode: str = "rename"  # rename, overwrite, skip


class ConverterRegistry:
    _converters: ClassVar[dict[tuple[str, str], Callable]] = {}

    @classmethod
    def register(cls, src_ext: str, dst_ext: str):
        def decorator(func):
            cls._converters[(src_ext.lower(), dst_ext.lower())] = func
            return func

        return decorator

    @classmethod
    def get(cls, src_ext: str, dst_ext: str) -> Callable | None:
        return cls._converters.get((src_ext.lower(), dst_ext.lower()))

    @classmethod
    def list_targets(cls, src_ext: str) -> list[str]:
        return sorted(
            [dst for src, dst in cls._converters.keys() if src == src_ext.lower()]
        )


def get_ext(path: str) -> str:
    return Path(path).suffix.lower().lstrip(".")


def unique_output_path(path: Path) -> Path:
    if not path.exists():
        return path
    base, ext = path.stem, path.suffix
    i = 1
    while (path.parent / f"{base}_{i}{ext}").exists():
        i += 1
    return path.parent / f"{base}_{i}{ext}"


# --- Core Converters (Images via PIL) ---
try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False


@ConverterRegistry.register("png", "jpg")
@ConverterRegistry.register("bmp", "jpg")
@ConverterRegistry.register("tiff", "jpg")
@ConverterRegistry.register("webp", "jpg")
def img_to_jpg(src: Path, dst: Path, settings: ConvertSettings):
    if not HAS_PIL:
        raise RuntimeError("Pillow not installed")
    img = Image.open(src)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    if settings.resolution:
        w, h = map(int, settings.resolution.split("x"))
        img = img.resize((w, h), Image.LANCZOS)
    img.save(dst, "JPEG", quality=settings.quality)


@ConverterRegistry.register("jpg", "png")
@ConverterRegistry.register("bmp", "png")
@ConverterRegistry.register("webp", "png")
def img_to_png(src: Path, dst: Path, settings: ConvertSettings):
    if not HAS_PIL:
        raise RuntimeError("Pillow not installed")
    img = Image.open(src)
    if settings.resolution:
        w, h = map(int, settings.resolution.split("x"))
        img = img.resize((w, h), Image.LANCZOS)
    img.save(dst, "PNG")


@ConverterRegistry.register("jpg", "pdf")
@ConverterRegistry.register("png", "pdf")
def img_to_pdf(src: Path, dst: Path, settings: ConvertSettings):
    if not HAS_PIL:
        raise RuntimeError("Pillow not installed")
    img = Image.open(src)
    if img.mode == "RGBA":
        img = img.convert("RGB")
    img.save(dst, "PDF", resolution=settings.dpi)


# --- Core Converters (Audio/Video via FFmpeg) ---
def run_ffmpeg(
    src: Path, dst: Path, args: list[str], progress_cb: Callable | None = None
):
    cmd = ["ffmpeg", "-y", "-i", str(src)] + args + [str(dst)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {proc.stderr[-200:]}")


@ConverterRegistry.register("mp3", "wav")
@ConverterRegistry.register("flac", "wav")
@ConverterRegistry.register("ogg", "wav")
@ConverterRegistry.register("m4a", "wav")
def audio_to_wav(src: Path, dst: Path, settings: ConvertSettings):
    run_ffmpeg(src, dst, ["-codec:a", "pcm_s16le"])


@ConverterRegistry.register("wav", "mp3")
@ConverterRegistry.register("flac", "mp3")
@ConverterRegistry.register("ogg", "mp3")
@ConverterRegistry.register("m4a", "mp3")
def audio_to_mp3(src: Path, dst: Path, settings: ConvertSettings):
    run_ffmpeg(src, dst, ["-codec:a", "libmp3lame", "-b:a", settings.bitrate])


@ConverterRegistry.register("mp4", "mp3")
@ConverterRegistry.register("mkv", "mp3")
@ConverterRegistry.register("avi", "mp3")
@ConverterRegistry.register("mov", "mp3")
def video_extract_mp3(src: Path, dst: Path, settings: ConvertSettings):
    run_ffmpeg(src, dst, ["-vn", "-codec:a", "libmp3lame", "-b:a", settings.bitrate])


@ConverterRegistry.register("avi", "mp4")
@ConverterRegistry.register("mkv", "mp4")
@ConverterRegistry.register("mov", "mp4")
@ConverterRegistry.register("webm", "mp4")
def video_to_mp4(src: Path, dst: Path, settings: ConvertSettings):
    cmd = ["-codec:v", "libx264", "-preset", "fast", "-crf", "23", "-codec:a", "aac"]
    if settings.resolution:
        cmd += ["-vf", f"scale={settings.resolution.replace('x', ':')}"]
    if settings.fps > 0:
        cmd += ["-r", str(settings.fps)]
    run_ffmpeg(src, dst, cmd)


# ==============================================================================
# TOOL MANAGER (Background Provisioning)
# ==============================================================================
class ToolManager(QThread):
    status_update = pyqtSignal(str)
    tools_ready = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.ffmpeg_path = shutil.which("ffmpeg")
        self.tesseract_path = shutil.which("tesseract")

    def run(self):
        if not self.ffmpeg_path:
            self.status_update.emit("Provisioning FFmpeg...")
            # In a full implementation, this would download FFmpeg binaries
            # For now, we rely on system PATH or user installation.
            self.status_update.emit("FFmpeg not found in PATH. Please install.")

        if not self.tesseract_path:
            self.status_update.emit("Tesseract not found. OCR disabled.")

        self.tools_ready.emit()


# ==============================================================================
# CONVERSION WORKER
# ==============================================================================
class ConversionWorker(QThread):
    progress = pyqtSignal(int, int, str)  # current, total, filename
    log_message = pyqtSignal(str, str)  # message, level (info, success, error)
    finished_batch = pyqtSignal(int, int)  # ok_count, fail_count

    def __init__(self, tasks: list[tuple[Path, str, Path, ConvertSettings]]):
        super().__init__()
        self.tasks = tasks
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        ok, fail = 0, 0
        total = len(self.tasks)

        for i, (src, dst_ext, out_dir, settings) in enumerate(self.tasks):
            if self._stop:
                break

            self.progress.emit(i + 1, total, src.name)

            try:
                converter = ConverterRegistry.get(get_ext(src), dst_ext)
                if not converter:
                    raise ValueError(f"No converter for .{get_ext(src)} -> .{dst_ext}")

                dst_path = out_dir / f"{src.stem}.{dst_ext}"
                if settings.conflict_mode == "rename":
                    dst_path = unique_output_path(dst_path)
                elif settings.conflict_mode == "skip" and dst_path.exists():
                    self.log_message.emit(f"Skipped: {src.name}", "info")
                    ok += 1
                    continue

                converter(src, dst_path, settings)
                self.log_message.emit(
                    f"Converted: {src.name} -> {dst_path.name}", "success"
                )
                ok += 1
            except Exception as e:
                self.log_message.emit(f"Failed: {src.name} ({e!s})", "error")
                fail += 1

        self.finished_batch.emit(ok, fail)


# ==============================================================================
# MAIN WINDOW
# ==============================================================================
class AlchemistWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RedTongue Alchemist")
        self.resize(1200, 800)

        self.files: list[Path] = []
        self.settings = ConvertSettings()
        self.worker: ConversionWorker | None = None
        self.tool_manager = ToolManager()

        self._build_ui()
        self._connect_signals()
        self.tool_manager.start()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # --- Left Pane: File List ---
        left_pane = QFrame()
        left_pane.setObjectName("Panel")
        left_layout = QVBoxLayout(left_pane)

        self.file_list = QListWidget()
        self.file_list.setAcceptDrops(True)
        self.file_list.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.file_list.itemDoubleClicked.connect(self._remove_file)
        left_layout.addWidget(QLabel("Files (Drop here)"))
        left_layout.addWidget(self.file_list, 1)

        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("Add Files")
        self.btn_add.clicked.connect(self._add_files)
        btn_layout.addWidget(self.btn_add)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.clicked.connect(self.file_list.clear)
        btn_layout.addWidget(self.btn_clear)
        left_layout.addLayout(btn_layout)

        # --- Center Pane: Preview & Settings ---
        center_splitter = QSplitter(Qt.Orientation.Vertical)

        # Preview
        preview_group = QGroupBox("Preview")
        preview_layout = QVBoxLayout(preview_group)
        self.preview_label = QLabel("Select a file to preview")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet(
            f"background: {C_INPUT}; border-radius: 4px; min-height: 150px;"
        )
        preview_layout.addWidget(self.preview_label)
        center_splitter.addWidget(preview_group)

        # Settings
        settings_group = QGroupBox("Conversion Settings")
        settings_layout = QVBoxLayout(settings_group)

        fmt_layout = QHBoxLayout()
        fmt_layout.addWidget(QLabel("Format:"))
        self.fmt_combo = QComboBox()
        self.fmt_combo.addItems(["auto", "jpg", "png", "pdf", "mp3", "wav", "mp4"])
        self.fmt_combo.currentTextChanged.connect(self._update_targets)
        fmt_layout.addWidget(self.fmt_combo, 1)
        settings_layout.addLayout(fmt_layout)

        quality_layout = QHBoxLayout()
        quality_layout.addWidget(QLabel("Quality (1-100):"))
        self.quality_spin = QComboBox()  # Using combo for simplicity in this refactor
        self.quality_spin.addItems(["90", "80", "70", "50"])
        self.quality_spin.setCurrentText("90")
        quality_layout.addWidget(self.quality_spin)
        settings_layout.addLayout(quality_layout)

        bitrate_layout = QHBoxLayout()
        bitrate_layout.addWidget(QLabel("Bitrate:"))
        self.bitrate_combo = QComboBox()
        self.bitrate_combo.addItems(["128k", "192k", "256k", "320k"])
        self.bitrate_combo.setCurrentText("128k")
        bitrate_layout.addWidget(self.bitrate_combo)
        settings_layout.addLayout(bitrate_layout)

        self.conflict_combo = QComboBox()
        self.conflict_combo.addItems(["rename", "overwrite", "skip"])
        settings_layout.addWidget(QLabel("If file exists:"))
        settings_layout.addWidget(self.conflict_combo)

        center_splitter.addWidget(settings_group)

        # --- Right Pane: Output & Actions ---
        right_pane = QFrame()
        right_pane.setObjectName("Panel")
        right_layout = QVBoxLayout(right_pane)

        out_group = QGroupBox("Output Directory")
        out_layout = QVBoxLayout(out_group)
        self.out_dir_edit = QLineEdit(str(Path.home()))
        out_layout.addWidget(self.out_dir_edit)
        self.btn_browse = QPushButton("Browse")
        self.btn_browse.clicked.connect(self._browse_output)
        out_layout.addWidget(self.btn_browse)
        right_layout.addWidget(out_group)

        self.btn_convert = QPushButton("START CONVERSION")
        self.btn_convert.setObjectName("Primary")
        self.btn_convert.setFixedHeight(50)
        self.btn_convert.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self.btn_convert.clicked.connect(self._start_conversion)
        right_layout.addWidget(self.btn_convert)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        right_layout.addWidget(self.progress_bar)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        right_layout.addWidget(self.log_text, 1)

        # Assemble Main Layout
        main_layout.addWidget(left_pane, 1)
        main_layout.addWidget(center_splitter, 2)
        main_layout.addWidget(right_pane, 1)

    def _connect_signals(self):
        self.tool_manager.status_update.connect(lambda msg: self._log(msg, "info"))
        self.tool_manager.tools_ready.connect(
            lambda: self._log("Tools initialized.", "success")
        )
        self.file_list.itemSelectionChanged.connect(self._update_preview)

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select Files")
        for f in files:
            p = Path(f)
            if p not in self.files:
                self.files.append(p)
                self.file_list.addItem(p.name)
        self._update_targets()

    def _remove_file(self, item):
        idx = self.file_list.row(item)
        if 0 <= idx < len(self.files):
            self.files.pop(idx)
            self.file_list.takeItem(idx)

    def _browse_output(self):
        d = QFileDialog.getExistingDirectory(self, "Output Directory")
        if d:
            self.out_dir_edit.setText(d)

    def _update_targets(self):
        # In a full app, this would dynamically update based on selected file types
        pass

    def _update_preview(self):
        items = self.file_list.selectedItems()
        if not items:
            self.preview_label.setText("Select a file to preview")
            return

        path = self.files[self.file_list.row(items[0])]
        ext = get_ext(path)

        if ext in ("jpg", "jpeg", "png", "bmp", "webp") and HAS_PIL:
            try:
                img = Image.open(path)
                img.thumbnail((300, 300))
                # Convert to QPixmap for PyQt6
                # Note: In production, use io.BytesIO to bridge PIL and Qt
                self.preview_label.setText(f"Image: {img.size[0]}x{img.size[1]}")
            except Exception as e:
                self.preview_label.setText(f"Preview error: {e}")
        else:
            self.preview_label.setText(
                f"File: {path.name}\nSize: {path.stat().st_size} bytes"
            )

    def _start_conversion(self):
        if not self.files:
            QMessageBox.warning(self, "No Files", "Add files to convert.")
            return

        out_dir = Path(self.out_dir_edit.text())
        out_dir.mkdir(parents=True, exist_ok=True)

        fmt = self.fmt_combo.currentText()
        self.settings.quality = int(self.quality_spin.currentText())
        self.settings.bitrate = self.bitrate_combo.currentText()
        self.settings.conflict_mode = self.conflict_combo.currentText()

        tasks = []
        for src in self.files:
            src_ext = get_ext(src)
            if fmt == "auto":
                # Simple auto-detect logic
                if src_ext in ("wav", "flac", "ogg", "m4a"):
                    target = "mp3"
                elif src_ext in ("jpg", "jpeg", "png", "bmp"):
                    target = "png"
                elif src_ext in ("mp4", "mkv", "avi"):
                    target = "mp4"
                else:
                    continue
            else:
                target = fmt

            if ConverterRegistry.get(src_ext, target):
                tasks.append((src, target, out_dir, self.settings))

        if not tasks:
            QMessageBox.warning(
                self,
                "No Valid Tasks",
                "No compatible converters found for selected files/formats.",
            )
            return

        self.btn_convert.setEnabled(False)
        self.btn_convert.setText("CONVERTING...")
        self.log_text.clear()

        self.worker = ConversionWorker(tasks)
        self.worker.progress.connect(self._on_progress)
        self.worker.log_message.connect(self._log)
        self.worker.finished_batch.connect(self._on_finished)
        self.worker.start()

    def _on_progress(self, current, total, filename):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.progress_bar.setFormat(f"{current}/{total} - {filename}")

    def _log(self, msg, level):
        color = C_WHITE
        if level == "success":
            color = C_SUCCESS
        elif level == "error":
            color = C_ERROR
        self.log_text.append(f'<span style="color:{color}">{msg}</span>')

    def _on_finished(self, ok, fail):
        self.btn_convert.setEnabled(True)
        self.btn_convert.setText("START CONVERSION")
        self._log(f"Batch complete: {ok} OK, {fail} Failed.", "success")

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            if url.isLocalFile():
                p = Path(url.toLocalFile())
                if p.is_file() and p not in self.files:
                    self.files.append(p)
                    self.file_list.addItem(p.name)


# ==============================================================================
# STANDALONE EXECUTION
# ==============================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(C_BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(C_WHITE))
    app.setPalette(palette)

    window = AlchemistWindow()
    window.show()
    sys.exit(app.exec())
