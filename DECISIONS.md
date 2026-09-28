# Decision Log (DECISIONS.md)

This log records architecture and design decisions, changes, and their rationales as mandated by Rule 9 in [plan.md](file:///d:/project/jarvis/plan.md).

| Date | Decision | Rationale |
|---|---|---|
| 2026-09-28 | Phase 0 completed: Adopted master design from `plan.md` | Single source of truth for Jarvis-lite Windows PC assistant. |
| 2026-09-28 | Target hardware: i5-8250U, 8GB RAM, 930MX 2GB, SSD+HDD | Optimize for CPU-only inference (3B–4B Q4), lightweight telemetry without heavy frameworks. |
| 2026-09-28 | Plain Python + asyncio orchestration | Avoid heavy framework overhead (LangChain/LlamaIndex) on low-spec hardware. |
| 2026-09-28 | Two-path architecture (Fast Path + Analysis Path) | Instant response for common actions (<1s, no LLM); deterministic playbooks + LLM for diagnostics. |
| 2026-09-28 | Strict security model with 4 risk levels (L0-L3) and Elevated Helper | Model cannot alter permissions or run arbitrary shell code; admin tasks run via separate UAC-gated helper. |
