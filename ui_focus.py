#!/usr/bin/env python3
"""
ui_focus.py
RedTongue Focus Studio Deck.
Native PyQt6 productivity module featuring Pomodoro timer, task management,
notes, statistics, and alarms. Includes a pure-Python WAV synthesizer for
audio cues without external audio dependencies.
"""

import json
import os
import shutil
import struct
import sys
import threading
import wave
from datetime import datetime
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

# ==============================================================================
# THEME CONSTANTS (Blood & Void)
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

APP_NAME = "RedTongue Focus"
CONFIG_DIR = Path.home() / ".redtongue" / "focus"
DATA_FILE = CONFIG_DIR / "focus_data.json"


# ==============================================================================
# DATA MANAGER (Thread-safe, Atomic JSON, Backup Rotation)
# ==============================================================================
class DataManager:
    """Manages persistent state with atomic writes and 3-generation backup."""

    _MAX_BACKUPS = 3

    def __init__(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if DATA_FILE.exists():
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        # Fallback to backups
        for i in range(self._MAX_BACKUPS, 0, -1):
            backup = DATA_FILE.with_suffix(f".json.bak{i}")
            if backup.exists():
                try:
                    with open(backup, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    continue
        return self._create_defaults()

    def _create_defaults(self) -> dict[str, Any]:
        return {
            "alarms": [],
            "day_notes": {},
            "use_24h": False,
            "sessions": [],
            "tasks": [],
            "notes": [{"id": "default", "title": "Quick Notes", "content": "", "updated": ""}],
            "settings": {
                "focus_duration": 25,
                "short_break": 5,
                "long_break": 15,
                "voice_volume": 80,
                "hotkeys_enabled": True,
            },
        }

    def save(self, immediate: bool = False) -> None:
        with self._lock:
            if immediate:
                self._do_save()
            else:
                # Debounce save in production; here we just save immediately for simplicity
                self._do_save()

    def _do_save(self) -> None:
        try:
            # Rotate backups
            for i in range(self._MAX_BACKUPS - 1, 0, -1):
                src = DATA_FILE.with_suffix(f".json.bak{i}")
                dst = DATA_FILE.with_suffix(f".json.bak{i + 1}")
                if src.exists():
                    shutil.copy2(str(src), str(dst))
            if DATA_FILE.exists():
                shutil.copy2(str(DATA_FILE), str(DATA_FILE.with_suffix(".json.bak1")))

            # Atomic write
            tmp = DATA_FILE.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            os.replace(str(tmp), str(DATA_FILE))
        except Exception as e:
            print(f"Focus Data Save Error: {e}")

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get("settings", {}).get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        with self._lock:
            self._data.setdefault("settings", {})[key] = value
        self.save()

    def add_session(self, duration_sec: int, session_type: str = "focus", completed: bool = True) -> None:
        session = {
            "id": datetime.now().isoformat(),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": datetime.now().strftime("%H:%M"),
            "duration": max(0, int(duration_sec)),
            "type": session_type,
            "completed": completed,
        }
        with self._lock:
            self._data.setdefault("sessions", []).append(session)
        self.save()

    def get_sessions(self, date_str: str | None = None) -> list[dict]:
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            return [s for s in self._data.get("sessions", []) if s.get("date") == date_str]

    def get_total_focus_time_today(self) -> int:
        sessions = self.get_sessions()
        return sum(s["duration"] for s in sessions if s.get("type") == "focus" and s.get("completed"))

    def add_task(self, text: str, priority: str = "normal") -> dict:
        task = {
            "id": datetime.now().isoformat(),
            "text": text.strip(),
            "priority": priority,
            "completed": False,
            "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "completed_date": None,
        }
        with self._lock:
            self._data.setdefault("tasks", []).append(task)
        self.save()
        return task

    def get_tasks(self, filter_status: str = "all") -> list[dict]:
        with self._lock:
            tasks = list(self._data.get("tasks", []))
        if filter_status == "active":
            return [t for t in tasks if not t.get("completed")]
        elif filter_status == "completed":
            return [t for t in tasks if t.get("completed")]
        return tasks

    def update_task(self, task_id: str, **kwargs) -> None:
        with self._lock:
            for task in self._data.get("tasks", []):
                if task.get("id") == task_id:
                    for k, v in kwargs.items():
                        task[k] = v
                    if kwargs.get("completed") and not task.get("completed_date"):
                        task["completed_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    break
        self.save()

    def delete_task(self, task_id: str) -> None:
        with self._lock:
            self._data["tasks"] = [t for t in self._data.get("tasks", []) if t.get("id") != task_id]
        self.save()

    def get_notes(self) -> list[dict]:
        with self._lock:
            return list(self._data.get("notes", []))

    def update_note(self, note_id: str, content: str) -> None:
        with self._lock:
            for note in self._data.get("notes", []):
                if note.get("id") == note_id:
                    note["content"] = content
                    note["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    break
        self.save()


# ==============================================================================
# SOUND SYNTHESIZER (Pure Python WAV Generation)
# ==============================================================================
class SoundSynthesizer:
    """Generates audio cues as WAV files without external dependencies."""

    SAMPLE_RATE = 44100

    @staticmethod
    def generate(filepath: Path, sound_type: str = "classic", volume: int = 80) -> None:
        amplitude = int(32767 * max(0, min(100, volume)) / 100.0)
        duration_ms = 300
        num_samples = int(SoundSynthesizer.SAMPLE_RATE * duration_ms / 1000)

        filepath.parent.mkdir(parents=True, exist_ok=True)

        with wave.open(str(filepath), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SoundSynthesizer.SAMPLE_RATE)

            for i in range(num_samples):
                if sound_type == "classic":
                    val = amplitude if int(i * 1000 / SoundSynthesizer.SAMPLE_RATE) % 2 == 0 else -amplitude
                elif sound_type == "done":
                    notes = [523, 659, 784, 1047]
                    note_idx = int((i / num_samples) * 4) % 4
                    val = amplitude if int(i * notes[note_idx] / SoundSynthesizer.SAMPLE_RATE) % 2 == 0 else -amplitude
                elif sound_type == "break":
                    notes = [784, 659, 523, 392]
                    note_idx = int((i / num_samples) * 4) % 4
                    val = amplitude if int(i * notes[note_idx] / SoundSynthesizer.SAMPLE_RATE) % 2 == 0 else -amplitude
                else:
                    val = amplitude if int(i * 800 / SoundSynthesizer.SAMPLE_RATE) % 2 == 0 else -amplitude

                # Simple decay envelope
                decay = 1.0 - (i / num_samples) * 0.5
                val = int(val * decay)
                wf.writeframes(struct.pack("<h", max(-32768, min(32767, val))))


# ==============================================================================
# UI PAGES
# ==============================================================================
class TimerPage(QWidget):
    def __init__(self, dm: DataManager, audio_player: QMediaPlayer):
        super().__init__()
        self.dm = dm
        self.audio = audio_player
        self.remaining_s = 0
        self.total_s = 0
        self.is_running = False
        self.mode = "focus"

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._build_ui()
        self._set_mode("focus")

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.mode_label = QLabel("FOCUS TIME")
        self.mode_label.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {C_GRAY}; letter-spacing: 2px;")
        layout.addWidget(self.mode_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.time_label = QLabel("25:00")
        self.time_label.setStyleSheet(
            f"font-size: 96px; font-weight: bold; color: {C_WHITE}; font-family: 'Consolas', monospace;"
        )
        layout.addWidget(self.time_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.progress_bar = QFrame()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setFixedWidth(500)
        self.progress_bar.setStyleSheet(f"background-color: {C_INPUT}; border-radius: 4px;")
        self.progress_fill = QFrame(self.progress_bar)
        self.progress_fill.setFixedHeight(8)
        self.progress_fill.setStyleSheet(f"background-color: {C_RED}; border-radius: 4px;")
        layout.addWidget(self.progress_bar, alignment=Qt.AlignmentFlag.AlignCenter)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(16)

        self.btn_start = QPushButton("START")
        self.btn_start.setObjectName("Primary")
        self.btn_start.setFixedSize(140, 50)
        self.btn_start.setStyleSheet("font-size: 18px;")
        self.btn_start.clicked.connect(self._toggle)
        btn_layout.addWidget(self.btn_start)

        self.btn_reset = QPushButton("RESET")
        self.btn_reset.setFixedSize(100, 50)
        self.btn_reset.clicked.connect(self._reset)
        btn_layout.addWidget(self.btn_reset)

        self.btn_skip = QPushButton("SKIP")
        self.btn_skip.setFixedSize(100, 50)
        self.btn_skip.clicked.connect(self._skip)
        btn_layout.addWidget(self.btn_skip)

        layout.addSpacing(30)
        layout.addLayout(btn_layout)

        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(10)
        self.btn_focus = QPushButton("Focus")
        self.btn_short = QPushButton("Short Break")
        self.btn_long = QPushButton("Long Break")
        for b in [self.btn_focus, self.btn_short, self.btn_long]:
            b.setFixedHeight(36)
            b.clicked.connect(lambda checked, m=b.text().lower().replace(" ", "_"): self._user_set_mode(m))
            mode_layout.addWidget(b)

        layout.addSpacing(20)
        layout.addLayout(mode_layout)
        layout.addStretch()

    def _user_set_mode(self, mode: str):
        self._set_mode(mode)

    def _set_mode(self, mode: str):
        self.mode = mode
        self.is_running = False
        self.timer.stop()
        self.btn_start.setText("START")

        if mode == "focus":
            mins = self.dm.get_setting("focus_duration", 25)
            self.mode_label.setText("FOCUS TIME")
            self.progress_fill.setStyleSheet(f"background-color: {C_RED}; border-radius: 4px;")
        elif mode == "short_break":
            mins = self.dm.get_setting("short_break", 5)
            self.mode_label.setText("SHORT BREAK")
            self.progress_fill.setStyleSheet(f"background-color: {C_GREEN}; border-radius: 4px;")
        else:
            mins = self.dm.get_setting("long_break", 15)
            self.mode_label.setText("LONG BREAK")
            self.progress_fill.setStyleSheet(f"background-color: {C_YELLOW}; border-radius: 4px;")

        self.total_s = mins * 60
        self.remaining_s = self.total_s
        self._update_display()

    def _toggle(self):
        if self.is_running:
            self.is_running = False
            self.timer.stop()
            self.btn_start.setText("RESUME")
        else:
            self.is_running = True
            self.timer.start(1000)
            self.btn_start.setText("PAUSE")

    def _reset(self):
        self.is_running = False
        self.timer.stop()
        self.remaining_s = self.total_s
        self.btn_start.setText("START")
        self._update_display()

    def _skip(self):
        self._complete_session()

    def _tick(self):
        if self.remaining_s > 0:
            self.remaining_s -= 1
            self._update_display()
        else:
            self._complete_session()

    def _complete_session(self):
        self.is_running = False
        self.timer.stop()

        # Play sound
        sound_path = CONFIG_DIR / "sounds" / f"{self.mode}.wav"
        SoundSynthesizer.generate(sound_path, sound_type=self.mode, volume=self.dm.get_setting("voice_volume", 80))
        self.audio.setSource(QUrl.fromLocalFile(str(sound_path)))
        self.audio.play()

        if self.mode == "focus":
            self.dm.add_session(self.dm.get_setting("focus_duration", 25) * 60, "focus", completed=True)
            self._set_mode("short_break")
        else:
            self._set_mode("focus")

    def _update_display(self):
        mins, secs = divmod(self.remaining_s, 60)
        self.time_label.setText(f"{mins:02d}:{secs:02d}")

        if self.total_s > 0:
            pct = 1.0 - (self.remaining_s / self.total_s)
            self.progress_fill.setFixedWidth(int(500 * pct))


class TasksPage(QWidget):
    def __init__(self, dm: DataManager):
        super().__init__()
        self.dm = dm
        self._build_ui()
        self._load_tasks()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        header = QHBoxLayout()
        title = QLabel("TASKS")
        title.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {C_WHITE}; letter-spacing: 2px;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        input_layout = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("What needs to be done?")
        self.input.returnPressed.connect(self._add_task)
        input_layout.addWidget(self.input, 1)

        btn_add = QPushButton("ADD")
        btn_add.setObjectName("Primary")
        btn_add.clicked.connect(self._add_task)
        input_layout.addWidget(btn_add)
        layout.addLayout(input_layout)

        self.list = QListWidget()
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.list, 1)

    def _add_task(self):
        text = self.input.text().strip()
        if not text:
            return
        self.dm.add_task(text)
        self.input.clear()
        self._load_tasks()

    def _load_tasks(self):
        self.list.clear()
        tasks = self.dm.get_tasks("all")
        for t in tasks:
            item = QListWidgetItem(t["text"])
            if t.get("completed"):
                item.setForeground(QColor(C_GRAY))
                font = item.font()
                font.setStrikeOut(True)
                item.setFont(font)
            else:
                if t.get("priority") == "high":
                    item.setForeground(QColor("#ff4444"))
            item.setData(Qt.ItemDataRole.UserRole, t["id"])
            self.list.addItem(item)

    def _show_context_menu(self, pos):
        item = self.list.itemAt(pos)
        if not item:
            return

        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.setStyleSheet(f"background-color: {C_PANEL}; color: {C_WHITE}; border: 1px solid {C_BORDER};")

        toggle_action = menu.addAction("Toggle Complete")
        delete_action = menu.addAction("Delete")

        action = menu.exec(self.list.mapToGlobal(pos))
        if action == toggle_action:
            task_id = item.data(Qt.ItemDataRole.UserRole)
            tasks = self.dm.get_tasks("all")
            for t in tasks:
                if t["id"] == task_id:
                    self.dm.update_task(task_id, completed=not t.get("completed"))
                    break
            self._load_tasks()
        elif action == delete_action:
            task_id = item.data(Qt.ItemDataRole.UserRole)
            self.dm.delete_task(task_id)
            self._load_tasks()


class NotesPage(QWidget):
    def __init__(self, dm: DataManager):
        super().__init__()
        self.dm = dm
        self._build_ui()
        self._load_note()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("QUICK NOTES")
        title.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {C_WHITE}; letter-spacing: 2px;")
        layout.addWidget(title)

        self.editor = QPlainTextEdit()
        self.editor.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {C_INPUT}; color: {C_WHITE};
                border: 1px solid {C_BORDER}; border-radius: 4px;
                font-family: 'Consolas', monospace; font-size: 14px; padding: 10px;
            }}
        """)
        self.editor.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.editor, 1)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_note)

    def _load_note(self):
        notes = self.dm.get_notes()
        if notes:
            self.editor.setPlainText(notes[0].get("content", ""))

    def _on_text_changed(self):
        self._save_timer.start(1000)

    def _save_note(self):
        notes = self.dm.get_notes()
        if notes:
            self.dm.update_note(notes[0]["id"], self.editor.toPlainText())


class StatsPage(QWidget):
    def __init__(self, dm: DataManager):
        super().__init__()
        self.dm = dm
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("STATISTICS")
        title.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {C_WHITE}; letter-spacing: 2px;")
        layout.addWidget(title)

        self.stats_layout = QHBoxLayout()
        layout.addLayout(self.stats_layout)
        layout.addStretch()

    def refresh(self):
        # Clear existing
        while self.stats_layout.count():
            w = self.stats_layout.takeAt(0).widget()
            if w:
                w.deleteLater()

        sessions = self.dm.get_sessions()
        tasks = self.dm.get_tasks("completed")

        today = datetime.now().strftime("%Y-%m-%d")
        today_sessions = [
            s for s in sessions if s.get("date") == today and s.get("type") == "focus" and s.get("completed")
        ]
        today_mins = sum(s.get("duration", 0) for s in today_sessions) // 60
        tasks_done = sum(1 for t in tasks if t.get("completed_date", "").startswith(today))

        for label, val, color in [
            ("Focus Today", f"{today_mins}m", C_RED),
            ("Sessions", str(len(today_sessions)), C_YELLOW),
            ("Tasks Done", str(tasks_done), C_GREEN),
        ]:
            card = QFrame()
            card.setObjectName("Panel")
            card.setStyleSheet(f"background-color: {C_PANEL}; border: 1px solid {C_BORDER}; border-radius: 8px;")
            c_layout = QVBoxLayout(card)
            c_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            v_lbl = QLabel(str(val))
            v_lbl.setStyleSheet(f"font-size: 48px; font-weight: bold; color: {color};")
            c_layout.addWidget(v_lbl, alignment=Qt.AlignmentFlag.AlignCenter)

            t_lbl = QLabel(label)
            t_lbl.setStyleSheet(f"font-size: 14px; color: {C_GRAY};")
            c_layout.addWidget(t_lbl, alignment=Qt.AlignmentFlag.AlignCenter)

            self.stats_layout.addWidget(card)


# ==============================================================================
# MAIN WINDOW
# ==============================================================================
class FocusStudioWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1000, 700)
        self.setMinimumSize(800, 600)

        self.dm = DataManager()

        # Audio Player
        self.audio_output = QAudioOutput()
        self.audio_output.setVolume(self.dm.get_setting("voice_volume", 80) / 100.0)
        self.audio_player = QMediaPlayer()
        self.audio_player.setAudioOutput(self.audio_output)

        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar
        sidebar = QFrame()
        sidebar.setFixedWidth(220)
        sidebar.setStyleSheet(f"background-color: {C_PANEL}; border-right: 1px solid {C_BORDER};")
        s_layout = QVBoxLayout(sidebar)
        s_layout.setContentsMargins(10, 20, 10, 20)
        s_layout.setSpacing(8)

        logo = QLabel("RED TONGUE")
        logo.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {C_RED}; letter-spacing: 1px;")
        s_layout.addWidget(logo)
        sub = QLabel("FOCUS DECK")
        sub.setStyleSheet(f"font-size: 12px; color: {C_GRAY}; margin-bottom: 20px;")
        s_layout.addWidget(sub)

        self.stack = QStackedWidget()

        # Pages
        self.timer_page = TimerPage(self.dm, self.audio_player)
        self.tasks_page = TasksPage(self.dm)
        self.notes_page = NotesPage(self.dm)
        self.stats_page = StatsPage(self.dm)

        self.stack.addWidget(self.timer_page)
        self.stack.addWidget(self.tasks_page)
        self.stack.addWidget(self.notes_page)
        self.stack.addWidget(self.stats_page)

        # Nav Buttons
        self.nav_btns = []
        nav_items = [("⏱  Timer", 0), ("☑  Tasks", 1), ("📝  Notes", 2), ("📊  Stats", 3)]
        for text, idx in nav_items:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setStyleSheet(f"""
                QPushButton {{ background: transparent; color: {C_GRAY}; border: none; text-align: left; padding: 12px; border-radius: 4px; font-size: 14px; }}
                QPushButton:hover {{ background-color: #1a1a1a; color: {C_WHITE}; }}
                QPushButton:checked {{ background-color: {C_RED}; color: {C_WHITE}; font-weight: bold; }}
            """)
            btn.clicked.connect(lambda checked, i=idx: self._navigate(i))
            s_layout.addWidget(btn)
            self.nav_btns.append(btn)

        s_layout.addStretch()
        self.nav_btns[0].setChecked(True)

        main_layout.addWidget(sidebar)
        main_layout.addWidget(self.stack, 1)

    def _navigate(self, idx: int):
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self.nav_btns):
            btn.setChecked(i == idx)

        if idx == 3:  # Stats
            self.stats_page.refresh()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(f"""
        QMainWindow, QWidget {{ background-color: {C_BG}; color: {C_WHITE}; font-family: 'Segoe UI', sans-serif; }}
        QPushButton#Primary {{ background-color: {C_RED}; color: {C_WHITE}; border: none; border-radius: 4px; padding: 8px 16px; font-weight: bold; }}
        QPushButton#Primary:hover {{ background-color: {C_RED_HOVER}; }}
        QLineEdit {{ background-color: {C_INPUT}; border: 1px solid {C_BORDER}; color: {C_WHITE}; padding: 8px; border-radius: 4px; }}
    """)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(C_BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(C_WHITE))
    app.setPalette(palette)

    window = FocusStudioWindow()
    window.show()
    sys.exit(app.exec())
