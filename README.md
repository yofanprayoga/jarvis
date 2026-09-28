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
- [ ] **Phase 4:** Diagnostics Playbooks (BSOD, Crashes, Disk 100%)
- [ ] **Phase 5:** Tray UI & Background Mode
- [ ] **Phase 6:** Web Research Pipeline
- [ ] **Phase 7:** Game & App Investigation
- [ ] **Phase 8:** Controlled Modifications (L3 Safe Edits)
- [ ] **Phase 9:** Browser Automation & Screen Reading
- [ ] **Phase 10:** Desktop GUI Interaction
- [ ] **Phase 11:** Voice (Mic standby / Push-to-Talk + Piper TTS)
- [ ] **Phase 12:** Cloud LLM & Extensions

## Quick Start (Phase 1 CLI)

Activate the local environment and run tools:
```powershell
# List all 10 registered tools
.\.venv\Scripts\python.exe -m assistant list

# Run a specific tool (e.g., system overview, disk health, memory)
.\.venv\Scripts\python.exe -m assistant tool system.get_overview
.\.venv\Scripts\python.exe -m assistant tool system.get_cpu interval_s=0.5
.\.venv\Scripts\python.exe -m assistant tool system.get_memory
.\.venv\Scripts\python.exe -m assistant tool system.get_disks
.\.venv\Scripts\python.exe -m assistant tool process.list_top by=memory count=5

# Fast Path (Jalur Cepat < 1 detik)
.\.venv\Scripts\python.exe -m assistant ask "buka kuramanime"
.\.venv\Scripts\python.exe -m assistant ask "buka web idlix dong"
.\.venv\Scripts\python.exe -m assistant ask "cari lofi di youtube"
.\.venv\Scripts\python.exe -m assistant ask "buka folder download"
.\.venv\Scripts\python.exe -m assistant ask "update kuramanime https://v21.kuramanime.ing/"

# View recent SQLite audit logs
.\.venv\Scripts\python.exe -m assistant audit --limit 10

# Start interactive CLI REPL
.\.venv\Scripts\python.exe -m assistant
```

## Running Tests & Benchmark Evaluation
```powershell
# Run unit tests (37 tests)
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
