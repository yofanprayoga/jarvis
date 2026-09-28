"""Markdown report generation for diagnostic findings and sessions (Section 13)."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Optional


def get_reports_dir() -> Path:
    """Ensure and return the reports directory."""
    reports_dir = Path("data/reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir


def save_markdown_report(
    title: str,
    query: str,
    response: str,
    findings: Optional[str] = None,
    rule_findings: Optional[list[str]] = None,
    playbook_name: Optional[str] = None,
    tool_name: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Path:
    """Save a structured markdown diagnostic report to data/reports/."""
    reports_dir = get_reports_dir()
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_slug = "".join(c if c.isalnum() else "_" for c in title.lower())[:30].strip("_")
    filename = f"report_{timestamp_str}_{safe_slug}.md"
    file_path = reports_dir / filename

    now_display = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        f"# Laporan Diagnosa: {title}",
        "",
        f"- **Waktu Pembuatan:** {now_display}",
        f"- **Perintah Pengguna:** `{query}`",
    ]

    if playbook_name:
        lines.append(f"- **Playbook:** `{playbook_name}`")
    if tool_name:
        lines.append(f"- **Tool:** `{tool_name}`")

    lines.extend([
        "",
        "---",
        "",
        "## Ringkasan & Rekomendasi Asisten",
        "",
        response.strip(),
        "",
    ])

    if rule_findings:
        lines.extend([
            "---",
            "",
            "## Temuan Aturan Diagnosa (Rule Findings)",
            "",
        ])
        for rf in rule_findings:
            lines.append(f"- {rf}")
        lines.append("")

    if findings:
        lines.extend([
            "---",
            "",
            "## Data Telemetri & Temuan Sistem (Raw Findings)",
            "",
            "```text",
            findings.strip(),
            "```",
            "",
        ])

    if metadata:
        lines.extend([
            "---",
            "",
            "## Metadata Tambahan",
            "",
            "```json",
            str(metadata),
            "```",
            "",
        ])

    lines.extend([
        "---",
        f"*Dibuat secara otomatis oleh Jarvis-lite Windows PC Assistant.*",
        "",
    ])

    file_path.write_text("\n".join(lines), encoding="utf-8")
    return file_path
