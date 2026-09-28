# Jarvis-lite — Local Windows PC Assistant

A local, Windows-first AI assistant that behaves like a **PC operator**, not just a chatbot. Designed for personal use on a living-room PC.

## Architecture Highlights
- **Two-Path Design:**
  - **Fast path (< 1s, no LLM):** Regex/YAML intent router handles common actions (launch apps, open websites, search YouTube) instantly.
  - **Analysis path (LLM + Playbooks):** Deterministic diagnostic playbooks run first, then a local 3B–4B LLM explains findings and recommends actions.
- **Strict Security:** Fixed 4-tier risk model (L0–L3). The model never modifies system settings without explicit user confirmation.
- **Resource Efficient:** Target machine is an Intel Core i5-8250U, 8 GB RAM. Idle footprint < 150 MB; model auto-unloaded when idle.

## Progress & Status
See [plan.md](file:///d:/project/jarvis/plan.md) for master implementation roadmap and [DECISIONS.md](file:///d:/project/jarvis/DECISIONS.md) for architectural decisions.

- [x] **Phase 0:** Master Design & Concept
- [x] **Phase 1:** Foundation & Read-only System Tools (Completed)
- [x] **Phase 2:** Fast Path & Intent Router (Completed)
- [x] **Phase 3:** Local LLM Integration & Evaluation Suite (Completed)
- [x] **Phase 4:** Diagnostics Playbooks (BSOD, Crashes, Disk 100%) (Completed)
- [x] **Phase 5:** Tray UI & Background Mode (Completed)
- [x] **Phase 6:** Web Research Pipeline (Completed)
- [x] **Phase 7:** Game & App Investigation (Completed)
- [x] **Phase 8:** Controlled Modifications (L3 Safe Edits) (Completed)
- [x] **Phase 9:** Browser Automation & Screen Reading (Phase 9A, 9B, 9C Completed)
- [x] **Phase 10:** Native Windows UI Automation & Desktop Control (Phase 10A, 10B, 10C, 10D Completed)
- [x] **Phase 11:** Voice Input Layer & Local STT (Faster-Whisper CPU + Native winmm.dll Completed)
- [x] **Phase 12:** Persistent Local Memory, Context Resolution & Safe Workflow Learning (Completed)
- [ ] **Phase 13:** Cloud LLM Fallback & Hybrid Routing

## Quick Start (CLI, Tray UI, Voice, Memory & Playbooks)

Activate the local environment and run tools, UI, or playbooks:
```powershell
# Jalankan antarmuka System Tray + Global Hotkey (Ctrl+Shift+J)
.\.venv\Scripts\python.exe -m assistant tray

# Buka jendela Chat Window langsung (Dark mode Tkinter dengan tombol Push-to-Talk)
.\.venv\Scripts\python.exe -m assistant chat

# Rekam dan transkripsi suara langsung dari CLI (Local faster-whisper STT)
.\.venv\Scripts\python.exe -m assistant voice

# List all 66 registered tools
.\.venv\Scripts\python.exe -m assistant list

# Persistent Memory & Context (Phase 12 - SQLite data/memory.db)
.\.venv\Scripts\python.exe -m assistant memory list
.\.venv\Scripts\python.exe -m assistant memory recall category="project" key="jarvis"
.\.venv\Scripts\python.exe -m assistant ask "project jarvis ada di D:\project\jarvis"
.\.venv\Scripts\python.exe -m assistant ask "ingat preferensi editor vscode"
.\.venv\Scripts\python.exe -m assistant ask "buka project jarvis"

# Safe Workflow Learning (Candidate Detection & Explicit Approval)
.\.venv\Scripts\python.exe -m assistant workflow list
.\.venv\Scripts\python.exe -m assistant workflow approve 1 --trigger "buka workspace dev"

# Desktop UI Automation & Inspection (Phase 10A-10C - Native UIA / Win32)
.\.venv\Scripts\python.exe -m assistant tool ui.inspect_tree window_title="Notepad" max_depth=3
.\.venv\Scripts\python.exe -m assistant tool ui.find_control name="Text Editor" control_type="Edit"
.\.venv\Scripts\python.exe -m assistant tool ui.set_value name="Text Editor" value="Hello from Jarvis"
.\.venv\Scripts\python.exe -m assistant tool window.activate title="Notepad"
.\.venv\Scripts\python.exe -m assistant tool window.close title="Notepad"

# Controlled File Modifications (Phase 8 - L3 Safe Edits, Diffs, Backups & Rollback)
.\.venv\Scripts\python.exe -m assistant tool files.propose_edit file_path="config/settings.yaml" new_content="name: JarvisPRO\n" explanation="Ubah nama assistant"
.\.venv\Scripts\python.exe -m assistant tool files.backup file_path="config/settings.yaml"
.\.venv\Scripts\python.exe -m assistant tool files.apply_edit file_path="config/settings.yaml" new_content="name: Jarvis\n" reason="Kembalikan setting"
.\.venv\Scripts\python.exe -m assistant tool files.restore_backup original_path="config/settings.yaml"

# Game Discovery & Save/Config Inspector Tools
.\.venv\Scripts\python.exe -m assistant tool games.list_installed
.\.venv\Scripts\python.exe -m assistant tool games.find_save_and_config game_name="Cyberpunk 2077"
.\.venv\Scripts\python.exe -m assistant tool apps.resolve name="notepad"

# Screen Reading & Offline Local OCR (Phase 9A - Win32 + Windows.Media.Ocr)
.\.venv\Scripts\python.exe -m assistant tool ui.inspect_window
.\.venv\Scripts\python.exe -m assistant tool screen.capture
.\.venv\Scripts\python.exe -m assistant tool screen.capture target="active_window"
.\.venv\Scripts\python.exe -m assistant tool screen.ocr

# Isolated Browser Automation & Interactive Actions (Phase 9B & 9C - Playwright)
.\.venv\Scripts\python.exe -m assistant tool browser.open url="https://learn.microsoft.com"
.\.venv\Scripts\python.exe -m assistant tool browser.read max_chars=2000
.\.venv\Scripts\python.exe -m assistant tool browser.screenshot
.\.venv\Scripts\python.exe -m assistant tool browser.find_links query="documentation"
.\.venv\Scripts\python.exe -m assistant tool browser.type selector="input[type='search']" text="Windows Kernel"
.\.venv\Scripts\python.exe -m assistant tool browser.click selector="a.nav-link"

# Web Research & PCGamingWiki Tools
.\.venv\Scripts\python.exe -m assistant tool web.search query="0x116 VIDEO_TDR_FAILURE" max_results=3
.\.venv\Scripts\python.exe -m assistant tool web.fetch url="https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/bug-check-0x116---video-tdr-failure" max_chars=800
.\.venv\Scripts\python.exe -m assistant tool web.pcgamingwiki game_name="Cyberpunk 2077"

# List available diagnostic playbooks (7 available)
.\.venv\Scripts\python.exe -m assistant playbook list

# Run a diagnostic playbook directly
.\.venv\Scripts\python.exe -m assistant playbook bsod_crash_diagnosis
.\.venv\Scripts\python.exe -m assistant playbook disk_full_usage
.\.venv\Scripts\python.exe -m assistant playbook system_slowness
.\.venv\Scripts\python.exe -m assistant playbook app_crash_diagnosis
.\.venv\Scripts\python.exe -m assistant playbook game_save_analysis
.\.venv\Scripts\python.exe -m assistant playbook game_stutter
.\.venv\Scripts\python.exe -m assistant playbook app_investigation

# Natural Language Commands (Fast Path & Analysis Path with Playbooks)
.\.venv\Scripts\python.exe -m assistant ask "buka kuramanime"
.\.venv\Scripts\python.exe -m assistant ask "cari lofi di youtube"
.\.venv\Scripts\python.exe -m assistant ask "save game cyberpunk ada dimana ya"
.\.venv\Scripts\python.exe -m assistant ask "semalem laptop tiba2 layar biru, kenapa ya"
.\.venv\Scripts\python.exe -m assistant ask "disk gw 100% terus nih"
.\.venv\Scripts\python.exe -m assistant ask "laptop lemot banget kenapa ya"

# View recent SQLite audit logs
.\.venv\Scripts\python.exe -m assistant audit --limit 10

# Start interactive CLI REPL
.\.venv\Scripts\python.exe -m assistant
```

## Running Tests & Benchmark Evaluation
```powershell
# Run full unit test suite (272 tests, 100% PASS)
.\.venv\Scripts\python.exe -m unittest discover tests

# Run benchmark evaluation suite (30 test prompts, route & target accuracy)
.\.venv\Scripts\python.exe eval/run_eval.py
```

## Deploying to Target Laptop (Ruang Tamu)
Untuk mengimplementasikan Jarvis di laptop target / ruang tamu:
```powershell
# 1. Clone repository di laptop target
git clone https://github.com/yofanprayoga/jarvis.git
cd jarvis

# 2. Jalankan skrip setup otomatis
.\scripts\setup_target.ps1
```
