"""Command Line Interface (CLI) for Jarvis."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
import assistant.tools  # ensure all tools are registered
from assistant.core.audit import audit_logger
from assistant.core.orchestrator import orchestrator
from assistant.core.router import intent_router
from assistant.tools.registry import registry


def parse_kwarg_pairs(pair_list: list[str]) -> dict[str, Any]:
    """Parse list of key=val arguments into typed python dictionary."""
    result = {}
    for item in pair_list:
        if "=" not in item:
            continue
        key, val = item.split("=", 1)
        key = key.strip()
        val = val.strip()

        # Type conversion attempt
        if val.lower() == "true":
            result[key] = True
        elif val.lower() == "false":
            result[key] = False
        else:
            try:
                if "." in val:
                    result[key] = float(val)
                else:
                    result[key] = int(val)
            except ValueError:
                result[key] = val
    return result


def cmd_list(args: argparse.Namespace) -> None:
    """List all registered tools and their risk levels."""
    tools = registry.list_tools()
    print(f"\nRegistered Tools ({len(tools)} available):")
    print("-" * 75)
    print(f"{'Tool Name':<28} | {'Risk Level':<12} | {'Description'}")
    print("-" * 75)
    for t in sorted(tools, key=lambda x: x.name):
        print(f"{t.name:<28} | {t.risk.name:<12} | {t.description[:60]}")
    print("-" * 75)


def cmd_tool(args: argparse.Namespace) -> None:
    """Execute a tool via the orchestrator."""
    tool_args = {}
    if args.json_args:
        try:
            tool_args = json.loads(args.json_args)
        except json.JSONDecodeError as jde:
            print(f"[ERROR] Invalid JSON in --json-args: {jde}", file=sys.stderr)
            sys.exit(1)
    elif args.params:
        tool_args = parse_kwarg_pairs(args.params)

    res = orchestrator.run_tool(args.name, tool_args)

    if res.ok:
        print(f"\n[OK] Tool '{args.name}' executed successfully.")
        print("-" * 60)
        print(res.summary)
        print("-" * 60)
        if args.raw_json:
            print("\n[Structured Data]:")
            print(json.dumps(res.data, indent=2, default=str))
    else:
        print(f"\n[FAIL] Tool '{args.name}' failed: {res.error}", file=sys.stderr)
        if res.summary:
            print(res.summary, file=sys.stderr)
        sys.exit(1)


def cmd_playbook(args: argparse.Namespace) -> None:
    """Execute a diagnostic playbook directly."""
    from assistant.playbooks.engine import playbook_engine

    if not args.name or args.name == "list":
        playbooks = playbook_engine.list_playbooks()
        print(f"\nAvailable Playbooks ({len(playbooks)}):")
        print("-" * 75)
        for pb_name in sorted(playbooks):
            pb = playbook_engine.get(pb_name)
            desc = pb.description if pb else ""
            print(f"- {pb_name:<25} | {desc}")
        print("-" * 75)
        return

    pb_args = {}
    if args.json_args:
        try:
            pb_args = json.loads(args.json_args)
        except json.JSONDecodeError as jde:
            print(f"[ERROR] Invalid JSON in --json-args: {jde}", file=sys.stderr)
            sys.exit(1)
    elif args.params:
        pb_args = parse_kwarg_pairs(args.params)

    print(f"\n[MENJALANKAN PLAYBOOK: {args.name}]...")
    res = playbook_engine.run(args.name, pb_args)

    if res.ok:
        print(f"\n[OK] Playbook '{args.name}' selesai.")
        print("=" * 60)
        print(res.summary)
        print("=" * 60)
        if args.raw_json:
            print("\n[Structured Data]:")
            print(json.dumps(res.data, indent=2, default=str))
    else:
        print(f"\n[FAIL] Playbook '{args.name}' gagal: {res.summary}", file=sys.stderr)
        sys.exit(1)


def cmd_ask(args: argparse.Namespace) -> None:
    """Handle natural language command via Orchestrator (Fast-Path -> LLM/Playbook)."""
    query = " ".join(args.text).strip()
    if not query:
        print("[ERROR] Masukkan perintah. Contoh: assistant ask 'buka youtube'", file=sys.stderr)
        sys.exit(1)

    res = orchestrator.handle_request(query)
    route = res.get("route", "unknown")

    if route == "fast":
        print(f"\n[FAST PATH: {res.get('intent')}]")
        print(f"Tool: {res.get('tool')}")
        print("-" * 60)
        print(res.get("response"))
        print("-" * 60)
    else:
        res_type = res.get("type", "response")
        print(f"\n[ANALYSIS PATH: {res_type.upper()}]")
        if res.get("playbook"):
            print(f"Playbook: {res.get('playbook')}")
        elif res.get("tool"):
            print(f"Tool: {res.get('tool')}")
        print("-" * 60)
        print(res.get("response"))
        print("-" * 60)


def cmd_voice(args: argparse.Namespace) -> None:
    """Execute a voice input command (Microphone -> local STT -> Orchestrator)."""
    from assistant.voice.voice_controller import voice_controller

    duration = getattr(args, "duration", 4.0) or 4.0
    language = getattr(args, "language", "id") or "id"
    dry_run = getattr(args, "dry_run", False)
    device_id = getattr(args, "device", 0) or 0

    print("\n" + "=" * 60)
    print("JARVIS VOICE INPUT (Microphone -> Local STT)")
    print("=" * 60)
    print(f"Merekam selama {duration:.1f} detik dari microphone (bahasa: {language})...")
    print("Silakan bicara sekarang...")

    res = voice_controller.listen_and_execute(
        duration_s=duration,
        language=language,
        dry_run=dry_run,
        device_id=device_id,
    )

    if not res.ok:
        print(f"\n[ERROR] Gagal memproses suara ({res.status}): {res.error}", file=sys.stderr)
        if not getattr(args, "_in_repl", False):
            sys.exit(1)
        return

    print(f"\n[TRANSKRIPSI] \"{res.transcript}\" ({res.stt_duration_ms:.1f} ms, bahasa={res.language})")

    if dry_run:
        print("[DRY RUN] Perintah tidak dieksekusi ke Orchestrator.")
        return

    orch_res = res.orchestrator_result or {}
    route = orch_res.get("route", "unknown")
    if route == "fast":
        print(f"\n[FAST PATH: {orch_res.get('intent')}] {orch_res.get('response')}")
    else:
        print(f"\n[ANALYSIS: {orch_res.get('type', 'response').upper()}]")
        if orch_res.get("playbook"):
            print(f"Playbook: {orch_res.get('playbook')}")
        print(orch_res.get("response"))


def cmd_audit(args: argparse.Namespace) -> None:
    """Display recent audit logs."""
    logs = audit_logger.get_recent(limit=args.limit)
    if not logs:
        print("\nAudit log is currently empty.")
        return

    print(f"\nRecent Audit Log Entries (showing last {len(logs)}):")
    print("=" * 85)
    for entry in logs:
        status = "OK" if entry["ok"] else "FAIL"
        print(
            f"[{entry['id']}] {entry['timestamp']} | {entry['tool_name']} | "
            f"Risk: {entry['risk_level']} | {status} ({entry['duration_ms']:.1f}ms)"
        )
        if entry["error"]:
            print(f"    Error: {entry['error']}")
        elif entry["summary"]:
            first_line = entry["summary"].split("\n")[0]
            print(f"    Summary: {first_line[:80]}")
    print("=" * 85)


def cmd_repl() -> None:
    """Interactive command shell with Fast-Path Router support."""
    print("=" * 65)
    print(" Jarvis-lite CLI Shell (Phase 1 & 2)")
    print(" Ketik perintah biasa (misal 'buka youtube', 'cari lofi di youtube')")
    print(" Perintah sistem: 'list', 'audit', 'help', 'exit'")
    print("=" * 65)

    while True:
        try:
            line = input("\njarvis> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not line:
            continue
        if line.lower() in ("exit", "quit", "q"):
            print("Goodbye!")
            break
        if line.lower() == "list":
            cmd_list(argparse.Namespace())
            continue
        if line.lower().startswith("audit"):
            cmd_audit(argparse.Namespace(limit=15))
            continue
        if line.lower() in ("voice", "v"):
            cmd_voice(argparse.Namespace(duration=4.0, language="id", dry_run=False, device=0, _in_repl=True))
            continue
        if line.lower() == "help":
            print(
                "Perintah Alami (Fast Path):\n"
                "  buka <youtube|kuramanime|idlix|google|chrome|folder>\n"
                "  cari <judul> di youtube\n"
                "  cari <topik> di google\n"
                "  update <alias> <url>\n\n"
                "Perintah Tool Langsung:\n"
                "  voice / v            - Rekam perintah suara lewat microphone\n"
                "  list                 - Daftar tool terdaftar\n"
                "  audit                - Lihat log audit SQLite\n"
                "  system.get_overview  - Jalankan tool langsung\n"
                "  exit                 - Keluar"
            )
            continue

        # Check if first word is 'playbook'
        if parts[0] == "playbook":
            pb_name = parts[1] if len(parts) > 1 else "list"
            pb_params = parse_kwarg_pairs(parts[2:]) if len(parts) > 2 else {}
            cmd_playbook(argparse.Namespace(name=pb_name, params=[], json_args=None, raw_json=False))
            continue

        # Check if first word is a direct tool name
        if registry.get(parts[0]):
            params = parse_kwarg_pairs(parts[1:])
            res = orchestrator.run_tool(parts[0], params)
            if res.ok:
                print(f"\n[OK] {res.summary}")
            else:
                print(f"\n[ERROR] {res.error}")
            continue

        # Otherwise, process through full Orchestrator (Fast-Path -> LLM/Playbook)
        res = orchestrator.handle_request(line)
        route = res.get("route", "unknown")
        if route == "fast":
            print(f"\n[FAST PATH: {res.get('intent')}] {res.get('response')}")
        else:
            print(f"\n[ANALYSIS: {res.get('type', 'response').upper()}]")
            if res.get("playbook"):
                print(f"Playbook: {res.get('playbook')}")
            print(res.get("response"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis-lite PC Assistant CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # 'list' command
    subparsers.add_parser("list", help="List registered tools")

    # 'ask' command
    ask_parser = subparsers.add_parser("ask", help="Send a natural language command")
    ask_parser.add_argument("text", nargs="+", help="Natural language query")

    # 'voice' command
    voice_parser = subparsers.add_parser("voice", help="Record speech and execute as natural language command")
    voice_parser.add_argument("--duration", type=float, default=4.0, help="Recording duration in seconds (default: 4.0)")
    voice_parser.add_argument("--language", default="id", help="Language code (id, en, or auto)")
    voice_parser.add_argument("--dry-run", action="store_true", help="Only transcribe speech without executing")
    voice_parser.add_argument("--device", type=int, default=0, help="Microphone device ID (default: 0)")

    # 'playbook' command
    playbook_parser = subparsers.add_parser("playbook", help="Execute or list diagnostic playbooks")
    playbook_parser.add_argument("name", nargs="?", default="list", help="Playbook name to execute (or 'list')")
    playbook_parser.add_argument("params", nargs="*", help="Optional key=value parameters")
    playbook_parser.add_argument("--json-args", dest="json_args", help="Arguments formatted as a JSON object string")
    playbook_parser.add_argument("--json", dest="raw_json", action="store_true", help="Print full structured data as JSON")

    # 'tool' command
    tool_parser = subparsers.add_parser("tool", help="Execute a specific tool")
    tool_parser.add_argument("name", help="Name of tool to execute")
    tool_parser.add_argument("params", nargs="*", help="Optional key=value parameters")
    tool_parser.add_argument("--json-args", dest="json_args", help="Arguments formatted as a JSON object string")
    tool_parser.add_argument("--json", dest="raw_json", action="store_true", help="Print full structured data as JSON")

    # 'audit' command
    audit_parser = subparsers.add_parser("audit", help="View recent audit log entries")
    audit_parser.add_argument("--limit", type=int, default=15, help="Number of records to display")

    # 'tray' command
    subparsers.add_parser("tray", help="Run background system tray app and hotkey listener")

    # 'chat' command
    subparsers.add_parser("chat", help="Open the dark mode chat window directly")

    # 'repl' command
    subparsers.add_parser("repl", help="Start interactive REPL")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list(args)
    elif args.command == "ask":
        cmd_ask(args)
    elif args.command == "voice":
        cmd_voice(args)
    elif args.command == "playbook":
        cmd_playbook(args)
    elif args.command == "tool":
        cmd_tool(args)
    elif args.command == "audit":
        cmd_audit(args)
    elif args.command == "tray":
        from assistant.ui.tray import run_tray_app
        run_tray_app()
    elif args.command == "chat":
        from assistant.ui.chat_window import ChatWindow
        w = ChatWindow()
        w.run_main_loop()
    elif args.command == "repl" or args.command is None:
        cmd_repl()


if __name__ == "__main__":
    main()

