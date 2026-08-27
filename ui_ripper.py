#!/usr/bin/env python3
"""
ui_ripper.py
RedTongue Ripper - Professional Media Downloader Deck.
Native PyQt6 frontend for yt-dlp. Features a threaded download queue,
drag-and-drop URL ingestion, SQLite history tracking, and
Audio/Video mode toggling. Optimized for low-RAM environments.
"""

import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
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
C_GREEN = "#2ecc71"
C_YELLOW = "#f1c40f"

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
QScrollBar:vertical {{ background: {C_BG}; width: 8px; }}
QScrollBar::handle:vertical {{ background: #333333; border-radius: 4px; }}
QScrollBar::handle:vertical:hover {{ background: {C_RED}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
"""


# ==============================================================================
# DATABASE MANAGER
# ==============================================================================
class RipperDB:
    """Lightweight SQLite tracker for download history."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._init_db()

    def _init_db(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT, title TEXT, mode TEXT, fmt TEXT,
                    status TEXT, file_path TEXT, timestamp TEXT
                )
            """)

    def add_entry(self, url: str, title: str, mode: str, fmt: str, status: str, file_path: str):
        with self.conn:
            self.conn.execute(
                "INSERT INTO history (url, title, mode, fmt, status, file_path, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (url, title, mode, fmt, status, file_path, time.strftime("%Y-%m-%d %H:%M:%S")),
            )

    def get_history(self, limit: int = 50) -> list[tuple]:
        cursor = self.conn.execute("SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,))
        return cursor.fetchall()

    def clear_history(self):
        with self.conn:
            self.conn.execute("DELETE FROM history")


# ==============================================================================
# DOWNLOAD WORKER
# ==============================================================================
class YtDlpWorker(QThread):
    """Background thread for yt-dlp execution."""

    progress = pyqtSignal(int, str)  # percentage, status_text
    finished = pyqtSignal(bool, str, str)  # success, title, file_path
    log = pyqtSignal(str)

    def __init__(self, url: str, opts: dict[str, Any], parent=None):
        super().__init__(parent)
        self.url = url
        self.opts = opts
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def _progress_hook(self, d: dict[str, Any]):
        if self._is_cancelled:
            raise Exception("Cancelled by user")

        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            speed = d.get("speed", 0) or 0

            if total > 0:
                pct = int((downloaded / total) * 100)
            else:
                pct = 0

            speed_str = f"{speed / 1024 / 1024:.2f} MB/s" if speed > 0 else "..."
            self.progress.emit(pct, f"Downloading... {speed_str}")

        elif d["status"] == "finished":
            self.progress.emit(99, "Converting...")

    def run(self):
        try:
            import yt_dlp

            # Deep copy opts to avoid mutation issues
            opts = dict(self.opts)
            opts["progress_hooks"] = [self._progress_hook]
            opts["logger"] = None  # Suppress console spam

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.url, download=True)

                if info is None:
                    self.finished.emit(False, "Unknown", "Failed to extract info")
                    return

                title = info.get("title", "Unknown")
                filepath = ydl.prepare_filename(info)

                # Handle playlists
                if "entries" in info:
                    title = f"Playlist: {title}"

                self.finished.emit(True, title, filepath)

        except Exception as e:
            if "Cancelled" in str(e):
                self.finished.emit(False, "Cancelled", "")
            else:
                self.log.emit(str(e))
                self.finished.emit(False, "Error", str(e)[:100])


# ==============================================================================
# DOWNLOAD ITEM WIDGET
# ==============================================================================
class DownloadItemWidget(QFrame):
    """Custom widget representing a single download in the queue."""

    cancel_requested = pyqtSignal()

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.url = url
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Header
        header = QHBoxLayout()
        self.url_lbl = QLabel(self.url[:60] + "..." if len(self.url) > 60 else self.url)
        self.url_lbl.setStyleSheet(f"color: {C_WHITE}; font-size: 12px;")
        header.addWidget(self.url_lbl, 1)

        self.cancel_btn = QPushButton("✕")
        self.cancel_btn.setFixedSize(24, 24)
        self.cancel_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C_GRAY}; border: none; font-size: 14px; }}
            QPushButton:hover {{ color: {C_RED}; }}
        """)
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)
        header.addWidget(self.cancel_btn)
        layout.addLayout(header)

        # Progress
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setFixedHeight(12)
        self.bar.setStyleSheet(f"""
            QProgressBar {{ background-color: {C_INPUT}; border: 1px solid {C_BORDER}; border-radius: 6px; text-align: center; }}
            QProgressBar::chunk {{ background-color: {C_RED}; border-radius: 6px; }}
        """)
        layout.addWidget(self.bar)

        # Status
        self.status_lbl = QLabel("Queued")
        self.status_lbl.setStyleSheet(f"color: {C_GRAY}; font-size: 11px;")
        layout.addWidget(self.status_lbl)

    def update_progress(self, pct: int, status: str):
        self.bar.setValue(pct)
        self.status_lbl.setText(status)

    def set_finished(self, success: bool, title: str, path: str):
        if success:
            self.bar.setValue(100)
            self.status_lbl.setText(f"✓ {title}")
            self.status_lbl.setStyleSheet(f"color: {C_GREEN}; font-size: 11px;")
            self.cancel_btn.hide()
        else:
            self.status_lbl.setText(f"✕ {title}")
            self.status_lbl.setStyleSheet(f"color: {C_RED}; font-size: 11px;")
            self.bar.setStyleSheet(f"""
                QProgressBar {{ background-color: {C_INPUT}; border: 1px solid {C_BORDER}; border-radius: 6px; }}
                QProgressBar::chunk {{ background-color: {C_RED}; border-radius: 6px; }}
            """)


# ==============================================================================
# MAIN WINDOW
# ==============================================================================
class RipperWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RedTongue Ripper")
        self.resize(900, 700)

        self.db = RipperDB(Path.home() / ".redtongue" / "ripper_history.db")
        self.active_workers: dict[int, YtDlpWorker] = {}
        self.download_queue: list[dict[str, Any]] = []
        self.max_concurrent = 2

        self._build_ui()
        self._load_history()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 1. URL Input
        input_frame = QFrame()
        input_frame.setObjectName("Panel")
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(10, 10, 10, 10)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Paste URL here (Drag & Drop supported)...")
        self.url_input.setAcceptDrops(True)
        self.url_input.returnPressed.connect(self._add_to_queue)
        input_layout.addWidget(self.url_input, 1)

        self.add_btn = QPushButton("Add")
        self.add_btn.setObjectName("Primary")
        self.add_btn.clicked.connect(self._add_to_queue)
        input_layout.addWidget(self.add_btn)
        main_layout.addWidget(input_frame)

        # 2. Options Bar
        opts_frame = QFrame()
        opts_frame.setObjectName("Panel")
        opts_layout = QHBoxLayout(opts_frame)
        opts_layout.setContentsMargins(10, 10, 10, 10)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Audio (MP3)", "Video (MP4)"])
        opts_layout.addWidget(QLabel("Mode:"))
        opts_layout.addWidget(self.mode_combo)

        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["Best", "High (1080p/320k)", "Medium (720p/192k)", "Low (480p/128k)"])
        opts_layout.addWidget(QLabel("Quality:"))
        opts_layout.addWidget(self.quality_combo)

        opts_layout.addStretch()

        self.thumb_chk = QCheckBox("Thumb")
        self.subs_chk = QCheckBox("Subs")
        opts_layout.addWidget(self.thumb_chk)
        opts_layout.addWidget(self.subs_chk)

        main_layout.addWidget(opts_frame)

        # 3. Download Queue
        queue_header = QHBoxLayout()
        queue_header.addWidget(QLabel("Download Queue"))
        queue_header.addStretch()
        self.clear_btn = QPushButton("Clear Finished")
        self.clear_btn.clicked.connect(self._clear_finished)
        queue_header.addWidget(self.clear_btn)
        main_layout.addLayout(queue_header)

        self.queue_scroll = QScrollArea()
        self.queue_scroll.setWidgetResizable(True)
        self.queue_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.queue_container = QWidget()
        self.queue_layout = QVBoxLayout(self.queue_container)
        self.queue_layout.setContentsMargins(0, 0, 0, 0)
        self.queue_layout.setSpacing(8)
        self.queue_layout.addStretch()

        self.queue_scroll.setWidget(self.queue_container)
        main_layout.addWidget(self.queue_scroll, 1)

        # 4. Status Bar
        self.status_lbl = QLabel("Ready")
        self.status_lbl.setStyleSheet(f"color: {C_GRAY}; font-size: 12px;")
        main_layout.addWidget(self.status_lbl)

        # Enable Drag and Drop on main window
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = [url.toString() for url in event.mimeData().urls() if url.toString().startswith("http")]
        if urls:
            self.url_input.setText(urls[0])
            self._add_to_queue()

    def _get_opts(self) -> dict[str, Any]:
        mode = self.mode_combo.currentText()
        quality = self.quality_combo.currentText()

        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "outtmpl": os.path.join(Path.home(), "Downloads", "RedTongue", "%(title)s.%(ext)s"),
        }

        if "Audio" in mode:
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "320" if "Best" in quality else "192" if "High" in quality else "128",
                }
            ]
        else:
            if "Best" in quality:
                opts["format"] = "bestvideo+bestaudio/best"
            elif "High" in quality:
                opts["format"] = "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
            elif "Medium" in quality:
                opts["format"] = "bestvideo[height<=720]+bestaudio/best[height<=720]"
            else:
                opts["format"] = "bestvideo[height<=480]+bestaudio/best[height<=480]"
            opts["merge_output_format"] = "mp4"

        if self.thumb_chk.isChecked():
            opts.setdefault("postprocessors", []).append({"key": "EmbedThumbnail"})
        if self.subs_chk.isChecked():
            opts["writesubtitles"] = True
            opts["subtitleslangs"] = ["en"]

        return opts

    def _add_to_queue(self):
        url = self.url_input.text().strip()
        if not url:
            return

        self.url_input.clear()

        # Create UI Widget
        item_widget = DownloadItemWidget(url)
        item_widget.cancel_requested.connect(lambda: self._cancel_download(id(item_widget)))

        # Insert before the stretch
        self.queue_layout.insertWidget(self.queue_layout.count() - 1, item_widget)

        # Add to logic queue
        task = {"id": id(item_widget), "url": url, "widget": item_widget, "opts": self._get_opts()}
        self.download_queue.append(task)
        self._process_queue()

    def _process_queue(self):
        active_count = len(self.active_workers)
        if active_count >= self.max_concurrent or not self.download_queue:
            return

        task = self.download_queue.pop(0)
        widget = task["widget"]

        worker = YtDlpWorker(task["url"], task["opts"])
        worker.progress.connect(lambda pct, txt, w=widget: w.update_progress(pct, txt))
        worker.finished.connect(
            lambda ok, title, path, w=widget, u=task["url"]: self._on_finished(ok, title, path, w, u)
        )

        self.active_workers[task["id"]] = worker
        widget.update_progress(0, "Starting...")
        worker.start()

        # Process next if possible
        self._process_queue()

    def _on_finished(self, success: bool, title: str, path: str, widget: DownloadItemWidget, url: str):
        widget_id = id(widget)
        self.active_workers.pop(widget_id, None)

        widget.set_finished(success, title, path)

        mode = "Audio" if "Audio" in self.mode_combo.currentText() else "Video"
        fmt = "mp3" if "Audio" in mode else "mp4"
        status = "ok" if success else "error"

        self.db.add_entry(url, title, mode, fmt, status, path)
        self.status_lbl.setText(f"Finished: {title}")

        # Continue queue
        self._process_queue()

    def _cancel_download(self, widget_id: int):
        worker = self.active_workers.get(widget_id)
        if worker:
            worker.cancel()

    def _clear_finished(self):
        # Iterate backwards to safely remove widgets
        for i in range(self.queue_layout.count() - 1, -1, -1):
            item = self.queue_layout.itemAt(i)
            if item and isinstance(item.widget(), DownloadItemWidget):
                w = item.widget()
                if "✓" in w.status_lbl.text() or "✕" in w.status_lbl.text():
                    self.queue_layout.removeWidget(w)
                    w.deleteLater()

    def _load_history(self):
        # Optional: Load last 5 downloads into a log or just initialize DB
        pass


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

    window = RipperWindow()
    window.show()
    sys.exit(app.exec())
