<img width="512" height="512" alt="logo" src="https://github.com/user-attachments/assets/e96d4eb2-36c9-4e54-ba53-2e8c3661fb6c" />


# RedTongue Refactory

![RedTongue Logo](logo.png)

**Version:** 4.0.0  
**Date:** August 28, 2026  
**Author:** Joshua Alexander

A comprehensive forensic Python refactoring and analysis suite with AI-powered capabilities, optimized for low-RAM (8GB) and HDD environments.

---

## Author & Contact

- **Name:** Joshua Alexander
- **Email:** somebodysomeone1982@gmail.com
- **GitHub:** [Taterfacer](https://github.com/Taterfacer)
- **Patreon:** [patreon.com/taterfacer](https://patreon.com/taterfacer)

---

## License

**All Rights Reserved.** This software is proprietary intellectual property of Joshua Alexander. 

- **NOT free software**
- **NOT open source**
- Unauthorized use, distribution, or modification is prohibited
- For licensing inquiries, contact: somebodysomeone1982@gmail.com

External tools and dependencies referenced in this project remain the property of their respective owners.

---

## Table of Contents

1. [Description](#description)
2. [Core Architecture](#core-architecture)
3. [Application Decks (UI Modules)](#application-decks-ui-modules)
4. [ToolLayer Functions](#toollayer-functions)
5. [AI Agent System](#ai-agent-system)
6. [Media Download Features (yt_dlp)](#media-download-features-yt_dlp)
7. [Requirements](#requirements)
8. [Installation](#installation)
9. [Usage](#usage)
10. [Architecture Highlights](#architecture-highlights)
11. [Acknowledgments](#acknowledgments)

---

## Description

RedTongue Refactory is a professional-grade Python development toolkit featuring:

- **Forensic AST Analysis** - Deep structural code analysis and linting
- **AI Swarm Integration** - Multi-agent AI assistance for code refactoring
- **RAG (Retrieval-Augmented Generation)** - Context-aware code suggestions with vector embeddings
- **Speech-to-Text & Text-to-Speech** - Voice-controlled development features using Whisper and Kokoro TTS
- **Sandbox Execution Engine** - Safe execution of untrusted Python code with CPU/memory limits
- **Adaptive System Governor** - Optimized for low-RAM and sequential HDD I/O
- **PyQt6 GUI** - Dark-themed interface with multiple specialized UI modules
- **Nuitka Compilation** - Build standalone executables from Python scripts
- **Media Download Suite** - Integrated video/audio extraction from 100+ websites

---

## Core Architecture

### Backend Components (`backend.py` - 3,208 lines)

| Class | Purpose | Key Methods |
|-------|---------|-------------|
| `SpeechToText` | Speech recognition using Whisper | `listen_and_transcribe()` |
| `DiagnosticBrain` | ONNX-based diagnostic inference | `is_ready()`, `status()`, `ensure_model()`, `compress_diagnostics()` |
| `RAGIndex` | Vector-based retrieval index | `_embed()`, `_tokens()`, `query()`, `reindex()`, `index_file()` |
| `KokoroTTS` | Text-to-speech synthesis | `generate_wav()`, `_ensure_engine()`, `_voice_candidates()` |
| `ToolLayer` | Primary tool execution layer | 40+ tool functions (see below) |
| `FailoverEntry` | Failover configuration entry | `to_dict()` |
| `FailoverStack` | AI provider failover management | `load_config()`, `ordered()`, `next_entry()`, `report_success()`, `report_failure()` |
| `AgentSwarm` | Multi-agent AI orchestration | `reset_clients()`, `rebuild_failover()`, `run_main_agent()` |

### Core Foundation (`core.py` - 897 lines)

| Class | Purpose |
|-------|---------|
| `LintStackError` | Base exception hierarchy |
| `ConfigError`, `StoreError`, `StoreCorruptError` | Configuration and storage exceptions |
| `AtomicWriteError`, `LockBusyError`, `RepairFailedError` | File operation exceptions |
| `Severity` | Issue severity enumeration (INFO, WARNING, ERROR, CRITICAL) |
| `Issue` | Code issue data model with fingerprinting |
| `Config`, `Layout` | Application configuration management |
| `FileLock`, `BootLock` | Advisory file locking for concurrent access prevention |
| `LoadSample` | Sample data loading utilities |
| `Governor` | Adaptive system resource monitoring and throttling |
| `Store` | SQLite-backed persistent storage with WAL mode |

### Engine Layer (`engine.py` - 501 lines)

| Class | Purpose |
|-------|---------|
| `BootstrapError`, `EngineUnavailableError` | Engine initialization exceptions |
| `DiscoveredFile`, `DiscoveryResult` | File discovery data models |
| `Issue` | Engine-level issue tracking |
| `AstResult` | AST parsing results |
| `EngineContext` | Main engine orchestration context |

### Sandbox Runner (`runner.py` - 251 lines)

| Class | Purpose |
|-------|---------|
| `SandboxRunner` | Cross-platform sandboxed code execution with CPU/memory/resource limits |

### Media Player (`redtongue_player.py` - 805 lines)

| Class | Purpose |
|-------|---------|
| `ShuffleQueue` | Randomized media queue management |
| `MediaLibrary` | Local media file indexing and library management |
| `PlaylistWidget` | PyQt6 playlist UI component |
| `RTButton`, `RTSlider` | Custom styled media control widgets |
| `MediaSuiteWidget` | Complete media playback interface |

---

## Application Decks (UI Modules)

### 1. Alchemist (`ui_alchemist.py` - 579 lines)
**Purpose:** Code transformation and conversion toolkit

| Class | Purpose |
|-------|---------|
| `ConvertSettings` | Conversion configuration data class |
| `ConverterRegistry` | File format converter registration and dispatch |
| `ToolManager` | Background thread for tool operations |
| `ConversionWorker` | Async file conversion processing |
| `AlchemistWindow` | Main Alchemist UI window |

**Features:**
- Multi-format file conversion
- Batch processing support
- Progress tracking with worker threads
- Tool integration manager

### 2. Crucible (`ui_crucible.py` - 1,492 lines)
**Purpose:** Nuitka-based Python compilation to standalone executables

| Class | Purpose |
|-------|---------|
| `SectionCard` | Styled UI section container |
| `SmartLogOutput` | Syntax-highlighted log display with auto-scroll |
| `DataDropList` | Drag-and-drop enabled file list widget |
| `NuitkaBuildThread` | Background compilation process |
| `CrucibleWindow` | Main Crucible compilation UI |

**Features:**
- One-click Python to EXE compilation
- Nuitka integration with configurable options
- Real-time build log output
- Drag-and-drop file input
- Build progress tracking
- Output size reporting
- Uses embedded base64 logo (fallback) or `crucible_logo.png`

### 3. Focus Studio (`ui_focus.py` - 812 lines)
**Purpose:** Productivity and focus management suite

| Class | Purpose |
|-------|---------|
| `DataManager` | Persistent data storage for tasks/notes |
| `SoundSynthesizer` | Audio tone generation for timers |
| `TimerPage` | Pomodoro-style timer interface |
| `TasksPage` | Task management with priorities |
| `NotesPage` | Rich text note editor |
| `StatsPage` | Productivity statistics dashboard |
| `FocusStudioWindow` | Main Focus Studio window |

**Features:**
- Customizable timer sessions
- Task prioritization system
- Note-taking with persistence
- Usage statistics tracking
- Audio alerts and ambient sounds

### 4. Ripper (`ui_ripper.py` - 542 lines)
**Purpose:** Media download and extraction toolkit (yt_dlp integration)

| Class | Purpose |
|-------|---------|
| `RipperDB` | SQLite database for download history |
| `YtDlpWorker` | Background yt_dlp download thread |
| `DownloadItemWidget` | Individual download queue item UI |
| `RipperWindow` | Main Ripper interface |

**Features:**
- Queue-based download management
- Progress tracking per download
- Format selection (video/audio)
- Download history persistence
- Error handling and retry logic

### 5. PyLib (`ui_pylib.py` - 479 lines)
**Purpose:** Python package and library management

| Class | Purpose |
|-------|---------|
| `PipListWorker` | Background pip list retrieval |
| `PipInstallWorker` | Background package installation |
| `PyLibWindow` | Main PyLib management UI |

**Features:**
- Installed package listing
- Package installation/uninstallation
- Version management
- Dependency inspection

### 6. Main Interface (`ui_main.py` - 614 lines)
**Purpose:** Primary application window with chat and lint panels

| Class | Purpose |
|-------|---------|
| `ChatWorker` | AI chat response background thread |
| `LintWorker` | Code linting background thread |
| `PythonHighlighter` | QSyntaxHighlighter for Python syntax |
| `CodeEditor` | Enhanced QPlainTextEdit with line numbers |
| `ChatPanel` | AI conversation interface |
| `LintPanel` | Real-time linting results display |
| `RefactoryMainWindow` | Main application window |

---

## ToolLayer Functions

The `ToolLayer` class provides **40+ tool functions** accessible to the AI agent system:

### File Operations
| Function | Description |
|----------|-------------|
| `read_file(path, chunked=False)` | Read file contents with optional chunking for large files |
| `write_file(path, content)` | Write content to file with atomic operations |
| `list_directory(path, recursive=False)` | List directory contents with optional recursion |
| `copy_file(src, dst)` | Copy file with validation |
| `delete_file(path)` | Delete file with safety checks |
| `move_file(src, dst)` | Move/rename file |
| `file_exists(path)` | Check if file exists |
| `get_file_info(path)` | Get file metadata (size, modified time, etc.) |

### Code Execution & Analysis
| Function | Description |
|----------|-------------|
| `run_python(path)` | Execute Python script in sandbox |
| `run_shell(command)` | Run shell command with safety filters |
| `run_forensic_lint(path)` | Deep AST-based code analysis |
| `analyze_crash_dump(stderr_text)` | Analyze error output for root cause |
| `run_tests(path, test_runner="pytest")` | Execute test suite |
| `run_linter(path, linter="flake8")` | Run code linter |
| `check_vulnerabilities(path)` | Security vulnerability scanning |

### Git Operations
| Function | Description |
|----------|-------------|
| `git_status()` | Get repository status |
| `git_commit(message, files)` | Commit changes with optional file selection |
| `git_diff(path)` | Show diff for file or entire repo |

### Package Management
| Function | Description |
|----------|-------------|
| `install_package(package, upgrade=False)` | Install pip package |

### Knowledge Base (RAG)
| Function | Description |
|----------|-------------|
| `ingest_knowledge(paths)` | Index files into RAG vector store |
| `query_knowledge_base(query, top_k=5)` | Semantic search indexed content |

### Diagnostics & System
| Function | Description |
|----------|-------------|
| `run_diagnostic_scan(target="full")` | Run system diagnostics |
| `get_system_resources()` | Get CPU, memory, disk usage |
| `check_resource_limits(operation)` | Check available resource limits |
| `speak_response(text)` | Generate speech from text |

### AI Agent Management
| Function | Description |
|----------|-------------|
| `delegate_task(role, task, context)` | Assign task to AI agent |
| `cancel_task(task_id)` | Cancel running agent task |
| `get_agent_status()` | Get current agent state |

### Session Management
| Function | Description |
|----------|-------------|
| `save_session_state(key, value)` | Persist session data |
| `load_session_state(key)` | Retrieve session data |
| `create_checkpoint(name)` | Create recovery checkpoint |
| `chain_commands(commands)` | Execute command sequence |

### Web Operations
| Function | Description |
|----------|-------------|
| `search_web(query)` | DuckDuckGo web search |
| `fetch_url(url)` | Fetch URL content with redirect handling |

---

## AI Agent System

### AgentSwarm Architecture
- **Multi-Provider Failover:** Automatic fallback between OpenAI, local models, and alternative providers
- **Role-Based Agents:** Specialized agents for different task types (refactor, debug, explain, test)
- **Context-Aware:** Integrates RAG-indexed codebase knowledge
- **Asynchronous Execution:** Non-blocking agent operations via QThread workers

### FailoverStack
- Configurable provider priority ordering
- Success/failure tracking per provider
- Automatic provider rotation on errors
- Persistent configuration via JSON

### RAGIndex (Retrieval-Augmented Generation)
- **Vector Embeddings:** 2048-dimensional embeddings for semantic search
- **Chunking Strategy:** 60-line chunks for optimal context window usage
- **Indexed Extensions:** `.py`, `.js`, `.ts`, `.html`, `.css`, `.md`, `.txt`, `.json`, `.yml`, `.yaml`, `.toml`, `.xml`, `.sql`
- **Ignored Directories:** `node_modules`, `__pycache__`, `libs`, `dist`, `build`, `site-packages`, `.venv`, `venv`
- **Persistence:** SQLite-backed index with WAL mode
- **Query Limits:** 10,000 character max query size with automatic truncation

---

## Media Download Features (yt_dlp)

### Legal Notice

⚠️ **IMPORTANT LEGAL DISCLAIMER:**

This software includes integration with `yt_dlp` (YouTube-DL Plus), an open-source command-line program to download videos from online platforms.

- **NOT INTENDED FOR DOWNLOADING COPYRIGHTED MATERIALS:** Users are solely responsible for ensuring they have the legal right to download any content. Downloading copyrighted material without permission may violate copyright laws in your jurisdiction.
- **FAIR USE ONLY:** This tool should only be used to download content that you own, content in the public domain, content licensed under Creative Commons, or content for which you have explicit permission from the copyright holder.
- **NO LIABILITY:** Joshua Alexander and the RedTongue Refactory project assume NO liability for any misuse of this feature. Users bear full responsibility for compliance with applicable laws and terms of service.
- **EXTERNAL DEPENDENCY:** `yt_dlp` is an external open-source project (licensed under Unlicense). It remains the property of its respective maintainers and contributors. RedTongue Refactory merely provides an integration interface.

### Compatible Websites (Top 10)

The yt_dlp integration supports **100+ websites**. Top supported platforms include:

1. **YouTube** (youtube.com) - Videos, playlists, channels, subtitles
2. **Vimeo** (vimeo.com) - High-quality video downloads
3. **SoundCloud** (soundcloud.com) - Audio tracks and playlists
4. **Bandcamp** (bandcamp.com) - Music albums and tracks
5. **Twitter/X** (twitter.com, x.com) - Video tweets
6. **Instagram** (instagram.com) - Reels, IGTV, posts
7. **TikTok** (tiktok.com) - Short-form videos
8. **Facebook** (facebook.com) - Public videos
9. **Twitch** (twitch.tv) - Clips and VODs
10. **Reddit** (reddit.com) - Video posts

### Full Compatibility List
For the complete list of 100+ supported sites, visit:  
https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md

### Implementation Details
- **Dynamic Import:** `yt_dlp` is imported at runtime to handle missing dependency gracefully
- **Background Threading:** Downloads run in `YtDlpWorker` QThread to prevent UI freezing
- **Progress Hooks:** Real-time progress updates displayed in UI
- **Format Selection:** User-configurable video/audio format preferences
- **Playlist Support:** Automatic handling of multi-video playlists
- **Database Persistence:** Download history stored in SQLite via `RipperDB`

---

## Requirements

### Core Dependencies
- **Python:** 3.8+ (tested up to 3.14)
- **PyQt6:** Modern Qt6 bindings for Python
- **requests:** HTTP library for web operations
- **cryptography:** Cryptographic recipes and primitives

### Runtime Dependencies
- **numpy:** Numerical computing for embeddings
- **psutil:** Cross-platform system monitoring
- **SpeechRecognition:** STT engine interface
- **openai:** OpenAI API client
- **duckduckgo-search:** Privacy-focused web search
- **onnxruntime:** (Optional) ONNX model inference for DiagnosticBrain

### Optional Dependencies
- **yt_dlp:** Media download functionality (install separately: `pip install yt-dlp`)
- **whisper:** Local speech-to-text (if not using API)
- **kokoro:** TTS engine (auto-downloaded on first use)

### Platform Support
- **Windows:** Full support (uses `py` launcher, ctypes for OS metrics)
- **Linux:** Full support (uses rlimits, /proc for OS metrics)
- **macOS:** Partial support (some features may require adjustments)

---

## Installation

### Step 1: Obtain Project Files
Clone the repository or obtain the project files through authorized channels.

### Step 2: Install Core Dependencies
```bash
pip install PyQt6 requests cryptography numpy psutil SpeechRecognition openai duckduckgo-search
```

### Step 3: Install Optional Features
```bash
# For ONNX diagnostic features
pip install onnxruntime

# For media download functionality
pip install yt-dlp
```

### Step 4: Run the Application
```bash
python main.py
```

The application will automatically bootstrap missing core dependencies on first launch and download required AI models (Kokoro TTS, ONNX models) as needed.

---

## Usage

### Launch Main Application
```bash
python main.py
```

### Access Application Decks

From the main interface, access specialized decks:

| Deck | Function |
|------|----------|
| **Alchemist** | Code transformation and file conversion |
| **Crucible** | Compile Python to standalone EXE via Nuitka |
| **Focus Studio** | Productivity timer, tasks, notes, and stats |
| **Ripper** | Download media from 100+ websites |
| **PyLib** | Manage Python packages and dependencies |

### AI Chat Interface
- Use the integrated chat panel for AI-assisted refactoring
- Ask questions about your codebase (powered by RAG)
- Request code improvements, bug fixes, or explanations
- Voice input available via Speech-to-Text

### Command-Line Tools (via ToolLayer)
Advanced users can access ToolLayer functions programmatically:

```python
from backend import ToolLayer

tools = ToolLayer(workspace="/path/to/project")

# Example: Run forensic lint
result = tools.run_forensic_lint("my_script.py")

# Example: Query knowledge base
matches = tools.query_knowledge_base("authentication logic", top_k=3)
```

---

## Architecture Highlights

### Performance Optimizations
- **Low-Memory Design:** Engineered to run on systems with 8GB RAM
- **HDD-Friendly I/O:** Sequential read/write patterns optimized for mechanical drives
- **File Chunking:** 64KB chunks for large file operations
- **Cached Embeddings:** Module-level embedding cache keyed by text hash and dimension
- **Advisory Locking:** Prevents concurrent access conflicts via `FileLock` and `BootLock`

### Safety Features
- **Sandboxed Execution:** Resource-limited code execution via `SandboxRunner`
- **Path Validation:** All file paths validated against workspace boundaries
- **Destructive Command Blocking:** Shell commands filtered for dangerous patterns (`rm -rf /`, `mkfs`, `format c:`, fork bombs)
- **Sensitive Path Protection:** System directories blocked from operations
- **Atomic Writes:** File operations use temporary files with rollback capability

### Data Persistence
- **SQLite WAL Mode:** Write-ahead logging for crash-safe transactions
- **Session State:** JSON-based session persistence
- **Checkpoint System:** Manual and automatic recovery checkpoints
- **Download History:** Ripper maintains SQLite database of downloads

### Threading Model
- **QThread Workers:** All long-running operations execute in background threads
- **Signal/Slot Communication:** Thread-safe UI updates via PyQt6 signals
- **Non-Blocking AI:** Agent operations run asynchronously
- **Progress Reporting:** Real-time progress hooks for downloads and builds

---

## Acknowledgments

### External Dependencies
The following external projects are used by RedTongue Refactory and remain the intellectual property of their respective owners:

- **PyQt6** - Riverbank Computing Limited
- **yt_dlp** - yt-dlp contributors (Unlicense)
- **OpenAI API** - OpenAI Inc.
- **DuckDuckGo Search** - deedy5 (MIT License)
- **ONNX Runtime** - Microsoft Corporation
- **NumPy** - NumPy Developers (BSD License)
- **psutil** - Giampaolo Rodola (BSD License)
- **SpeechRecognition** - Anthony Zhang (MIT License)
- **cryptography** - Python Cryptography Authority (Apache 2.0)

### Trademark Notice
"RedTongue Refactory" is a trademark of Joshua Alexander. All other trademarks, logos, and brand names mentioned are the property of their respective owners.

---

## Contact & Support

For licensing inquiries, technical support, or collaboration:

- **Email:** somebodysomeone1982@gmail.com
- **GitHub:** https://github.com/Taterfacer
- **Patreon:** https://patreon.com/taterfacer

---

*RedTongue Refactory © 2026 Joshua Alexander. All rights reserved.*  
*Proprietary Software — Not for Free Distribution*
