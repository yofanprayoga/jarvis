from __future__ import annotations

import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
from assistant.core.orchestrator import orchestrator


def run_evaluation(eval_file: str = "eval/intents_eval.yaml") -> dict[str, float]:
    p = Path(eval_file)
    if not p.is_file():
        print(f"Eval file not found: {eval_file}")
        return {}

    with open(p, "r", encoding="utf-8") as f:
        test_cases = yaml.safe_load(f) or []

    total = len(test_cases)
    route_correct = 0
    target_correct = 0
    latencies = []

    print(f"\nRunning Jarvis Intent & Planner Evaluation ({total} test cases)...")
    print("=" * 80)
    print(f"{'#':<3} | {'Input':<38} | {'Exp Route':<10} | {'Act Route':<10} | {'Status'}")
    print("-" * 80)

    for i, tc in enumerate(test_cases, 1):
        user_input = tc["input"]
        exp_route = tc["expect_route"]
        exp_tool = tc.get("expect_tool")
        exp_playbook = tc.get("expect_playbook")
        exp_type = tc.get("expect_type")

        t_start = time.perf_counter()
        res = orchestrator.handle_request(user_input)
        elapsed_ms = (time.perf_counter() - t_start) * 1000.0
        latencies.append(elapsed_ms)

        act_route = res.get("route", "unknown")
        act_tool = res.get("tool")
        act_playbook = res.get("playbook")
        act_type = res.get("type")

        # Route matching
        is_route_ok = (act_route == exp_route)
        if is_route_ok:
            route_correct += 1

        # Target matching
        is_target_ok = True
        if exp_tool and act_tool != exp_tool:
            is_target_ok = False
        if exp_playbook and act_playbook != exp_playbook:
            is_target_ok = False
        if exp_type and act_type != exp_type:
            is_target_ok = False

        if is_route_ok and is_target_ok:
            target_correct += 1
            status_str = f"PASS ({elapsed_ms:.1f}ms)"
        else:
            status_str = f"FAIL (got {act_tool or act_playbook or act_type})"

        input_display = user_input[:35] + "..." if len(user_input) > 35 else user_input
        print(f"{i:<3} | {input_display:<38} | {exp_route:<10} | {act_route:<10} | {status_str}")

    print("=" * 80)
    route_acc = (route_correct / total) * 100.0 if total else 0.0
    target_acc = (target_correct / total) * 100.0 if total else 0.0
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

    print(f"\nEvaluation Results:")
    print(f"- Total Test Cases: {total}")
    print(f"- Route Accuracy (Fast vs LLM): {route_acc:.1f}% (Target: >= 95%)")
    print(f"- Target Accuracy (Tool/Playbook Choice): {target_acc:.1f}% (Target: >= 85%)")
    print(f"- Average Latency: {avg_latency:.1f} ms")

    return {
        "total": total,
        "route_accuracy": route_acc,
        "target_accuracy": target_acc,
        "avg_latency_ms": avg_latency,
    }


if __name__ == "__main__":
    run_evaluation()
