#!/usr/bin/env python3
"""
ui_main.py
Main application window and UI components for the RedTongue Refactory.
Handles layout, deck launching, AI chat streaming, and forensic linting.
"""

import asyncio
import json
import os
import sys
import threading
from pathlib import Path

from PyQt6.QtCore import QProcess, Qt, QThread, pyqtSignal
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
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from backend import AgentSwarm, SpeechToText, ToolLayer, load_config

# ==============================================================================
# THEME CONSTANTS
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

QSS = f"""
QMainWindow, QWidget {{ background-color: {C_BG}; color: {C_WHITE}; font-family: 'Segoe UI', sans-serif; font-size: 13px; }}
QFrame#Panel {{ background-color: {C_PANEL}; border: 1px solid {C_BORDER}; border-radius: 4px; }}
QTreeView {{ background-color: #0a0a0a; border: 1px solid {C_BORDER}; color: {C_WHITE}; }}
QTreeView::item:selected {{ background-color: {C_RED}; color: {C_WHITE}; }}
QTabWidget::pane {{ border: 1px solid {C_BORDER}; background: {C_BG}; }}
QTabBar::tab {{ background: {C_INPUT}; color: {C_GRAY}; padding: 8px 16px; border: 1px solid {C_BORDER}; border-bottom: none; }}
QTabBar::tab:selected {{ background: {C_BG}; color: {C_WHITE}; border-bottom: 2px solid {C_RED}; }}
QPushButton {{ background-color: {C_INPUT}; color: {C_WHITE}; border: 1px solid {C_BORDER}; border-radius: 4px; padding: 6px 16px; }}
QPushButton:hover {{ background-color: #2a2a2a; }}
QPushButton#Primary {{ background-color: {C_RED}; color: {C_WHITE}; border: 1px solid {C_RED_HOVER}; }}
QPushButton#Primary:hover {{ background-color: {C_RED_HOVER}; }}
QLineEdit {{ background-color: {C_INPUT}; border: 1px solid {C_BORDER}; color: {C_WHITE}; padding: 6px; border-radius: 4px; }}
QTableWidget {{ background-color: #0a0a0a; gridline-color: {C_BORDER}; border: 1px solid {C_BORDER}; }}
QTableWidget::item:selected {{ background-color: {C_RED}; }}
QHeaderView::section {{ background-color: {C_INPUT}; color: {C_GRAY}; padding: 4px; border: 1px solid {C_BORDER}; }}
QScrollBar:vertical {{ background: {C_BG}; width: 10px; }}
QScrollBar::handle:vertical {{ background: #333333; border-radius: 5px; }}
QStatusBar {{ background-color: #0a0a0a; color: {C_GRAY}; border-top: 1px solid {C_BORDER}; }}
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
            f"background-color: {C_BG}; color: {C_WHITE}; border: none; selection-background-color: {C_RED};"
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
    """AI Chat interface with Speech-to-Text."""

    def __init__(self, swarm: AgentSwarm, stt: SpeechToText, parent=None):
        super().__init__(parent)
        self.swarm = swarm
        self.stt = stt
        self.history = []
        self.worker = None
        self._build_ui()

    def _build_ui(self):
        """Builds the chat panel UI with display area and input controls."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.display = QPlainTextEdit()
        self.display.setReadOnly(True)
        self.display.setStyleSheet(
            f"background: #050505; color: {C_WHITE}; border: none; font-family: Consolas;"
        )
        layout.addWidget(self.display, 1)

        input_layout = QHBoxLayout()
        self.mic_btn = QPushButton("🎤")
        self.mic_btn.setFixedWidth(40)
        self.mic_btn.clicked.connect(self._activate_stt)
        input_layout.addWidget(self.mic_btn)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask the Swarm... (Enter to send)")
        self.input.returnPressed.connect(self._send_message)
        input_layout.addWidget(self.input, 1)

        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("Primary")
        self.send_btn.clicked.connect(self._send_message)
        input_layout.addWidget(self.send_btn)

        layout.addLayout(input_layout)

    def _activate_stt(self):
        """Activates speech-to-text listening in background thread."""
        self.mic_btn.setText("🎙️...")
        self.mic_btn.setEnabled(False)
        # Run STT in a separate thread to avoid blocking UI
        threading.Thread(target=self._stt_worker, daemon=True).start()

    def _stt_worker(self):
        """Background worker for speech-to-text transcription."""
        text = self.stt.listen_and_transcribe()
        # Update UI on main thread
        from PyQt6.QtCore import QMetaObject, Qt

        QMetaObject.invokeMethod(
            self,
            "_update_input",
            Qt.ConnectionType.QueuedConnection,
            QMetaObject.Connection(lambda t=text: self.input.setText(t) if t else None),
        )
        self.mic_btn.setText("🎤")
        self.mic_btn.setEnabled(True)

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
        self.display.appendPlainText(f"[USER] {text}\n")
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
        self.display.appendPlainText(f"\n[TOOL: {name}] {output}\n")

    def _append_error(self, error):
        """Appends error message to chat display."""
        self.display.appendPlainText(f"\n[ERROR] {error}\n")

    def _chat_finished(self):
        """Handles chat stream completion."""
        self.display.appendPlainText("\n")
        self.history.append({"role": "assistant", "content": "Response complete."})


class LintPanel(QWidget):
    """Forensic lint results table."""

    def __init__(self, on_push_to_ai, parent=None):
        super().__init__(parent)
        self.on_push_to_ai = on_push_to_ai
        self.all_issues = []
        self.worker = None
        self._build_ui()

    def _build_ui(self):
        """Builds the lint panel UI with control buttons and results table."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QFrame()
        h_layout = QHBoxLayout(header)
        self.status_lbl = QLabel("Engine Idle")
        h_layout.addWidget(self.status_lbl)
        h_layout.addStretch()

        self.run_btn = QPushButton("RUN FORENSIC LINT")
        self.run_btn.setObjectName("Primary")
        self.run_btn.clicked.connect(self._start_lint)
        h_layout.addWidget(self.run_btn)

        self.push_btn = QPushButton("PUSH TO AI")
        self.push_btn.clicked.connect(self._push_to_ai)
        h_layout.addWidget(self.push_btn)
        layout.addWidget(header)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Severity", "Code", "File", "Line", "Message"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table, 1)

    def _start_lint(self):
        """Starts or stops the forensic lint worker."""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            return
        self.table.setRowCount(0)
        self.all_issues = []
        self.run_btn.setText("STOP LINT")
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
            sev_color = "#ff4444" if issue["severity"] == "HIGH" else "#ffaa00"
            sev_item = QTableWidgetItem(issue["severity"])
            sev_item.setForeground(QColor(sev_color))
            self.table.setItem(row, 0, sev_item)
            self.table.setItem(row, 1, QTableWidgetItem(issue["code"]))
            self.table.setItem(row, 2, QTableWidgetItem(issue["path"]))
            self.table.setItem(row, 3, QTableWidgetItem(str(issue["line"])))
            self.table.setItem(row, 4, QTableWidgetItem(issue["msg"]))

    def _on_finished(self, summary):
        """Handles lint completion and updates status display."""
        self.run_btn.setText("RUN FORENSIC LINT")
        self.status_lbl.setText(f"Complete: {len(self.all_issues)} issues found.")

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
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.splitter, 1)

        # 1. Explorer
        self.explorer = QFrame()
        self.explorer.setObjectName("Panel")
        exp_layout = QVBoxLayout(self.explorer)
        exp_layout.setContentsMargins(0, 0, 0, 0)
        self.file_tree = QTreeView()
        self.file_model = QFileSystemModel()
        self.file_model.setRootPath(str(self.current_project))
        self.file_tree.setModel(self.file_model)
        self.file_tree.setRootIndex(self.file_model.index(str(self.current_project)))
        self.file_tree.setHeaderHidden(True)
        self.file_tree.doubleClicked.connect(self._open_file)
        exp_layout.addWidget(self.file_tree)
        self.splitter.addWidget(self.explorer)

        # 2. Center (Editor + Lint)
        self.center_splitter = QSplitter(Qt.Orientation.Vertical)
        self.editor = CodeEditor()
        self.center_splitter.addWidget(self.editor)

        self.lint_panel = LintPanel(self._push_lint_to_chat)
        self.center_splitter.addWidget(self.lint_panel)
        self.splitter.addWidget(self.center_splitter)

        # 3. Right (Chat)
        self.chat_panel = ChatPanel(self.swarm, self.stt)
        self.splitter.addWidget(self.chat_panel)

        self.splitter.setSizes([250, 650, 400])

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready.")

    def _build_menus(self):
        """Build the main window's File and Decks menus with their associated actions and shortcuts."""
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        file_menu.addAction(
            "Open Project...", self._open_project, QKeySequence("Ctrl+O")
        )
        file_menu.addAction("Save", self._save_file, QKeySequence("Ctrl+S"))
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close, QKeySequence("Ctrl+Q"))

        decks_menu = menubar.addMenu("&Decks")
        decks = [
            ("Focus Studio", "ui_focus.py"),
            ("Crucible (Compiler)", "ui_crucible.py"),
            ("Ripper (Downloader)", "ui_ripper.py"),
            ("Alchemist (Converter)", "ui_alchemist.py"),
            ("Maestro (Mastering)", "ui_alchemist.py"),
            ("PyLib (Packages)", "ui_pylib.py"),
        ]
        for name, script in decks:
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
