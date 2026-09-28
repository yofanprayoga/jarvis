"""Explainer prompt templates (Section 10.3 & Appendix B)."""

from __future__ import annotations

EXPLAINER_SYSTEM_PROMPT = """You explain diagnostic findings and tool results to a non-expert Windows PC owner.
Use ONLY the findings provided below. Ground your answer strictly in the facts.

Required Structure:
1) Apa yang ditemukan (fakta jelas, sebutkan sumbernya: CPU/RAM/Disk/Event Log/dll)
2) Kemungkinan penyebab (diurutkan dari yang paling mungkin; beri label tiap poin: [pasti] / [kemungkinan besar] / [dugaan])
3) Langkah berikutnya (pisahkan dengan jelas antara tindakan "aman dicoba sendiri" dan "perlu persetujuan kamu")

Tone:
- Ringkas, jelas, to the point.
- Jika data kurang lengkap, sebutkan apa yang kurang.
- Balas dalam Bahasa Indonesia (kecuali user bertanya dalam Bahasa Inggris).
"""


def build_explainer_prompt(user_query: str, findings: str) -> tuple[str, str]:
    """Build (system_prompt, user_prompt) for the LLM explainer."""
    user = (
        f"Pertanyaan User: {user_query}\n\n"
        f"Hasil Temuan Sistem / Diagnosa:\n{findings}\n\n"
        f"Berikan penjelasan dan rekomendasi sesuai panduan."
    )
    return EXPLAINER_SYSTEM_PROMPT, user
