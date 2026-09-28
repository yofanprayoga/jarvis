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


def cmd_ask(args: argparse.Namespace) -> None:
    """Handle natural language command via the Fast-Path Intent Router."""
    query = " ".join(args.text).strip()
    if not query:
        print("[ERROR] Masukkan perintah. Contoh: assistant ask 'buka youtube'", file=sys.stderr)
        sys.exit(1)

    route_res = intent_router.route(query)
    if route_res.matched:
        print(f"\n[FAST PATH: {route_res.intent}]")
        print(f"Tool: {route_res.tool_name}")
        print("-" * 60)
        print(route_res.message)
        print("-" * 60)
    else:
        print(f"\n[UNMATCHED] {route_res.message}")


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
        if line.lower() == "help":
            print(
                "Perintah Alami (Fast Path):\n"
                "  buka <youtube|kuramanime|idlix|google|chrome|folder>\n"
                "  cari <judul> di youtube\n"
                "  cari <topik> di google\n"
                "  update <alias> <url>\n\n"
                "Perintah Tool Langsung:\n"
                "  list                 - Daftar tool terdaftar\n"
                "  audit                - Lihat log audit SQLite\n"
                "  system.get_overview  - Jalankan tool langsung\n"
                "  exit                 - Keluar"
            )
            continue

        # Check if first word is a direct tool name
        parts = line.split()
        if registry.get(parts[0]):
            params = parse_kwarg_pairs(parts[1:])
            res = orchestrator.run_tool(parts[0], params)
            if res.ok:
                print(f"\n[OK] {res.summary}")
            else:
                print(f"\n[ERROR] {res.error}")
            continue

        # Otherwise, process through Fast-Path Intent Router
        route_res = intent_router.route(line)
        if route_res.matched:
            print(f"\n[FAST PATH: {route_res.intent}] {route_res.message}")
        else:
            print(f"\n[INFO] {route_res.message}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis-lite PC Assistant CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # 'list' command
    subparsers.add_parser("list", help="List registered tools")

    # 'ask' command
    ask_parser = subparsers.add_parser("ask", help="Send a natural language command")
    ask_parser.add_argument("text", nargs="+", help="Natural language query")

    # 'tool' command
    tool_parser = subparsers.add_parser("tool", help="Execute a specific tool")
    tool_parser.add_argument("name", help="Name of tool to execute")
    tool_parser.add_argument("params", nargs="*", help="Optional key=value parameters")
    tool_parser.add_argument("--json-args", dest="json_args", help="Arguments formatted as a JSON object string")
    tool_parser.add_argument("--json", dest="raw_json", action="store_true", help="Print full structured data as JSON")

    # 'audit' command
    audit_parser = subparsers.add_parser("audit", help="View recent audit log entries")
    audit_parser.add_argument("--limit", type=int, default=15, help="Number of records to display")

    # 'repl' command
    subparsers.add_parser("repl", help="Start interactive REPL")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list(args)
    elif args.command == "ask":
        cmd_ask(args)
    elif args.command == "tool":
        cmd_tool(args)
    elif args.command == "audit":
        cmd_audit(args)
    elif args.command == "repl" or args.command is None:
        cmd_repl()


if __name__ == "__main__":
    main()
