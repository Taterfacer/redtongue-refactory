#!/usr/bin/env python3
"""
redtongue_player.py
Native PyQt6 Media Suite for the RedTongue Refactory.
Supports MP3, MP4, and common audio/video formats via OS-native QtMultimedia.
Includes playlist management, Fisher-Yates shuffle, drag-and-drop, and
persistent JSON-based library.
Rule 7 Compliant: No external codec packs, no registry scanning, no bloat.
"""
import json
import random
import shutil
import sys
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QKeySequence
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QShortcut,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

try:
    from mutagen import File as MutagenFile
    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False

# ==============================================================================
# THEME & CONSTANTS
# ==============================================================================
APP_NAME = "RedTongue Media Player"
CONFIG_DIR = Path.home() / ".redtongue"
CONFIG_FILE = CONFIG_DIR / "player_config.json"
PLAYLIST_FILE = CONFIG_DIR / "playlist.json"
LIBRARY_FILE = CONFIG_DIR / "media_library.json"

C_BG = "#0d0d0d"
C_PANEL = "#121212"
C_INPUT = "#1a1a1a"
C_BORDER = "#222222"
C_RED = "#8b0000"
C_RED_HOVER = "#a52a2a"
C_WHITE = "#e0e0e0"
C_GRAY = "#888888"

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v"}
AUDIO_EXTS = {".mp3", ".flac", ".aac", ".ogg", ".opus", ".m4a", ".wav", ".wma"}
ALL_EXTS = VIDEO_EXTS | AUDIO_EXTS

# ==============================================================================
# UTILITIES
# ==============================================================================
def format_time(ms: int) -> str:
    """Formats milliseconds to MM:SS or HH:MM:SS."""
    if ms < 0: return "0:00"
    seconds = ms // 1000
    minutes = seconds // 60
    hours = minutes // 60
    if hours > 0:
        return f"{hours}:{minutes % 60:02d}:{seconds % 60:02d}"
    return f"{minutes}:{seconds % 60:02d}"

def atomic_write_json(path: Path, data: Any) -> None:
    """Writes JSON atomically to prevent corruption."""
    tmp = path.with_suffix(".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    shutil.move(str(tmp), str(path))

def load_json(path: Path, default: Any = None) -> Any:
    """Loads JSON with fallback."""
    if default is None: default = {}
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default

# ==============================================================================
# SHUFFLE QUEUE (Fisher-Yates)
# ==============================================================================
class ShuffleQueue:
    """Manages shuffle state without repeating tracks."""
    def __init__(self):
        self._unplayed: list[int] = []
        self._history: list[int] = []
        self._size: int = 0

    def reset(self, size: int):
        self._size = size
        self._unplayed = list(range(size))
        random.shuffle(self._unplayed)
        self._history = []

    def sync(self, size: int):
        if size == self._size: return
        if size > self._size:
            new_idx = list(range(self._size, size))
            random.shuffle(new_idx)
            self._unplayed.extend(new_idx)
        else:
            self._unplayed = [i for i in self._unplayed if i < size]
            self._history = [i for i in self._history if i < size]
        self._size = size

    def mark_played(self, idx: int):
        if idx in self._unplayed: self._unplayed.remove(idx)
        if idx not in self._history: self._history.append(idx)

    def next(self, size: int, current_index: int) -> int:
        if size <= 0: return -1
        self.sync(size)
        if not self._unplayed:
            self._unplayed = list(range(size))
            random.shuffle(self._unplayed)
        if current_index != -1 and size > 1:
            try:
                self._unplayed.remove(current_index)
                self._unplayed.append(current_index)
            except ValueError:
                pass
        idx = self._unplayed.pop(0)
        self._history.append(idx)
        return idx

    def previous(self, current_index: int) -> int:
        if len(self._history) < 2: return -1
        if self._history[-1] == current_index: self._history.pop()
        if self._history:
            prev = self._history[-1]
            if current_index != -1 and current_index not in self._unplayed:
                self._unplayed.insert(0, current_index)
            return prev
        return -1

# ==============================================================================
# MEDIA LIBRARY
# ==============================================================================
class MediaLibrary:
    """Lightweight, JSON-persisted media metadata cache."""
    def __init__(self):
        self.data = load_json(LIBRARY_FILE, {"tracks": [], "folders": []})
        self.tracks: list[dict[str, Any]] = self.data.get("tracks", [])
        self.folders: list[str] = self.data.get("folders", [])

    def save(self):
        atomic_write_json(LIBRARY_FILE, {"tracks": self.tracks, "folders": self.folders})

    def _extract_metadata(self, path: Path) -> dict[str, Any] | None:
        try:
            stat = path.stat()
        except Exception:
            return None

        track = {
            "path": str(path),
            "title": path.stem,
            "artist": "Unknown Artist",
            "album": "Unknown Album",
            "duration": 0,
            "type": "Video" if path.suffix.lower() in VIDEO_EXTS else "Audio",
            "folder": str(path.parent),
            "date_added": stat.st_mtime,
            "file_size": stat.st_size,
            "ext": path.suffix.lower(),
        }

        if HAS_MUTAGEN and path.suffix.lower() in AUDIO_EXTS:
            try:
                mfile = MutagenFile(str(path))
                if mfile is not None:
                    def get(*keys):
                        for k in keys:
                            if mfile.get(k): return str(mfile[k][0])
                        return None
                    title = get("title", "TIT2")
                    artist = get("artist", "TPE1")
                    album = get("album", "TALB")
                    if title: track["title"] = title
                    if artist: track["artist"] = artist
                    if album: track["album"] = album
                    if hasattr(mfile, "info") and hasattr(mfile.info, "length"):
                        track["duration"] = int(mfile.info.length * 1000)
            except Exception:
                pass
        return track

    def add_folder(self, folder: str) -> int:
        folder_path = Path(folder)
        if not folder_path.exists(): return 0
        if folder not in self.folders: self.folders.append(folder)

        existing = {t["path"] for t in self.tracks}
        added = 0
        for ext in ALL_EXTS:
            for p in folder_path.rglob(f"*{ext}"):
                sp = str(p)
                if sp in existing: continue
                t = self._extract_metadata(p)
                if t:
                    self.tracks.append(t)
                    existing.add(sp)
                    added += 1
        self.save()
        return added

    def remove_folder(self, folder: str):
        if folder in self.folders:
            self.folders.remove(folder)
            self.tracks = [t for t in self.tracks if not t["path"].startswith(folder)]
            self.save()

# ==============================================================================
# UI COMPONENTS
# ==============================================================================
class PlaylistWidget(QListWidget):
    """Custom playlist with drag-and-drop and context menus."""
    item_activated = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setStyleSheet(f"""
            QListWidget {{
                background-color: {C_BG}; color: {C_WHITE};
                border: 1px solid {C_BORDER}; border-radius: 4px;
                font-size: 12px; outline: none;
            }}
            QListWidget::item {{ padding: 6px; border-bottom: 1px solid {C_BORDER}; }}
            QListWidget::item:selected {{ background-color: {C_RED}; color: {C_WHITE}; }}
            QListWidget::item:hover {{ background-color: #2a2a2a; }}
        """)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.itemDoubleClicked.connect(lambda item: self.item_activated.emit(self.row(item)))

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: event.ignore()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        paths = []
        for url in urls:
            if url.isLocalFile():
                p = Path(url.toLocalFile())
                if p.is_dir():
                    paths.extend([f for f in p.rglob("*") if f.suffix.lower() in ALL_EXTS])
                elif p.suffix.lower() in ALL_EXTS:
                    paths.append(p)
        if paths:
            # Emit a custom signal or handle via parent. For simplicity, we'll let the parent poll or use a direct callback.
            # In this architecture, the parent connects to a custom signal.
            self.parent().handle_playlist_drop(paths)

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background-color: {C_PANEL}; color: {C_WHITE}; border: 1px solid {C_BORDER}; }}
            QMenu::item:selected {{ background-color: {C_RED}; }}
        """)
        remove_action = menu.addAction("Remove Selected")
        remove_action.triggered.connect(self._remove_selected)
        clear_action = menu.addAction("Clear Playlist")
        clear_action.triggered.connect(self.parent().clear_playlist)
        menu.exec(self.mapToGlobal(pos))

    def _remove_selected(self):
        for item in self.selectedItems():
            row = self.row(item)
            self.takeItem(row)
            self.parent().remove_track_at(row)

class RTButton(QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {C_INPUT}; color: {C_WHITE};
                border: 1px solid {C_BORDER}; border-radius: 4px;
                padding: 6px 12px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #2a2a2a; border-color: #444; }}
            QPushButton#Primary {{ background-color: {C_RED}; border-color: {C_RED_HOVER}; }}
            QPushButton#Primary:hover {{ background-color: {C_RED_HOVER}; }}
        """)

class RTSlider(QSlider):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                border: 1px solid {C_BORDER}; height: 6px;
                background: {C_INPUT}; border-radius: 3px;
            }}
            QSlider::sub-page:horizontal {{ background: {C_RED}; border-radius: 3px; }}
            QSlider::handle:horizontal {{
                background: {C_WHITE}; border: 1px solid {C_RED};
                width: 12px; height: 12px; margin: -3px 0; border-radius: 6px;
            }}
        """)

# ==============================================================================
# MAIN MEDIA WIDGET
# ==============================================================================
class MediaSuiteWidget(QWidget):
    """Embeddable Media Player Suite."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.playlist: list[Path] = []
        self.current_index = -1
        self.shuffle_mode = False
        self.repeat_mode = 0 # 0: Off, 1: One, 2: All
        self._seeking = False

        # Config
        self.config = load_json(CONFIG_FILE, {"volume": 80, "shuffle": False, "repeat": 0})
        self.shuffle_mode = self.config.get("shuffle", False)
        self.repeat_mode = self.config.get("repeat", 0)

        # Player Engine
        self.audio_output = QAudioOutput()
        self.audio_output.setVolume(self.config.get("volume", 80) / 100.0)
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.audio_output)

        # Helpers
        self.shuffle_queue = ShuffleQueue()
        self.library = MediaLibrary()

        self._build_ui()
        self._setup_shortcuts()
        self._load_saved_playlist()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Top: Video / Art
        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet(f"background-color: {C_BG}; border-radius: 6px;")
        self.player.setVideoOutput(self.video_widget)
        layout.addWidget(self.video_widget, stretch=1)

        # Middle: Now Playing & Controls
        self.now_playing = QLabel("No file loaded")
        self.now_playing.setStyleSheet(f"color: {C_GRAY}; font-size: 12px; padding: 4px;")
        self.now_playing.setWordWrap(True)
        layout.addWidget(self.now_playing)

        # Seek Bar
        seek_layout = QHBoxLayout()
        self.time_current = QLabel("0:00")
        self.time_current.setStyleSheet(f"color: {C_GRAY}; font-size: 11px; min-width: 40px;")
        seek_layout.addWidget(self.time_current)

        self.seek_slider = RTSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.setEnabled(False)
        self.seek_slider.sliderPressed.connect(lambda: setattr(self, '_seeking', True))
        self.seek_slider.sliderReleased.connect(self._on_seek_released)
        self.seek_slider.sliderMoved.connect(self._seek)
        seek_layout.addWidget(self.seek_slider, stretch=1)

        self.time_total = QLabel("0:00")
        self.time_total.setStyleSheet(f"color: {C_GRAY}; font-size: 11px; min-width: 40px;")
        seek_layout.addWidget(self.time_total)
        layout.addLayout(seek_layout)

        # Transport
        transport = QHBoxLayout()
        self.btn_prev = RTButton("⏮")
        self.btn_prev.clicked.connect(self._play_previous)
        transport.addWidget(self.btn_prev)

        self.btn_play = RTButton("▶ Play")
        self.btn_play.setObjectName("Primary")
        self.btn_play.clicked.connect(self._toggle_play)
        transport.addWidget(self.btn_play)

        self.btn_next = RTButton("⏭")
        self.btn_next.clicked.connect(self._play_next)
        transport.addWidget(self.btn_next)

        transport.addStretch()

        self.btn_shuffle = RTButton("🔀")
        self.btn_shuffle.setCheckable(True)
        self.btn_shuffle.setChecked(self.shuffle_mode)
        self.btn_shuffle.clicked.connect(self._toggle_shuffle)
        transport.addWidget(self.btn_shuffle)

        self.btn_repeat = RTButton("🔁")
        self.btn_repeat.setCheckable(True)
        self.btn_repeat.setChecked(self.repeat_mode > 0)
        self.btn_repeat.clicked.connect(self._cycle_repeat)
        transport.addWidget(self.btn_repeat)

        layout.addLayout(transport)

        # Bottom: Playlist & Actions
        bottom_splitter = QSplitter(Qt.Orientation.Vertical)

        # Playlist
        self.playlist_widget = PlaylistWidget(self)
        bottom_splitter.addWidget(self.playlist_widget)

        # Action Buttons
        action_layout = QHBoxLayout()
        self.btn_open = RTButton("Open Files")
        self.btn_open.clicked.connect(self._open_files)
        action_layout.addWidget(self.btn_open)

        self.btn_folder = RTButton("Open Folder")
        self.btn_folder.clicked.connect(self._open_folder)
        action_layout.addWidget(self.btn_folder)

        self.btn_clear = RTButton("Clear")
        self.btn_clear.clicked.connect(self.clear_playlist)
        action_layout.addWidget(self.btn_clear)

        action_layout.addStretch()

        self.vol_slider = RTSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(int(self.audio_output.volume() * 100))
        self.vol_slider.setFixedWidth(100)
        self.vol_slider.valueChanged.connect(self._set_volume)
        action_layout.addWidget(self.vol_slider)

        action_widget = QWidget()
        action_widget.setLayout(action_layout)
        bottom_splitter.addWidget(action_widget)

        bottom_splitter.setSizes([200, 40])
        layout.addWidget(bottom_splitter)

        # Player Signals
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.playbackStateChanged.connect(self._on_state_changed)

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Space"), self, self._toggle_play)
        QShortcut(QKeySequence("Right"), self, lambda: self._seek_relative(5000))
        QShortcut(QKeySequence("Left"), self, lambda: self._seek_relative(-5000))
        QShortcut(QKeySequence("Up"), self, lambda: self._adjust_volume(5))
        QShortcut(QKeySequence("Down"), self, lambda: self._adjust_volume(-5))
        QShortcut(QKeySequence("N"), self, self._play_next)
        QShortcut(QKeySequence("P"), self, self._play_previous)
        QShortcut(QKeySequence("F"), self, self._toggle_fullscreen)

    # --- Playback Logic ---
    def _open_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Open Media", "", "Media Files (*.mp3 *.mp4 *.mkv *.wav *.flac *.aac *.ogg)")
        if files: self._add_files([Path(f) for f in files])

    def _open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Open Media Folder")
        if folder:
            found = [f for f in Path(folder).rglob("*") if f.suffix.lower() in ALL_EXTS]
            if found: self._add_files(sorted(found))

    def _add_files(self, paths: list[Path]):
        for p in paths:
            if p not in self.playlist:
                self.playlist.append(p)
                item = QListWidgetItem(p.name)
                item.setToolTip(str(p))
                self.playlist_widget.addItem(item)

        if self.shuffle_mode: self.shuffle_queue.sync(len(self.playlist))
        if self.current_index == -1 and self.playlist: self._play_index(0)
        self._save_playlist()

    def handle_playlist_drop(self, paths: list[Path]):
        self._add_files(paths)

    def _play_index(self, index: int):
        if not (0 <= index < len(self.playlist)): return
        self.current_index = index
        path = self.playlist[index]
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.play()
        self.now_playing.setText(f"Now Playing: {path.name}")
        self.playlist_widget.setCurrentRow(index)

    def _toggle_play(self):
        state = self.player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            if self.current_index == -1 and self.playlist: self._play_index(0)
            else: self.player.play()

    def _play_next(self):
        if not self.playlist: return
        if self.shuffle_mode:
            idx = self.shuffle_queue.next(len(self.playlist), self.current_index)
            if 0 <= idx < len(self.playlist): self._play_index(idx)
        elif self.current_index + 1 < len(self.playlist):
            self._play_index(self.current_index + 1)
        elif self.repeat_mode == 2:
            self._play_index(0)

    def _play_previous(self):
        if not self.playlist: return
        if self.player.position() > 5000:
            self.player.setPosition(0)
            return
        if self.shuffle_mode:
            idx = self.shuffle_queue.previous(self.current_index)
            if 0 <= idx < len(self.playlist): self._play_index(idx)
        elif self.current_index > 0:
            self._play_index(self.current_index - 1)

    def _toggle_shuffle(self):
        self.shuffle_mode = self.btn_shuffle.isChecked()
        if self.shuffle_mode:
            self.shuffle_queue.reset(len(self.playlist))
            if 0 <= self.current_index < len(self.playlist):
                self.shuffle_queue.mark_played(self.current_index)
        self.config["shuffle"] = self.shuffle_mode
        atomic_write_json(CONFIG_FILE, self.config)

    def _cycle_repeat(self):
        self.repeat_mode = (self.repeat_mode + 1) % 3
        self.btn_repeat.setChecked(self.repeat_mode > 0)
        labels = ["", "🔂", ""]
        self.btn_repeat.setText(labels[self.repeat_mode])
        self.config["repeat"] = self.repeat_mode
        atomic_write_json(CONFIG_FILE, self.config)

    def clear_playlist(self):
        self.player.stop()
        self.playlist.clear()
        self.playlist_widget.clear()
        self.current_index = -1
        self.shuffle_queue.reset(0)
        self.now_playing.setText("No file loaded")
        self._save_playlist()

    def remove_track_at(self, row: int):
        if not (0 <= row < len(self.playlist)): return
        if row == self.current_index:
            self.player.stop()
            self.current_index = -1
        elif row < self.current_index:
            self.current_index -= 1
        self.playlist.pop(row)
        if self.shuffle_mode: self.shuffle_queue.reset(len(self.playlist))
        self._save_playlist()

    # --- UI Updates ---
    def _on_position_changed(self, position: int):
        if self._seeking: return
        self.time_current.setText(format_time(position))
        if self.seek_slider.maximum() > 0: self.seek_slider.setValue(position)

    def _on_duration_changed(self, duration: int):
        self.seek_slider.setRange(0, duration)
        self.seek_slider.setEnabled(duration > 0)
        self.time_total.setText(format_time(duration))

    def _on_state_changed(self, state: QMediaPlayer.PlaybackState):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.btn_play.setText("⏸ Pause")
        else:
            self.btn_play.setText("▶ Play")
            if self.current_index != -1 and self.player.position() >= self.player.duration() - 500:
                if self.repeat_mode == 1: self._play_index(self.current_index)
                else: self._play_next()

    def _on_seek_released(self):
        self._seeking = False

    def _seek(self, position: int):
        self.player.setPosition(position)

    def _seek_relative(self, ms: int):
        self.player.setPosition(max(0, self.player.position() + ms))

    def _set_volume(self, value: int):
        self.audio_output.setVolume(value / 100.0)
        self.config["volume"] = value
        atomic_write_json(CONFIG_FILE, self.config)

    def _adjust_volume(self, delta: int):
        new_val = max(0, min(100, self.vol_slider.value() + delta))
        self.vol_slider.setValue(new_val)

    def _toggle_fullscreen(self):
        if self.video_widget.isFullScreen():
            self.video_widget.showNormal()
        else:
            self.video_widget.showFullScreen()

    # --- Persistence ---
    def _save_playlist(self):
        data = {"playlist": [str(p) for p in self.playlist], "current_index": self.current_index}
        atomic_write_json(PLAYLIST_FILE, data)

    def _load_saved_playlist(self):
        saved = load_json(PLAYLIST_FILE, {"playlist": [], "current_index": -1})
        paths = [Path(p) for p in saved.get("playlist", []) if Path(p).exists()]
        if paths:
            self._add_files(paths)
            idx = saved.get("current_index", -1)
            if 0 <= idx < len(self.playlist): self._play_index(idx)

# ==============================================================================
# STANDALONE EXECUTION
# ==============================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(f"""
        QMainWindow, QWidget {{ background-color: {C_BG}; color: {C_WHITE}; font-family: 'Segoe UI', sans-serif; }}
    """)

    window = QWidget()
    window.setWindowTitle(APP_NAME)
    window.resize(1000, 700)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(10, 10, 10, 10)

    player = MediaSuiteWidget()
    layout.addWidget(player)

    window.show()
    sys.exit(app.exec())