"""Mock LLM Provider for rapid offline development, testing, and CI (Section 7.1)."""

from __future__ import annotations

from typing import Any, Optional
from assistant.llm.client import LLMClient


class MockLLMClient(LLMClient):
    """Deterministic, lightweight mock LLM returning valid JSON contracts."""

    def __init__(self, healthy: bool = True) -> None:
        self._healthy = healthy

    def is_healthy(self) -> bool:
        return self._healthy

    def warm_up(self) -> bool:
        return True

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        # Explainer response template
        return (
            "1) Apa yang ditemukan:\n"
            "- Berdasarkan diagnosa telemetri sistem, pemakaian CPU dan RAM telah dianalisis.\n\n"
            "2) Kemungkinan penyebab:\n"
            "- [kemungkinan besar] Aplikasi latar belakang mengonsumsi resource tinggi.\n"
            "- [dugaan] Beban kerja browser atau tab aktif.\n\n"
            "3) Langkah berikutnya:\n"
            "- [aman dicoba]: Tutup tab atau proses yang tidak terpakai.\n"
            "- [perlu persetujuan kamu]: Menutup paksa proses spesifik jika masih macet."
        )

    def generate_json(
        self,
        prompt: str,
        system: str,
        schema: Optional[dict[str, Any]] = None,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        p = prompt.lower()

        # Diagnostic playbooks
        if "bsod" in p or "layar biru" in p or "crash" in p:
            return {"type": "playbook", "name": "bsod_crash_diagnosis", "args": {}}
        if "disk 100" in p or "100%" in p or "penyimpanan" in p:
            return {"type": "playbook", "name": "disk_full_usage", "args": {}}
        if "lemot" in p or "lambat" in p:
            return {"type": "playbook", "name": "system_slowness", "args": {}}

        # Tool calls - prioritize process queries before component metrics
        if "proses" in p or "process" in p or "boros" in p:
            return {"type": "tool_call", "tool": "process.list_top", "args": {"by": "cpu", "count": 5}}
        if "cpu" in p or "processor" in p:
            return {"type": "tool_call", "tool": "system.get_cpu", "args": {"interval_s": 0.5}}
        if "ram" in p or "memori" in p or "memory" in p:
            return {"type": "tool_call", "tool": "system.get_memory", "args": {}}
        if "disk" in p or "storage" in p:
            return {"type": "tool_call", "tool": "system.get_disks", "args": {}}
        if "gpu" in p or "vga" in p:
            return {"type": "tool_call", "tool": "system.get_gpu_info", "args": {}}
        if "spek" in p or "spesifikasi" in p or "overview" in p:
            return {"type": "tool_call", "tool": "system.get_overview", "args": {}}

        # Greetings / informational
        if "halo" in p or "hai" in p or "siapa kamu" in p:
            return {"type": "answer", "text": "Halo! Saya Jarvis, asisten PC operator kamu."}

        # Clarification fallback
        return {"type": "clarify", "question": "Bisa tolong jelaskan lebih spesifik apa yang ingin kamu periksa?"}
