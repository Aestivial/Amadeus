# Amadeus Project Roadmap & Milestone Tracker

This roadmap outlines the milestones for the Amadeus local AI agent.

---

## Milestone 1: Core Foundation & Portable Architecture ✅ (Completed)
- [x] **Portable Directory Architecture**: Self-contained runtime (`.runtime/`), binaries (`bin/`), models (`models/`), and data (`data/`).
- [x] **Multi-stage Launcher**: `amadeus.cmd` and `amadeus.ps1` with manual `repair` command for directory moves.
- [x] **Zero-dependency Setup & Teardown**: `setup.ps1` and `uninstall.ps1` with model backup options.
- [x] **Configuration & Registry System**: Dual-layer TOML configuration (`src/amadeus/models.toml` + `data/models.toml`).
- [x] **Safety Policy Engine**: Granular execution modes (`ask`, `auto`, `yolo`) and hardened regex denylist.
- [x] **Core Execution Tools**:
  - `shell`: Isolated UTF-8 PowerShell execution with timeouts and output truncation.
  - `files`: `read_file`, `write_file` (with unified diff preview), `edit_file`, `list_dir`.
  - `search`: `glob` and `grep` with ripgrep acceleration and Python fallback.
  - `web`: `web_fetch` with HTML text extraction, safety tagging, and domain filtering.
- [x] **Persistent User Memory**: Markdown memory (`profile.md`, `preferences.md`, `notes/*.md`) with BM25-lite keyword recall and automated token budget management.
- [x] **Persona & UI Subsystem**: Steins;Gate Kurisu Makise system persona, crimson gradient terminal styling, and Unicode Braille banners.
- [x] **Comprehensive Test Suite**: 128 unit tests passing across all foundation modules.

---

## Milestone 2: Runtime Engine & Execution Loop ⏳ (Parked for Next Run)
- [ ] **Llama.cpp Process Supervisor (`src/amadeus/runtime/llamacpp.py`)**:
  - Automatic download and extraction of Windows CUDA 13.x/12.x builds and `cudart` dependencies.
  - Process lifecycle management using Windows Job Objects (clean shutdown on exit).
  - Health check polling (`/health`) and dynamic flag generation (`-c`, `-ngl`, `-fa`, `--n-cpu-moe`).
- [ ] **Hugging Face Model Downloader (`src/amadeus/runtime/hf.py`)**:
  - Resumable streaming downloads with SHA-256 validation and progress indicators.
- [ ] **Ollama & OpenAI-Compatible Connectors (`src/amadeus/runtime/ollama.py`, `openai_compat.py`)**:
  - Unload and warm-up API integration.
- [ ] **LLM Client & Streaming Tool Calling (`src/amadeus/llm/client.py`, `toolparse.py`)**:
  - OpenAI-compatible SSE streaming with native Jinja tool-call chunk aggregation.
  - Fallback text-based JSON tool extraction parser.
- [ ] **Autonomous ReAct Agent Loop (`src/amadeus/agent.py`, `context.py`)**:
  - Tool execution dispatch, repetition prevention, and context summarization.
- [ ] **Interactive REPL (`src/amadeus/repl.py`, `cli.py`)**:
  - `prompt_toolkit` interactive prompt, slash command parsing, and history navigation.
- [ ] **System Diagnostics (`amadeus doctor`)**:
  - Hardware audit (VRAM, RAM, CUDA driver level) and recommended model profile detection.

---

## Milestone 3: Distribution & Polish (Future)
- [ ] Automated GitHub Actions CI workflow (Windows and Linux test matrix).
- [ ] Initial release tag (`v0.1.0`).
- [ ] User Manual (`MANUAL.md`).
- [ ] Optional local web interface (`amadeus serve`).
