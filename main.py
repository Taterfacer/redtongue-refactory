#!/usr/bin/env python3
"""
main.py
Entry point for the RedTongue Refactory suite.
Handles dependency bootstrapping, logging, splash screen, and application launch.
"""
import logging
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ==============================================================================
# CONSTANTS & PATHS
# ==============================================================================
APP_NAME = "RedTongue Refactory"
APP_VERSION = "4.0.0"
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Core dependencies required before PyQt6 can be imported
CORE_PACKAGES = {
    "PyQt6": "PyQt6",
    "requests": "requests",
    "cryptography": "cryptography",
}

# Runtime dependencies (checked after PyQt6 is loaded)
RUNTIME_PACKAGES = {
    "numpy": "numpy",
    "psutil": "psutil",
    "speech_recognition": "SpeechRecognition",
    "openai": "openai",
    "duckduckgo_search": "duckduckgo-search",
}

# ==============================================================================
# LOGGING SETUP
# ==============================================================================
def setup_logging() -> logging.Logger:
    """Configures root logger with file and stream handlers."""
    logger = logging.getLogger("RedTongue")
    logger.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    fh = RotatingFileHandler(
        LOG_DIR / "refactory.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    sh.setLevel(logging.INFO)

    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger

logger = setup_logging()

# ==============================================================================
# DEPENDENCY BOOTSTRAPPING
# ==============================================================================
def pip_install(packages: list[str]) -> bool:
    """Installs packages via pip. Returns True on success."""
    if not packages:
        return True
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", "--upgrade"] + packages
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error("pip install timed out.")
        return False
    except Exception as e:
        logger.error(f"pip install failed: {e}")
        return False

def bootstrap_core() -> None:
    """Installs core dependencies required for the GUI to launch."""
    missing = []
    for module, package in CORE_PACKAGES.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)

    if missing:
        logger.info(f"Installing core dependencies: {', '.join(missing)}")
        if not pip_install(missing):
            logger.critical("Failed to install core dependencies. Exiting.")
            sys.exit(1)

def check_runtime_deps() -> None:
    """Checks and installs optional runtime dependencies in background."""
    missing = []
    for module, package in RUNTIME_PACKAGES.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)

    if missing:
        logger.info(f"Missing optional dependencies: {', '.join(missing)}")
        # In a full implementation, this would trigger a background thread
        # to install them without blocking the UI.
        # pip_install(missing)

# ==============================================================================
# SPLASH SCREEN
# ==============================================================================
def create_splash(app) -> "QSplashScreen":
    """Creates and returns the Blood & Void themed splash screen."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap
    from PyQt6.QtWidgets import QSplashScreen

    pixmap = QPixmap(400, 200)
    pixmap.fill(QColor("#050505"))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Draw border
    painter.setPen(QColor("#2a0a0a"))
    painter.setBrush(QColor("#0a0a0c"))
    painter.drawRoundedRect(5, 5, 390, 190, 10, 10)

    # Draw Title
    painter.setPen(QColor("#8b0000"))
    title_font = QFont("Segoe UI", 22, QFont.Weight.Bold)
    painter.setFont(title_font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "RED TONGUE\nREFACTORY")

    # Draw Version
    painter.setPen(QColor("#555555"))
    ver_font = QFont("Segoe UI", 9)
    painter.setFont(ver_font)
    painter.drawText(0, 180, 400, 15, Qt.AlignmentFlag.AlignCenter, f"v{APP_VERSION}")
    painter.end()

    splash = QSplashScreen(pixmap)
    splash.setWindowFlags(
        Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
    )
    return splash

# ==============================================================================
# MAIN EXECUTION
# ==============================================================================
def main() -> None:
    """Application entry point."""
    # 1. Bootstrap core dependencies before importing Qt
    bootstrap_core()

    # 2. Import PyQt6 (now guaranteed to be available)
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QMessageBox

    # 3. Initialize Qt Application
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # 4. Show Splash Screen
    splash = create_splash(app)
    splash.show()
    app.processEvents()
    time.sleep(0.5)

    # 5. Check runtime dependencies (non-blocking)
    check_runtime_deps()

    # 6. Launch Main UI
    try:
        from ui_main import RefactoryMainWindow
        window = RefactoryMainWindow()
        window.show()
        splash.finish(window)
    except Exception as e:
        splash.close()
        logger.critical(f"Failed to initialize UI: {e}", exc_info=True)
        QMessageBox.critical(
            None, "Fatal Error", f"Failed to initialize UI:\n\n{e}"
        )
        sys.exit(1)

    # 7. Start Event Loop
    sys.exit(app.exec())

if __name__ == "__main__":
    main()