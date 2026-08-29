#!/usr/bin/env python3
"""
ui_main.py
Main application window and UI components for the RedTongue Refactory.
Completely redesigned with modern UX principles: clear hierarchy, intuitive flows, generous spacing.
"""

import asyncio
import json
import os
import sys
import threading
from pathlib import Path

from PyQt6.QtCore import QProcess, Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import (
    QAction,
    QColor,
    QFont,
    QKeySequence,
    QShortcut,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QFileSystemModel,
    QIcon,
    QPalette,
    QBrush,
)
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
    QTabWidget,
    QScrollArea,
    QGroupBox,
    QMenu,
    QSizePolicy,
    QCompleter,
    QProgressBar,
    QStackedWidget,
    QComboBox,
)

from backend import AgentSwarm, SpeechToText, ToolLayer, load_config

# ==============================================================================
# THEME CONSTANTS - Modern Professional Dark Theme
# Optimized for readability, reduced eye strain, and clear visual hierarchy
# ==============================================================================

# Background layers (subtle differentiation)
C_BG_MAIN = "#1e1e2e"        # Main window background
C_BG_PANEL = "#252537"       # Panel backgrounds  
C_BG_SURFACE = "#2d2d44"     # Elevated surfaces/cards
C_BG_INPUT = "#35354f"       # Input fields

# Borders and dividers
C_BORDER_SUBTLE = "#3a3a5c"  # Subtle borders
C_BORDER_NORMAL = "#4a4a6a"  # Normal borders
C_BORDER_FOCUS = "#7aa2f7"   # Focus state borders

# Primary accent - Professional blue
C_PRIMARY = "#7aa2f7"        
C_PRIMARY_HOVER = "#89b4fa"
C_PRIMARY_ACTIVE = "#5e81e8"

# Secondary accent - Soft cyan
C_SECONDARY = "#73daca"
C_SECONDARY_HOVER = "#8ce6d8"

# Status colors (softer, less harsh)
C_SUCCESS = "#9ece6a"
C_WARNING = "#e0af68"
C_ERROR = "#f7768e"
C_INFO = "#7dcfff"

# Text colors (high contrast, easy reading)
C_TEXT_MAIN = "#ffffff"      
C_TEXT_SECONDARY = "#a9b1d6" 
C_TEXT_MUTED = "#565f89"     

# Syntax highlighting
C_KEYWORD = "#bb9af7"
C_STRING = "#9ece6a"
C_COMMENT = "#565f89"
C_FUNCTION = "#7aa2f7"
C_CLASS = "#e0af68"

QSS = f"""
/* ==========================================================================
   MAIN WINDOW - Clean, professional base
   ========================================================================== */
QMainWindow {{ 
    background-color: {C_BG_MAIN}; 
    color: {C_TEXT_MAIN}; 
    font-family: 'Inter', 'Segoe UI', sans-serif; 
    font-size: 13px; 
    line-height: 1.5;
}}

/* ==========================================================================
   PANELS & FRAMES - Subtle depth with soft shadows simulation
   ========================================================================== */
QFrame#Panel {{ 
    background-color: {C_BG_PANEL}; 
    border: 1px solid {C_BORDER_SUBTLE}; 
    border-radius: 8px; 
}}
QFrame#ControlPanel {{
    background-color: {C_BG_SURFACE};
    border: 1px solid {C_BORDER_NORMAL};
    border-radius: 10px;
}}
QFrame#Card {{
    background-color: {C_BG_SURFACE};
    border: 1px solid {C_BORDER_SUBTLE};
    border-radius: 8px;
}}

/* ==========================================================================
   MENU BAR - Clean, unobtrusive
   ========================================================================== */
QMenuBar {{
    background-color: {C_BG_MAIN};
    color: {C_TEXT_MAIN};
    border-bottom: 1px solid {C_BORDER_SUBTLE};
    padding: 6px 12px;
    font-weight: 500;
}}
QMenuBar::item {{
    padding: 6px 12px;
    border-radius: 4px;
}}
QMenuBar::item:selected {{
    background-color: {C_PRIMARY};
    color: {C_BG_MAIN};
}}
QMenu {{
    background-color: {C_BG_PANEL};
    border: 1px solid {C_BORDER_NORMAL};
    border-radius: 8px;
    padding: 8px;
}}
QMenu::item {{
    padding: 8px 24px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {C_PRIMARY};
    color: {C_BG_MAIN};
}}

/* ==========================================================================
   TOOLBAR - Modern, spacious
   ========================================================================== */
QToolBar {{
    background-color: {C_BG_PANEL};
    border: none;
    border-bottom: 1px solid {C_BORDER_SUBTLE};
    padding: 8px 12px;
    spacing: 8px;
    icon-size: 22px;
}}
QToolBar::separator {{
    width: 2px;
    background: {C_BORDER_NORMAL};
    margin: 6px 12px;
    border-radius: 1px;
}}
QToolButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 8px 12px;
    color: {C_TEXT_MAIN};
    font-weight: 500;
}}
QToolButton:hover {{
    background-color: {C_BG_SURFACE};
    border: 1px solid {C_BORDER_NORMAL};
}}
QToolButton:pressed {{
    background-color: {C_PRIMARY};
    color: {C_BG_MAIN};
}}
QToolButton::menu-indicator {{
    image: none;
}}

/* ==========================================================================
   FILE EXPLORER - Clear tree structure
   ========================================================================== */
QTreeView {{ 
    background-color: {C_BG_MAIN}; 
    border: 1px solid {C_BORDER_SUBTLE}; 
    color: {C_TEXT_MAIN}; 
    border-radius: 6px;
    padding: 6px;
    outline: none;
}}
QTreeView::item {{
    padding: 6px 8px;
    border-radius: 4px;
    border: 1px solid transparent;
}}
QTreeView::item:hover {{
    background-color: {C_BG_SURFACE};
    border-color: {C_BORDER_SUBTLE};
}}
QTreeView::item:selected {{ 
    background-color: {C_PRIMARY}; 
    color: {C_BG_MAIN};
    font-weight: 600;
}}
QTreeView::branch {{
    image: none;
}}
QTreeView::branch:has-children:closed {{
    image: none;
}}
QTreeView::branch:open:has-children {{
    image: none;
}}

/* ==========================================================================
   TAB WIDGET - Clean tab design
   ========================================================================== */
QTabWidget::pane {{ 
    border: 1px solid {C_BORDER_SUBTLE}; 
    background: {C_BG_MAIN}; 
    border-radius: 8px;
    padding: 4px;
}}
QTabBar::tab {{ 
    background: {C_BG_SURFACE}; 
    color: {C_TEXT_SECONDARY}; 
    padding: 10px 24px; 
    border: 1px solid {C_BORDER_SUBTLE}; 
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 4px;
    font-weight: 500;
}}
QTabBar::tab:hover {{
    background: {C_BG_PANEL};
    color: {C_TEXT_MAIN};
}}
QTabBar::tab:selected {{ 
    background: {C_BG_PANEL}; 
    color: {C_PRIMARY}; 
    border-bottom: 2px solid {C_PRIMARY};
}}

/* ==========================================================================
   BUTTONS - Clear hierarchy, obvious affordances
   ========================================================================== */
QPushButton {{ 
    background-color: {C_BG_SURFACE}; 
    color: {C_TEXT_MAIN}; 
    border: 1px solid {C_BORDER_NORMAL}; 
    border-radius: 6px; 
    padding: 10px 20px;
    font-weight: 500;
    min-width: 80px;
}}
QPushButton:hover {{ 
    background-color: {C_BG_PANEL};
    border: 1px solid {C_BORDER_FOCUS};
}}
QPushButton:pressed {{
    background-color: {C_PRIMARY};
    color: {C_BG_MAIN};
    border: 1px solid {C_PRIMARY};
}}
QPushButton#Primary {{ 
    background-color: {C_PRIMARY}; 
    color: {C_BG_MAIN}; 
    border: 1px solid {C_PRIMARY};
    font-weight: 600;
    padding: 10px 24px;
}}
QPushButton#Primary:hover {{ 
    background-color: {C_PRIMARY_HOVER}; 
    border: 1px solid {C_PRIMARY_HOVER};
}}
QPushButton#Primary:pressed {{
    background-color: {C_PRIMARY_ACTIVE};
}}
QPushButton#Secondary {{
    background-color: transparent;
    border: 1px solid {C_BORDER_NORMAL};
    color: {C_TEXT_SECONDARY};
}}
QPushButton#Secondary:hover {{
    background-color: {C_BG_SURFACE};
    color: {C_TEXT_MAIN};
    border: 1px solid {C_TEXT_SECONDARY};
}}
QPushButton#Success {{
    background-color: {C_SUCCESS};
    color: {C_BG_MAIN};
    border: 1px solid {C_SUCCESS};
    font-weight: 600;
}}
QPushButton#Success:hover {{
    background-color: #a8d986;
}}
QPushButton#Danger {{
    background-color: {C_ERROR};
    color: {C_BG_MAIN};
    border: 1px solid {C_ERROR};
}}
QPushButton#Danger:hover {{
    background-color: #ff8fa3;
}}
QPushButton:disabled {{
    background-color: {C_BG_SURFACE};
    color: {C_TEXT_MUTED};
    border: 1px solid {C_BORDER_SUBTLE};
}}

/* ==========================================================================
   INPUT FIELDS - Clear, focusable
   ========================================================================== */
QLineEdit {{ 
    background-color: {C_BG_INPUT}; 
    border: 1px solid {C_BORDER_NORMAL}; 
    color: {C_TEXT_MAIN}; 
    padding: 10px 14px; 
    border-radius: 6px;
    selection-background-color: {C_PRIMARY};
    font-size: 13px;
}}
QLineEdit:focus {{
    border: 1px solid {C_PRIMARY};
    outline: none;
}}
QLineEdit:placeholder {{
    color: {C_TEXT_MUTED};
}}
QComboBox {{
    background-color: {C_BG_INPUT};
    border: 1px solid {C_BORDER_NORMAL};
    color: {C_TEXT_MAIN};
    padding: 10px 14px;
    border-radius: 6px;
    min-width: 120px;
}}
QComboBox:hover {{
    border: 1px solid {C_BORDER_FOCUS};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background-color: {C_BG_PANEL};
    border: 1px solid {C_BORDER_NORMAL};
    selection-background-color: {C_PRIMARY};
    border-radius: 6px;
}}

/* ==========================================================================
   TEXT EDITORS - Readable, comfortable
   ========================================================================== */
QPlainTextEdit {{
    background-color: {C_BG_MAIN};
    color: {C_TEXT_MAIN};
    border: 1px solid {C_BORDER_SUBTLE};
    border-radius: 6px;
    padding: 12px;
    selection-background-color: {C_PRIMARY};
    selection-color: {C_BG_MAIN};
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 13px;
    line-height: 1.6;
}}
QPlainTextEdit:focus {{
    border: 1px solid {C_BORDER_FOCUS};
}}
QPlainTextEdit:placeholder {{
    color: {C_TEXT_MUTED};
}}

/* ==========================================================================
   TABLES - Clean data presentation
   ========================================================================== */
QTableWidget {{ 
    background-color: {C_BG_MAIN}; 
    gridline-color: {C_BORDER_SUBTLE}; 
    border: 1px solid {C_BORDER_SUBTLE};
    border-radius: 6px;
    alternate-background-color: {C_BG_PANEL};
}}
QTableWidget::item {{
    padding: 8px;
    border: none;
}}
QTableWidget::item:selected {{ 
    background-color: {C_PRIMARY}; 
    color: {C_BG_MAIN};
    font-weight: 600;
}}
QTableWidget::item:hover {{
    background-color: {C_BG_SURFACE};
}}
QHeaderView::section {{ 
    background-color: {C_BG_SURFACE}; 
    color: {C_TEXT_SECONDARY}; 
    padding: 10px; 
    border: 1px solid {C_BORDER_SUBTLE};
    font-weight: 600;
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 0.5px;
}}

/* ==========================================================================
   SCROLL BARS - Unobtrusive, modern
   ========================================================================== */
QScrollBar:vertical {{ 
    background: {C_BG_MAIN}; 
    width: 12px; 
    border-radius: 6px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{ 
    background: {C_BORDER_NORMAL}; 
    border-radius: 6px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {C_TEXT_SECONDARY};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}
QScrollBar:horizontal {{ 
    background: {C_BG_MAIN}; 
    height: 12px; 
    border-radius: 6px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{ 
    background: {C_BORDER_NORMAL}; 
    border-radius: 6px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {C_TEXT_SECONDARY};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ==========================================================================
   STATUS BAR - Informative, not distracting
   ========================================================================== */
QStatusBar {{ 
    background-color: {C_BG_PANEL}; 
    color: {C_TEXT_SECONDARY}; 
    border-top: 1px solid {C_BORDER_SUBTLE};
    padding: 6px 12px;
    font-size: 12px;
}}

/* ==========================================================================
   GROUP BOX - Organized sections
   ========================================================================== */
QGroupBox {{
    background-color: {C_BG_PANEL};
    border: 1px solid {C_BORDER_SUBTLE};
    border-radius: 8px;
    margin-top: 16px;
    padding-top: 16px;
    font-weight: 600;
    color: {C_TEXT_MAIN};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 10px;
    color: {C_PRIMARY};
    background-color: {C_BG_PANEL};
}}

/* ==========================================================================
   LABELS - Clear typography hierarchy
   ========================================================================== */
QLabel {{
    color: {C_TEXT_MAIN};
}}
QLabel#Heading {{
    font-size: 18px;
    font-weight: 700;
    color: {C_TEXT_MAIN};
    letter-spacing: -0.5px;
}}
QLabel#SubHeading {{
    font-size: 14px;
    font-weight: 600;
    color: {C_TEXT_SECONDARY};
}}
QLabel#Muted {{
    color: {C_TEXT_MUTED};
    font-size: 12px;
}}
QLabel#StatusGood {{
    color: {C_SUCCESS};
    font-weight: 600;
}}
QLabel#StatusWarning {{
    color: {C_WARNING};
    font-weight: 600;
}}
QLabel#StatusError {{
    color: {C_ERROR};
    font-weight: 600;
}}

/* ==========================================================================
   PROGRESS BAR - Smooth, modern
   ========================================================================== */
QProgressBar {{
    background-color: {C_BG_INPUT};
    border: 1px solid {C_BORDER_SUBTLE};
    border-radius: 6px;
    text-align: center;
    color: {C_TEXT_MAIN};
    font-weight: 600;
    height: 8px;
}}
QProgressBar::chunk {{
    background-color: {C_PRIMARY};
    border-radius: 4px;
}}

/* ==========================================================================
   CHAT MESSAGE BUBBLES - Clear conversation flow
   ========================================================================== */
QTextEdit {{
    background-color: {C_BG_MAIN};
    color: {C_TEXT_MAIN};
    border: 1px solid {C_BORDER_SUBTLE};
    border-radius: 8px;
    padding: 12px;
    selection-background-color: {C_PRIMARY};
}}
QTextEdit:focus {{
    border: 1px solid {C_BORDER_FOCUS};
}}
"""


# ==============================================================================
# WORKERS
# ==============================================================================
class ChatWorker(QThread):
    """Streams AI responses and tool executions."""

    token_received = pyqtSignal(str)
    tool_executed = pyqtSignal(str, str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(
        self, swarm: AgentSwarm, message: str, history: list, context: str = ""
    ):
        super().__init__()
        self.swarm = swarm
        self.message = message
        self.history = history
        self.context = context

    def run(self):
        """Executes AI agent streaming in background thread with asyncio event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:

            async def process():
                async for event in self.swarm.run_main_agent(
                    self.message, self.history, rag_context=self.context
                ):
                    try:
                        data = json.loads(event)
                        if data["type"] == "stream":
                            self.token_received.emit(data["content"])
                        elif data["type"] == "tool":
                            self.tool_executed.emit(data["name"], data["output"][:200])
                        elif data["type"] == "error":
                            self.error_signal.emit(data["content"])
                        elif data["type"] == "done":
                            self.finished_signal.emit()
                    except json.JSONDecodeError:
                        pass

            loop.run_until_complete(process())
        except Exception as e:
            self.error_signal.emit(str(e))
        finally:
            loop.close()


class LintWorker(QThread):
    """Chunked background linting to prevent RAM spikes."""

    batch_ready = pyqtSignal(list)
    progress = pyqtSignal(str)
    finished_lint = pyqtSignal(dict)

    def __init__(self, project_path: Path, batch_size: int = 50):
        super().__init__()
        self.project_path = project_path
        self.batch_size = batch_size
        self._is_running = True

    def run(self):
        """Discovers and analyzes Python files in batches, emitting issues progressively."""
        try:
            self.progress.emit("Discovering files...")
            files = []
            for root, _, filenames in os.walk(self.project_path):
                if ".git" in root or "__pycache__" in root:
                    continue
                for f in filenames:
                    if f.endswith(".py"):
                        files.append(os.path.join(root, f))

            total = len(files)
            for i in range(0, total, self.batch_size):
                if not self._is_running:
                    return
                batch = files[i : i + self.batch_size]
                self.progress.emit(f"Parsing batch {i // self.batch_size + 1}...")

                # Mock AST analysis for skeleton (replace with engine.ast_pass)
                issues = []
                for f in batch:
                    try:
                        with open(f, encoding="utf-8") as fh:
                            content = fh.read()
                        if "import *" in content:
                            issues.append(
                                {
                                    "code": "AST-IMP001",
                                    "severity": "HIGH",
                                    "path": f,
                                    "line": 1,
                                    "msg": "Wildcard import detected.",
                                }
                            )
                    except Exception:
                        pass

                self.batch_ready.emit(issues)
                self.msleep(100)  # Yield to OS

            self.finished_lint.emit({"total_files": total, "total_issues": 0})
        except Exception as e:
            self.progress.emit(f"Error: {e}")

    def stop(self):
        """Stops the linting worker."""
        self._is_running = False


# ==============================================================================
# UI COMPONENTS
# ==============================================================================
class PythonHighlighter(QSyntaxHighlighter):
    """Basic Python syntax highlighting."""

    def __init__(self, document):
        super().__init__(document)
        self.rules = []
        kw_fmt = QTextCharFormat()
        kw_fmt.setForeground(QColor("#D4A76A"))
        kw_fmt.setFontWeight(QFont.Weight.Bold)

        for kw in [
            "def",
            "class",
            "import",
            "from",
            "return",
            "if",
            "elif",
            "else",
            "for",
            "while",
            "try",
            "except",
            "with",
            "as",
            "pass",
            "True",
            "False",
            "None",
        ]:
            self.rules.append((f"\\b{kw}\\b", kw_fmt))

    def highlightBlock(self, text):
        """Applies syntax highlighting rules to a text block."""
        for pattern, fmt in self.rules:
            import re

            for match in re.finditer(pattern, text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)


class CodeEditor(QPlainTextEdit):
    """Native code editor with line numbers."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(QFont("Consolas", 11))
        self.setStyleSheet(
            f"background-color: {C_BG_PRIMARY}; color: {C_TEXT_PRIMARY}; border: 1px solid {C_BORDER}; selection-background-color: {C_RED_PRIMARY};"
        )
        self.highlighter = PythonHighlighter(self.document())
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

    def load_file(self, path: Path):
        """Loads a file into the editor with syntax highlighting."""
        try:
            self.setPlainText(path.read_text(encoding="utf-8"))
            self.document().setModified(False)
        except Exception as e:
            self.setPlainText(f"# Error loading file: {e}")

    def save_file(self, path: Path):
        """Saves editor content to file and marks document as unmodified."""
        try:
            path.write_text(self.toPlainText(), encoding="utf-8")
            self.document().setModified(False)
            return True
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))
            return False


class ChatPanel(QWidget):
    """AI Chat interface with Speech-to-Text - Redesigned for clarity."""

    def __init__(self, swarm: AgentSwarm, stt: SpeechToText, parent=None):
        super().__init__(parent)
        self.swarm = swarm
        self.stt = stt
        self.history = []
        self.worker = None
        self._build_ui()

    def _build_ui(self):
        """Builds the chat panel UI with clear visual hierarchy."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Chat display area with message bubbles
        self.display = QPlainTextEdit()
        self.display.setReadOnly(True)
        self.display.setPlaceholderText("AI responses will appear here...")
        self.display.setStyleSheet(f"""
            background: {C_BG_MAIN}; 
            color: {C_TEXT_MAIN}; 
            border: 1px solid {C_BORDER_SUBTLE}; 
            font-family: 'JetBrains Mono', Consolas, monospace; 
            font-size: 13px; 
            border-radius: 8px;
            padding: 12px;
        """)
        layout.addWidget(self.display, 1)

        # Input area with clear affordances
        input_card = QFrame()
        input_card.setObjectName("Card")
        input_layout = QHBoxLayout(input_card)
        input_layout.setContentsMargins(12, 12, 12, 12)
        input_layout.setSpacing(12)
        
        # Mic button with clear icon
        self.mic_btn = QPushButton("🎤")
        self.mic_btn.setFixedSize(48, 48)
        self.mic_btn.setToolTip("Click to use speech-to-text")
        self.mic_btn.clicked.connect(self._activate_stt)
        input_layout.addWidget(self.mic_btn)

        # Input field with clear placeholder
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type your message or use voice input...")
        self.input.returnPressed.connect(self._send_message)
        self.input.setStyleSheet(f"""
            background-color: {C_BG_INPUT};
            border: 1px solid {C_BORDER_NORMAL};
            color: {C_TEXT_MAIN};
            padding: 12px 16px;
            border-radius: 8px;
            font-size: 13px;
        """)
        input_layout.addWidget(self.input, 1)

        # Send button with primary styling
        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("Primary")
        self.send_btn.setFixedSize(80, 48)
        self.send_btn.clicked.connect(self._send_message)
        input_layout.addWidget(self.send_btn)

        layout.addWidget(input_card)

    def _activate_stt(self):
        """Activates speech-to-text listening in background thread."""
        self.mic_btn.setText("🎙️")
        self.mic_btn.setEnabled(False)
        self.mic_btn.setStyleSheet("background-color: #e0af68; color: #1a1a2e;")
        threading.Thread(target=self._stt_worker, daemon=True).start()

    def _stt_worker(self):
        """Background worker for speech-to-text transcription."""
        text = self.stt.listen_and_transcribe()
        from PyQt6.QtCore import QMetaObject, Qt

        QMetaObject.invokeMethod(
            self,
            "_update_input",
            Qt.ConnectionType.QueuedConnection,
            QMetaObject.Connection(lambda t=text: self.input.setText(t) if t else None),
        )
        self.mic_btn.setText("🎤")
        self.mic_btn.setEnabled(True)
        self.mic_btn.setStyleSheet("")

    def _update_input(self, text):
        """Updates input field with transcribed text from STT."""
        if text:
            self.input.setText(text)

    def _send_message(self):
        """Sends user message to AI agent and starts streaming response."""
        text = self.input.text().strip()
        if not text or (self.worker and self.worker.isRunning()):
            return

        self.input.clear()
        self.display.appendPlainText(f"▸ You: {text}\n")
        self.history.append({"role": "user", "content": text})

        self.worker = ChatWorker(self.swarm, text, self.history)
        self.worker.token_received.connect(self._append_token)
        self.worker.tool_executed.connect(self._append_tool)
        self.worker.finished_signal.connect(self._chat_finished)
        self.worker.error_signal.connect(self._append_error)
        self.worker.start()

    def _append_token(self, token):
        """Appends a token to the chat display during streaming."""
        cursor = self.display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(token)
        self.display.setTextCursor(cursor)

    def _append_tool(self, name, output):
        """Appends tool execution result to chat display."""
        self.display.appendPlainText(f"\n⚙️ [{name}] {output}\n")

    def _append_error(self, error):
        """Appends error message to chat display."""
        self.display.appendPlainText(f"\n⚠️ Error: {error}\n")

    def _chat_finished(self):
        """Handles chat stream completion."""
        self.display.appendPlainText("\n" + "─" * 50 + "\n")
        self.history.append({"role": "assistant", "content": "Response complete."})


class LintPanel(QWidget):
    """Forensic lint results table - Redesigned for clarity."""

    def __init__(self, on_push_to_ai, parent=None):
        super().__init__(parent)
        self.on_push_to_ai = on_push_to_ai
        self.all_issues = []
        self.worker = None
        self._build_ui()

    def _build_ui(self):
        """Builds the lint panel UI with clear controls and readable results."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Header card with status and controls
        header = QFrame()
        header.setObjectName("ControlPanel")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(16, 16, 16, 16)
        
        self.status_lbl = QLabel("⏸ Engine Idle")
        self.status_lbl.setObjectName("SubHeading")
        h_layout.addWidget(self.status_lbl)
        h_layout.addStretch()

        self.run_btn = QPushButton("▶ Run Analysis")
        self.run_btn.setObjectName("Primary")
        self.run_btn.clicked.connect(self._start_lint)
        h_layout.addWidget(self.run_btn)

        self.push_btn = QPushButton("→ Push to AI")
        self.push_btn.setObjectName("Secondary")
        self.push_btn.clicked.connect(self._push_to_ai)
        h_layout.addWidget(self.push_btn)
        layout.addWidget(header)

        # Results table with better readability
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Severity", "Code", "File", "Line", "Message"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(f"""
            background-color: {C_BG_MAIN}; 
            color: {C_TEXT_MAIN}; 
            gridline-color: {C_BORDER_SUBTLE}; 
            border: 1px solid {C_BORDER_SUBTLE}; 
            border-radius: 8px;
        """)
        layout.addWidget(self.table, 1)

    def _start_lint(self):
        """Starts or stops the forensic lint worker."""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            return
        self.table.setRowCount(0)
        self.all_issues = []
        self.run_btn.setText("⏹ Stop Analysis")
        self.worker = LintWorker(Path.cwd())
        self.worker.batch_ready.connect(self._on_batch)
        self.worker.progress.connect(self.status_lbl.setText)
        self.worker.finished_lint.connect(self._on_finished)
        self.worker.start()

    def _on_batch(self, issues):
        """Handles batch of issues from worker and updates table display."""
        self.all_issues.extend(issues)
        for issue in issues:
            row = self.table.rowCount()
            self.table.insertRow(row)
            sev_color = C_ERROR if issue["severity"] == "HIGH" else C_WARNING
            sev_item = QTableWidgetItem(issue["severity"])
            sev_item.setForeground(QColor(sev_color))
            self.table.setItem(row, 0, sev_item)
            self.table.setItem(row, 1, QTableWidgetItem(issue["code"]))
            self.table.setItem(row, 2, QTableWidgetItem(issue["path"]))
            self.table.setItem(row, 3, QTableWidgetItem(str(issue["line"])))
            self.table.setItem(row, 4, QTableWidgetItem(issue["msg"]))

    def _on_finished(self, summary):
        """Handles lint completion and updates status display."""
        self.run_btn.setText("▶ Run Analysis")
        self.status_lbl.setText(f"✓ Complete: {len(self.all_issues)} issues found")
        if len(self.all_issues) > 0:
            self.status_lbl.setObjectName("StatusWarning")
        else:
            self.status_lbl.setObjectName("StatusGood")

    def _push_to_ai(self):
        """Pushes top issues to AI chat for analysis."""
        if not self.all_issues:
            return
        critical = [
            i for i in self.all_issues if i["severity"] in ("HIGH", "CRITICAL")
        ][:20]
        if not critical:
            critical = self.all_issues[:20]
        prompt = "Forensic lint results:\n\n"
        for i in critical:
            prompt += f"- [{i['code']}] {i['path']}:{i['line']} -> {i['msg']}\n"
        self.on_push_to_ai(prompt)


# ==============================================================================
# MAIN WINDOW
# ==============================================================================
class RefactoryMainWindow(QMainWindow):
    """Main application window for RedTongue Refactory with file explorer, editor, lint, and AI chat."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("RedTongue Refactory v4.0.0")
        self.resize(1400, 900)

        self.cfg = load_config()
        self.tool_layer = ToolLayer(str(Path.cwd()))
        self.swarm = AgentSwarm(self.tool_layer)
        self.stt = SpeechToText()

        self.current_project = Path.cwd()
        self.current_file = None

        self._build_ui()
        self._build_menus()
        self._setup_shortcuts()

    def _build_ui(self):
        """Builds the main UI with modern layout, clear sections, and intuitive spacing."""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Main content splitter with generous proportions
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.splitter, 1)

        # 1. Left Panel - File Explorer
        self.explorer = QFrame()
        self.explorer.setObjectName("Panel")
        exp_layout = QVBoxLayout(self.explorer)
        exp_layout.setContentsMargins(12, 12, 12, 12)
        exp_layout.setSpacing(12)
        
        # Explorer header with clear typography
        exp_header = QLabel("📁 Project Explorer")
        exp_header.setObjectName("Heading")
        exp_layout.addWidget(exp_header)
        
        self.file_tree = QTreeView()
        self.file_model = QFileSystemModel()
        self.file_model.setRootPath(str(self.current_project))
        self.file_tree.setModel(self.file_model)
        self.file_tree.setRootIndex(self.file_model.index(str(self.current_project)))
        self.file_tree.setHeaderHidden(True)
        self.file_tree.setAnimated(True)
        self.file_tree.doubleClicked.connect(self._open_file)
        exp_layout.addWidget(self.file_tree, 1)
        self.splitter.addWidget(self.explorer)

        # 2. Center Panel - Editor + Lint
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(12)
        
        self.center_splitter = QSplitter(Qt.Orientation.Vertical)
        
        # Editor section
        editor_frame = QFrame()
        editor_layout = QVBoxLayout(editor_frame)
        editor_layout.setContentsMargins(12, 12, 12, 12)
        editor_layout.setSpacing(12)
        
        editor_header = QLabel("📝 Code Editor")
        editor_header.setObjectName("Heading")
        editor_layout.addWidget(editor_header)
        
        self.editor = CodeEditor()
        self.editor.setPlaceholderText("Open a file to start editing...")
        editor_layout.addWidget(self.editor, 1)
        self.center_splitter.addWidget(editor_frame)

        # Lint section
        self.lint_panel = LintPanel(self._push_lint_to_chat)
        self.center_splitter.addWidget(self.lint_panel)
        self.center_splitter.setSizes([500, 350])
        
        center_layout.addWidget(self.center_splitter, 1)
        self.splitter.addWidget(center_widget)

        # 3. Right Panel - AI Chat
        chat_widget = QWidget()
        chat_layout = QVBoxLayout(chat_widget)
        chat_layout.setContentsMargins(12, 12, 12, 12)
        chat_layout.setSpacing(12)
        
        # Chat header with clear typography
        chat_header = QLabel("🤖 AI Assistant")
        chat_header.setObjectName("Heading")
        chat_layout.addWidget(chat_header)
        
        self.chat_panel = ChatPanel(self.swarm, self.stt)
        chat_layout.addWidget(self.chat_panel, 1)
        self.splitter.addWidget(chat_widget)

        self.splitter.setSizes([280, 720, 450])

        # Status bar with helpful info
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("✓ Ready — RedTongue Refactory v4.0.0")

        # Create toolbar (after all components are initialized)
        self._build_toolbar()

    def _build_toolbar(self):
        """Builds the main toolbar with quick access actions."""
        self.toolbar = self.addToolBar("Main Toolbar")
        self.toolbar.setMovable(False)
        
        # New Project action
        new_proj_action = QAction("📁", self)
        new_proj_action.setToolTip("New Project")
        new_proj_action.triggered.connect(self._open_project)
        self.toolbar.addAction(new_proj_action)
        
        # Open File action
        open_action = QAction("📂", self)
        open_action.setToolTip("Open File (Ctrl+O)")
        open_action.triggered.connect(self._open_project)
        self.toolbar.addAction(open_action)
        
        # Save action
        save_action = QAction("💾", self)
        save_action.setToolTip("Save (Ctrl+S)")
        save_action.triggered.connect(self._save_file)
        self.toolbar.addAction(save_action)
        
        self.toolbar.addSeparator()
        
        # Run Lint action
        lint_action = QAction("🔍", self)
        lint_action.setToolTip("Run Forensic Lint (Ctrl+Shift+L)")
        lint_action.triggered.connect(self.lint_panel._start_lint)
        self.toolbar.addAction(lint_action)
        
        self.toolbar.addSeparator()
        
        # Decks button with menu
        decks_btn = QToolButton()
        decks_btn.setText("🃏 Decks ▼")
        decks_btn.setObjectName("Secondary")
        decks_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        deck_menu = QMenu(self)
        for name, script in [
            ("🎯 Focus Studio", "ui_focus.py"),
            ("⚗️ Crucible (Compiler)", "ui_crucible.py"),
            ("🔪 Ripper (Downloader)", "ui_ripper.py"),
            ("🧪 Alchemist (Converter)", "ui_alchemist.py"),
            ("🎼 Maestro (Mastering)", "ui_alchemist.py"),
            ("📦 PyLib (Packages)", "ui_pylib.py"),
        ]:
            deck_action = QAction(name, self)
            deck_action.triggered.connect(lambda checked, s=script: self._launch_deck(s))
            deck_menu.addAction(deck_action)
        decks_btn.setMenu(deck_menu)
        self.toolbar.addWidget(decks_btn)
        
        # Add spacer to push status indicator to the right
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.toolbar.addWidget(spacer)
        
        # Status indicator
        status_indicator = QLabel("● Online")
        status_indicator.setStyleSheet(f"color: {C_SUCCESS}; font-weight: 600; padding: 4px;")
        self.toolbar.addWidget(status_indicator)

    def _build_menus(self):
        """Build the main window's File and Decks menus with their associated actions and shortcuts."""
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        open_action = file_menu.addAction("📁 Open Project...")
        open_action.setShortcut(QKeySequence("Ctrl+O"))
        open_action.triggered.connect(self._open_project)
        
        save_action = file_menu.addAction("💾 Save")
        save_action.setShortcut(QKeySequence("Ctrl+S"))
        save_action.triggered.connect(self._save_file)
        
        file_menu.addSeparator()
        
        exit_action = file_menu.addAction("❌ Exit")
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)

        decks_menu = menubar.addMenu("&Decks")
        for name, script in [
            ("🎯 Focus Studio", "ui_focus.py"),
            ("⚗️ Crucible (Compiler)", "ui_crucible.py"),
            ("🔪 Ripper (Downloader)", "ui_ripper.py"),
            ("🧪 Alchemist (Converter)", "ui_alchemist.py"),
            ("🎼 Maestro (Mastering)", "ui_alchemist.py"),
            ("📦 PyLib (Packages)", "ui_pylib.py"),
        ]:
            action = QAction(name, self)
            action.triggered.connect(lambda checked, s=script: self._launch_deck(s))
            decks_menu.addAction(action)

    def _setup_shortcuts(self):
        """Sets up keyboard shortcuts for the application."""
        QShortcut(QKeySequence("Ctrl+Shift+L"), self, self.lint_panel._start_lint)

    def _open_project(self):
        """
        Open a project folder and rebind the workspace tools to it.
        """
        path = QFileDialog.getExistingDirectory(self, "Open Project Folder")
        if path:
            self.current_project = Path(path)
            self.file_model.setRootPath(str(self.current_project))
            self.file_tree.setRootIndex(
                self.file_model.index(str(self.current_project))
            )
            # Rebind ToolLayer and AgentSwarm to new workspace (B4 fix)
            self.tool_layer = ToolLayer(str(self.current_project))
            self.swarm = AgentSwarm(self.tool_layer)
            # Update ChatPanel.swarm reference to use new swarm instance
            if hasattr(self, 'chat_panel') and self.chat_panel:
                self.chat_panel.swarm = self.swarm
            self.status_bar.showMessage(f"Project loaded: {path}")

    def _open_file(self, index):
        """Opens a file from the file tree into the editor."""
        path = Path(self.file_model.filePath(index))
        if path.is_file() and path.suffix == ".py":
            self.editor.load_file(path)
            self.current_file = path
            self.setWindowTitle(f"RedTongue Refactory - {path.name}")

    def _save_file(self):
        """Saves the current file in the editor."""
        if self.current_file:
            if self.editor.save_file(self.current_file):
                self.status_bar.showMessage(f"Saved: {self.current_file.name}")

    def _launch_deck(self, script_name):
        """Launches a RedTongue deck application in a separate process."""
        script_path = Path(__file__).parent / script_name
        if script_path.exists():
            QProcess.startDetached(sys.executable, [str(script_path)])
            self.status_bar.showMessage(f"Launched: {script_name}")
        else:
            QMessageBox.warning(
                self,
                "Deck Missing",
                f"Could not find {script_name} in the project root.",
            )

    def _push_lint_to_chat(self, prompt):
        """Pushes lint results to AI chat panel as a prompt."""
        self.chat_panel.input.setText(prompt)
        self.chat_panel.input.setFocus()
