# Decision Log (DECISIONS.md)

This log records architecture and design decisions, changes, and their rationales as mandated by Rule 9 in [plan.md](file:///d:/project/jarvis/plan.md).

| Date | Decision | Rationale |
|---|---|---|
| 2026-09-28 | Phase 0 completed: Adopted master design from `plan.md` | Single source of truth for Jarvis-lite Windows PC assistant. |
| 2026-09-28 | Target hardware: i5-8250U, 8GB RAM, 930MX 2GB, SSD+HDD | Optimize for CPU-only inference (3B–4B Q4), lightweight telemetry without heavy frameworks. |
| 2026-09-28 | Plain Python + asyncio orchestration | Avoid heavy framework overhead (LangChain/LlamaIndex) on low-spec hardware. |
| 2026-09-28 | Two-path architecture (Fast Path + Analysis Path) | Instant response for common actions (<1s, no LLM); deterministic playbooks + LLM for diagnostics. |
| 2026-09-28 | Strict security model with 4 risk levels (L0-L3) and Elevated Helper | Model cannot alter permissions or run arbitrary shell code; admin tasks run via separate UAC-gated helper. |
| 2026-09-28 | Phase 1 completed: Core Foundation & 10 System Tools | Established schema-validated tool contracts, PolicyEngine, SQLite audit log, and CLI without LLM dependencies. |
| 2026-09-28 | Isolated local `.venv` with Python 3.11 user-scope | Prevents system-wide package pollution and satisfies Rule 3 (no Windows system modification). |
| 2026-09-28 | Explicit connection closing on SQLite audit logger | Solves Windows WinError 32 file locking during tests and background access. |
| 2026-09-28 | Fixed PowerShell JSON query templates (`ConvertTo-Json`) | Eliminates fragile regex text scraping and guarantees structured data for all WMI/CIM/Counter queries. |
| 2026-09-28 | 1500-character ceiling on `ToolResult.summary` | Protects limited context window and prompt-processing latency on CPU-only 3B–4B LLMs. |
| 2026-09-28 | Phase 2 completed: Fast-Path Intent Router & Launch Tools | Ultra-fast (<100ms) execution for opening URLs, searching YouTube/Google, launching apps, and opening folders without LLM overhead. |
| 2026-09-28 | Dual-tier Site Manager (YAML seed + SQLite dynamic learning) | Solves changing mirror domains (e.g., Kuramanime, Idlix) by allowing dynamic updates saved into local SQLite. |
| 2026-09-28 | Conversational filler word normalization | Robust pattern matching for natural Indonesian/English commands (tolong, dong, coba, please) while preserving URL dots. |
| 2026-09-28 | Start Menu and App Paths indexing | Discovers installed user applications via `.lnk` files without hardcoding absolute paths. |
| 2026-09-28 | Phase 3 completed: Local LLM Integration & Evaluation Suite | Connected structured JSON planner, explainer, tool selector, and 30-case evaluation suite (100% accuracy). |
| 2026-09-28 | Tri-Provider LLM abstraction (Ollama, OpenAI-compat, Mock) | Supports local Ollama with `keep_alive`, OpenAI-compatible servers, and instant offline dev/test execution without heavy GPU/RAM requirements. |
| 2026-09-28 | Keyword Tool Selector for Prompt Optimization | Sends only 3–5 relevant tool schemas per request to keep CPU inference fast on i5-8250U. |
| 2026-09-28 | Automated Target Laptop Deployment Script (`scripts/setup_target.ps1`) | Separates dev workstation development from living-room target laptop with 1-click deployment. |
| 2026-09-28 | Phase 4 completed: Diagnostics Playbooks & Crash Analysis | Deterministic YAML playbooks (`bsod_crash_diagnosis`, `app_crash_diagnosis`, `disk_full_usage`, `system_slowness`) with conditional step execution, heuristic rule findings, and bugcheck offline lookup table. |
| 2026-09-28 | Offline BugCheck Lookup Database (Appendix C) | Instant offline analysis of Windows crash codes (0x116 TDR, 0x124 WHEA, 0x1A MEMORY, 0x133 DPC, etc.) without requiring internet access. |
| 2026-09-28 | Dot-notation `AttrDict` and restricted expression evaluation | Allows playbook `when` conditions and heuristic rules (e.g. `events.data.kernel_power_41_count > 0 and not events.data.bugcheck_codes`) to safely evaluate against structured data without arbitrary code execution risks. |
| 2026-09-28 | Graceful degradation for crash minidumps | When `cdb.exe` is absent or minidumps are blocked by UAC, playbooks fall back to Event Log 1001, BugCheck seed tables, and update history. |
| 2026-09-28 | Phase 5 completed: Tray UI & Background Mode | Integrated `pystray` system tray, lightweight dark-mode Tkinter chat window (~45 MB RAM), native Windows `RegisterHotKey` listener (Ctrl+Shift+J), L3 modal confirmation dialog, markdown report exporter, and Task Scheduler logon installer. |
| 2026-09-28 | Native Windows `RegisterHotKey` via ctypes | Provides zero-overhead global hotkey capture without third-party driver or heavy keyboard hook hooks. |
| 2026-09-28 | Built-in Tkinter over heavy webview/Electron | Guarantees < 50 MB RAM idle footprint on low-spec living room laptop while keeping desktop UI ultra responsive. |
| 2026-09-28 | Background worker thread for UI interactions | Prevents UI freezing during multi-second diagnostics or LLM inference with cancellation/kill switch support. |
| 2026-09-28 | Phase 6 completed: Web Research Pipeline & PCGamingWiki | Built `SearchProvider` (`ddgs` / `duckduckgo_search` + offline `MockSearchProvider`), `WebFetcher` with clean text extraction, local TTL disk cache (`data/cache/web/`), `PCGamingWikiClient` MediaWiki parser, and `WebResearcher` pipeline. |
| 2026-09-28 | Rule 7 prompt-injection defense with untrusted tags | External web data is strictly tagged `<untrusted_web_source>` and treated as passive data; instructions embedded within websites can never trigger an action or policy escalation. |
| 2026-09-28 | Domain prioritization for technical troubleshooting | Ranks official documentation (`learn.microsoft.com`, `pcgamingwiki.com`, `nvidia.com`, `intel.com`) higher than generic search results. |
| 2026-09-28 | Phase 7 completed: Game & App Investigation, File Inspection & Backup | Implemented Steam/Epic game discovery (`games.list_installed`), save/config locator (`games.find_save_and_config`), Shannon entropy calculation and format detection (`files.inspect`), allowlisted text reading (`files.read_text`), timestamped SHA-256 backup with rollback manifest (`files.backup`), executable resolver and Authenticode inspector (`apps.resolve`, `apps.inspect`, `apps.get_cli_help`), and 3 new diagnostic playbooks (`game_save_analysis`, `game_stutter`, `app_investigation`). |
| 2026-09-28 | Shannon Entropy for game save encryption detection | Byte entropy > 7.2 accurately flags encrypted or compressed save formats before attempting textual modifications. |
| 2026-09-28 | Multi-drive Steam VDF and ACF parser | Reads `libraryfolders.vdf` and `appmanifest_*.acf` directly, discovering installed games across multiple SSD/HDD drives without requiring Steam API keys or client runtime. |
