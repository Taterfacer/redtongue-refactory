<img width="512" height="512" alt="logo" src="https://github.com/user-attachments/assets/e96d4eb2-36c9-4e54-ba53-2e8c3661fb6c" />


# RedTongue Refactory

**Version:** 4.0.0  
**Date:** August 28, 2026

A forensic Python refactoring and analysis suite with AI-powered capabilities, designed for low-RAM (8GB) and HDD environments.

---

## Author & Contact

- **Name:** Joshua Alexander
- **Email:** somebodysomeone1982@gmail.com
- **GitHub:** [Taterfacer](https://github.com/Taterfacer)
- **Patreon:** [patreon.com/taterfacer](https://patreon.com/taterfacer)

---

## License

**All Rights Reserved.** This software is proprietary intellectual property of Joshua Alexander. Not free. Not open source. Unauthorized use, distribution, or modification is prohibited.

External tools and dependencies referenced in this project remain the property of their respective owners.

---

## Description

RedTongue Refactory is a comprehensive Python development toolkit featuring:

- **Forensic AST Analysis** - Deep structural code analysis and linting
- **AI Swarm Integration** - Multi-agent AI assistance for code refactoring
- **RAG (Retrieval-Augmented Generation)** - Context-aware code suggestions
- **Speech-to-Text & Text-to-Speech** - Voice-controlled development features
- **Sandbox Execution Engine** - Safe execution of untrusted Python code with resource limits
- **Adaptive System Governor** - Optimized for low-RAM and sequential HDD I/O
- **PyQt6 GUI** - Dark-themed interface with multiple specialized UI modules

### Core Components

| Module | Purpose |
|--------|---------|
| `main.py` | Entry point with dependency bootstrapping and splash screen |
| `core.py` | Foundation layer: error hierarchy, data models, SQLite store, file locks |
| `engine.py` | AST parsing, interpreter detection, Ruff bootstrapping |
| `backend.py` | AI Swarm, ToolLayer, RAG, TTS/STT, ONNX diagnostic brain |
| `runner.py` | Cross-platform sandbox execution with CPU/memory limits |
| `ui_*.py` | PyQt6 interface modules (Alchemist, Crucible, Focus, Ripper, PyLib) |

---

## Requirements

### Core Dependencies
- Python 3.8+ (tested up to 3.14)
- PyQt6
- requests
- cryptography

### Runtime Dependencies
- numpy
- psutil
- SpeechRecognition
- openai
- duckduckgo-search
- onnxruntime (optional, for diagnostic brain)

### Platform Support
- Windows (uses `py` launcher, ctypes for OS metrics)
- Linux (uses rlimits, /proc for OS metrics)
- macOS (partial support)

---

## Installation

1. **Clone or obtain the project files**

2. **Install dependencies:**
   ```bash
   pip install PyQt6 requests cryptography numpy psutil SpeechRecognition openai duckduckgo-search
   ```

   Optional (for ONNX diagnostic features):
   ```bash
   pip install onnxruntime
   ```

3. **Run the application:**
   ```bash
   python main.py
   ```

The application will automatically bootstrap missing core dependencies on first launch.

---

## Usage

Launch the main application:

```bash
python main.py
```

The GUI provides access to:
- **Alchemist** - Code transformation and refactoring
- **Crucible** - Forensic analysis and issue fingerprinting
- **Focus** - Targeted code inspection
- **Ripper** - Code extraction and decomposition
- **PyLib** - Library management

---

## Architecture Highlights

- **Low-Memory Optimized:** Designed to run on 8GB RAM systems
- **HDD-Friendly:** Sequential I/O patterns for mechanical drives
- **Adaptive Governor:** Monitors system load and adjusts behavior
- **Atomic File Operations:** Safe writes with rollback capability
- **Advisory Locking:** Prevents concurrent access conflicts
- **SQLite WAL Mode:** Persistent storage with write-ahead logging

---

## Acknowledgments

Any external tools, libraries, or dependencies used by this project remain the intellectual property of their respective owners.

---

## Contact

For licensing inquiries or support:
- **Email:** somebodysomeone1982@gmail.com
- **GitHub:** https://github.com/Taterfacer
- **Support:** https://patreon.com/taterfacer

---

*RedTongue Refactory © 2026 Joshua Alexander. All rights reserved.*
