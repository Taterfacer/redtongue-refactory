#!/usr/bin/env python3
"""
ui_pylib.py
RedTongue PyLib - Native PyQt6 Python Environment & Package Manager.
Scans installed packages, manages virtual environments, and installs 
curated package stacks via a threaded pip worker.
Optimized for low-RAM environments with native QTreeWidget rendering.
"""
import sys
import os
import json
import subprocess
import threading
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QFrame, QTreeWidget, QTreeWidgetItem,
    QPlainTextEdit, QProgressBar, QMessageBox, QHeaderView, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPalette

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

QSS = f"""
QMainWindow, QWidget {{ background-color: {C_BG}; color: {C_WHITE}; font-family: 'Segoe UI', sans-serif; font-size: 13px; }}
QFrame#Panel {{ background-color: {C_PANEL}; border: 1px solid {C_BORDER}; border-radius: 4px; }}
QPushButton {{ background-color: {C_INPUT}; color: {C_WHITE}; border: 1px solid {C_BORDER}; border-radius: 4px; padding: 6px 16px; font-weight: bold; }}
QPushButton:hover {{ background-color: #2a2a2a; }}
QPushButton#Primary {{ background-color: {C_RED}; color: {C_WHITE}; border: 1px solid {C_RED_HOVER}; }}
QPushButton#Primary:hover {{ background-color: {C_RED_HOVER}; }}
QTreeWidget {{ background-color: #0a0a0a; border: 1px solid {C_BORDER}; color: {C_WHITE}; }}
QTreeWidget::item {{ padding: 4px; }}
QTreeWidget::item:selected {{ background-color: {C_RED}; color: {C_WHITE}; }}
QTreeWidget::item:hover {{ background-color: #1a1a1a; }}
QPlainTextEdit {{ background-color: {C_INPUT}; color: {C_WHITE}; border: 1px solid {C_BORDER}; border-radius: 4px; font-family: Consolas; }}
QScrollBar:vertical {{ background: {C_BG}; width: 8px; }}
QScrollBar::handle:vertical {{ background: #333333; border-radius: 4px; }}
QScrollBar::handle:vertical:hover {{ background: {C_RED}; }}
"""

# ==============================================================================
# PACKAGE CATALOG
# ==============================================================================
PACKAGE_CATALOG: Dict[str, List[Tuple[str, str]]] = {
    "Core & Utilities": [
        ("pip", "latest"), ("setuptools", "latest"), ("wheel", "latest"),
        ("virtualenv", "latest"), ("python-dotenv", "latest"), ("rich", "latest"),
        ("typer", "latest"), ("click", "latest"), ("tqdm", "latest"),
        ("psutil", "latest"), ("pyyaml", "latest"), ("pydantic", "latest"),
        ("loguru", "latest"), ("httpx", "latest"), ("requests", "latest"),
    ],
    "GUI & Desktop Apps": [
        ("PyQt6", "latest"), ("PyQt6-Qt6", "latest"), ("PyQt6-sip", "latest"),
        ("PySide6", "latest"), ("customtkinter", "latest"), ("dearpygui", "latest"),
        ("kivy", "latest"), ("pystray", "latest"), ("pynput", "latest"),
    ],
    "Data Science & Math": [
        ("numpy", "latest"), ("scipy", "latest"), ("pandas", "latest"),
        ("matplotlib", "latest"), ("seaborn", "latest"), ("plotly", "latest"),
        ("openpyxl", "latest"), ("statsmodels", "latest"), ("sympy", "latest"),
        ("scikit-learn", "latest"), ("joblib", "latest"),
    ],
    "AI & Machine Learning": [
        ("torch", "latest"), ("torchvision", "latest"), ("torchaudio", "latest"),
        ("transformers", "latest"), ("accelerate", "latest"),
        ("sentence-transformers", "latest"), ("spacy", "latest"),
        ("nltk", "latest"), ("huggingface-hub", "latest"),
    ],
    "Web Development": [
        ("flask", "latest"), ("django", "latest"), ("djangorestframework", "latest"),
        ("fastapi", "latest"), ("uvicorn", "latest"), ("gunicorn", "latest"),
        ("sqlalchemy", "latest"), ("alembic", "latest"), ("redis", "latest"),
        ("celery", "latest"), ("beautifulsoup4", "latest"), ("lxml", "latest"),
    ],
    "Testing & Quality": [
        ("pytest", "latest"), ("pytest-cov", "latest"), ("pytest-mock", "latest"),
        ("coverage", "latest"), ("mypy", "latest"), ("pylint", "latest"),
        ("flake8", "latest"), ("black", "latest"), ("isort", "latest"),
        ("bandit", "latest"), ("pre-commit", "latest"),
    ],
    "DevOps & Cloud": [
        ("docker", "latest"), ("boto3", "latest"), ("botocore", "latest"),
        ("awscli", "latest"), ("paramiko", "latest"), ("ansible-core", "latest"),
    ],
}

# ==============================================================================
# BACKGROUND WORKERS
# ==============================================================================
class PipListWorker(QThread):
    """Scans installed packages and emits the list."""
    finished_scan = pyqtSignal(dict)  # {name_lower: version}
    error = pyqtSignal(str)

    def run(self):
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "list", "--format=json"],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                packages = json.loads(result.stdout)
                installed = {pkg["name"].lower(): pkg["version"] for pkg in packages}
                self.finished_scan.emit(installed)
            else:
                self.error.emit(f"Pip list failed: {result.stderr}")
        except Exception as e:
            self.error.emit(str(e))

class PipInstallWorker(QThread):
    """Installs packages and streams output."""
    log_output = pyqtSignal(str)
    finished_install = pyqtSignal(bool, str)  # success, message

    def __init__(self, packages: List[str]):
        super().__init__()
        self.packages = packages
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        cmd = [sys.executable, "-m", "pip", "install", *self.packages, "--disable-pip-version-check"]
        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, universal_newlines=True
            )
            for line in process.stdout:
                if self._stop:
                    process.terminate()
                    break
                self.log_output.emit(line.rstrip())
            
            process.wait()
            if self._stop:
                self.finished_install.emit(False, "Installation cancelled by user.")
            elif process.returncode == 0:
                self.finished_install.emit(True, "Installation complete.")
            else:
                self.finished_install.emit(False, f"Installation failed with code {process.returncode}.")
        except Exception as e:
            self.finished_install.emit(False, str(e))

# ==============================================================================
# MAIN WINDOW
# ==============================================================================
class PyLibWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RedTongue PyLib Manager")
        self.resize(1000, 700)
        
        self.installed_packages: Dict[str, str] = {}
        self.list_worker: Optional[PipListWorker] = None
        self.install_worker: Optional[PipInstallWorker] = None
        
        self._build_ui()
        self._refresh_packages()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        # Toolbar
        toolbar = QFrame()
        toolbar.setObjectName("Panel")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(10, 8, 10, 8)
        
        self.btn_refresh = QPushButton("Refresh List")
        self.btn_refresh.clicked.connect(self._refresh_packages)
        tb_layout.addWidget(self.btn_refresh)
        
        tb_layout.addStretch()
        
        self.btn_install = QPushButton("Install Selected")
        self.btn_install.setObjectName("Primary")
        self.btn_install.clicked.connect(self._install_selected)
        tb_layout.addWidget(self.btn_install)
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_install)
        tb_layout.addWidget(self.btn_cancel)
        main_layout.addWidget(toolbar)

        # Main Splitter
        splitter = QFrame() # Using QFrame as container for layout
        splitter.setObjectName("Panel")
        split_layout = QHBoxLayout(splitter)
        split_layout.setContentsMargins(0, 0, 0, 0)

        # Tree Widget
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Package", "Status", "Version"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setStyleSheet(f"""
            QTreeWidget {{ background-color: #0a0a0a; border: none; }}
            QTreeWidget::item {{ padding: 4px; }}
            QTreeWidget::item:selected {{ background-color: {C_RED}; }}
        """)
        split_layout.addWidget(self.tree, 2)

        # Log Area
        log_container = QWidget()
        log_layout = QVBoxLayout(log_container)
        log_layout.setContentsMargins(0, 0, 0, 0)
        
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(500) # Prevent memory bloat
        log_layout.addWidget(self.log_text)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0) # Indeterminate
        self.progress_bar.hide()
        log_layout.addWidget(self.progress_bar)
        
        split_layout.addWidget(log_container, 1)
        main_layout.addWidget(splitter, 1)

        # Status Bar
        self.status_lbl = QLabel("Ready")
        self.status_lbl.setStyleSheet(f"color: {C_GRAY}; font-size: 12px;")
        main_layout.addWidget(self.status_lbl)

    def _log(self, msg: str):
        self.log_text.appendPlainText(msg)

    def _refresh_packages(self):
        self.btn_refresh.setEnabled(False)
        self.status_lbl.setText("Scanning installed packages...")
        self._log("Starting package scan...")
        
        self.list_worker = PipListWorker()
        self.list_worker.finished_scan.connect(self._on_scan_finished)
        self.list_worker.error.connect(self._on_scan_error)
        self.list_worker.start()

    def _on_scan_finished(self, installed: Dict[str, str]):
        self.installed_packages = installed
        self.tree.clear()
        
        total = 0
        for category, packages in PACKAGE_CATALOG.items():
            cat_item = QTreeWidgetItem(self.tree)
            cat_item.setText(0, category)
            cat_item.setFont(0, QFont("Segoe UI", 12, QFont.Weight.Bold))
            cat_item.setFlags(cat_item.flags() | Qt.ItemFlag.ItemIsTristate | Qt.ItemFlag.ItemIsUserCheckable)
            cat_item.setCheckState(0, Qt.CheckState.Unchecked)
            
            for pkg_name, pkg_ver in packages:
                pkg_item = QTreeWidgetItem(cat_item)
                pkg_item.setText(0, pkg_name)
                pkg_item.setFlags(pkg_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                pkg_item.setCheckState(0, Qt.CheckState.Unchecked)
                
                pkg_lower = pkg_name.lower()
                if pkg_lower in self.installed_packages:
                    pkg_item.setText(1, "Installed")
                    pkg_item.setForeground(1, QColor(C_GREEN))
                    pkg_item.setText(2, self.installed_packages[pkg_lower])
                else:
                    pkg_item.setText(1, "Not Installed")
                    pkg_item.setForeground(1, QColor(C_GRAY))
                    pkg_item.setText(2, pkg_ver)
                total += 1
                
        self.tree.expandAll()
        self.btn_refresh.setEnabled(True)
        self.status_lbl.setText(f"Scan complete. {len(self.installed_packages)} packages found in environment.")
        self._log(f"Scan complete. Found {len(self.installed_packages)} installed packages.")

    def _on_scan_error(self, err: str):
        self.btn_refresh.setEnabled(True)
        self.status_lbl.setText("Scan failed.")
        self._log(f"Scan error: {err}")

    def _get_selected_packages(self) -> List[str]:
        selected = []
        for i in range(self.tree.topLevelItemCount()):
            cat_item = self.tree.topLevelItem(i)
            for j in range(cat_item.childCount()):
                pkg_item = cat_item.child(j)
                if pkg_item.checkState(0) == Qt.CheckState.Checked:
                    selected.append(pkg_item.text(0))
        return selected

    def _install_selected(self):
        packages = self._get_selected_packages()
        if not packages:
            QMessageBox.information(self, "No Selection", "Please select at least one package to install.")
            return
            
        reply = QMessageBox.question(
            self, "Confirm Installation", 
            f"Install {len(packages)} package(s)?\n\n" + ", ".join(packages[:10]) + ("..." if len(packages) > 10 else ""),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.No:
            return
            
        self.btn_install.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress_bar.show()
        self.status_lbl.setText(f"Installing {len(packages)} packages...")
        self._log(f"Starting installation of {len(packages)} packages...")
        
        self.install_worker = PipInstallWorker(packages)
        self.install_worker.log_output.connect(self._log)
        self.install_worker.finished_install.connect(self._on_install_finished)
        self.install_worker.start()

    def _cancel_install(self):
        if self.install_worker and self.install_worker.isRunning():
            self.install_worker.stop()
            self._log("Cancelling installation...")

    def _on_install_finished(self, success: bool, msg: str):
        self.btn_install.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress_bar.hide()
        self.status_lbl.setText(msg)
        self._log(msg)
        
        if success:
            QMessageBox.information(self, "Success", "Packages installed successfully. Refreshing list...")
            self._refresh_packages()
        else:
            QMessageBox.warning(self, "Installation Failed", msg)

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
    
    window = PyLibWindow()
    window.show()
    sys.exit(app.exec())