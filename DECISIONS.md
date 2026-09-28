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
