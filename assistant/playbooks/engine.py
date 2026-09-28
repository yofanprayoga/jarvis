"""Playbook Execution Engine (Section 11)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional
import yaml

from assistant.playbooks.models import (
    PlaybookDefinition,
    PlaybookResult,
    PlaybookStep,
    PlaybookStepResult,
)


class AttrDict(dict):
    """Dictionary supporting dot-notation attribute access and nested wrapping."""

    def __getattr__(self, item: str) -> Any:
        try:
            val = self[item]
        except KeyError:
            return None
        return self._wrap(val)

    def __getitem__(self, item: Any) -> Any:
        val = super().get(item)
        return self._wrap(val)

    @classmethod
    def _wrap(cls, val: Any) -> Any:
        if isinstance(val, dict) and not isinstance(val, AttrDict):
            return AttrDict(val)
        if isinstance(val, list):
            return [cls._wrap(x) for x in val]
        return val


def safe_eval(expr: str, context: dict[str, Any]) -> bool:
    """Safely evaluate a boolean expression with context variables and dot access."""
    if not expr or not expr.strip():
        return True

    safe_builtins = {
        "len": len,
        "int": int,
        "float": float,
        "str": str,
        "bool": bool,
        "list": list,
        "any": any,
        "all": all,
    }
    safe_globals = {
        "__builtins__": safe_builtins,
        "true": True,
        "false": False,
        "null": None,
        "True": True,
        "False": False,
        "None": None,
    }
    wrapped = {k: AttrDict._wrap(v) for k, v in context.items()}
    try:
        res = eval(expr, safe_globals, wrapped)
        return bool(res)
    except Exception:
        return False


def resolve_template_value(val: Any, context: dict[str, Any]) -> Any:
    """Resolve templated variables like '{days}' or '{dumps.data.latest}' from context."""
    if not isinstance(val, str):
        return val

    s = val.strip()
    # Check if exact single placeholder like "{dumps.data.latest}"
    if s.startswith("{") and s.endswith("}") and s.count("{") == 1 and s.count("}") == 1:
        expr = s[1:-1].strip()
        safe_builtins = {
            "len": len,
            "int": int,
            "float": float,
            "str": str,
            "bool": bool,
            "list": list,
        }
        safe_globals = {
            "__builtins__": safe_builtins,
            "true": True,
            "false": False,
            "null": None,
        }
        wrapped = {k: AttrDict._wrap(v) for k, v in context.items()}
        try:
            return eval(expr, safe_globals, wrapped)
        except Exception:
            return None

    # Mixed string interpolation like "prefix {var} suffix"
    def repl(match: re.Match) -> str:
        expr = match.group(1).strip()
        safe_globals = {"__builtins__": {}}
        wrapped = {k: AttrDict._wrap(v) for k, v in context.items()}
        try:
            res = eval(expr, safe_globals, wrapped)
            return str(res) if res is not None else ""
        except Exception:
            return ""

    return re.sub(r"\{([^}]+)\}", repl, s)


class PlaybookEngine:
    """Loads, validates, and runs deterministic diagnostic playbooks."""

    def __init__(
        self,
        definitions_dir: str | Path | None = None,
        orchestrator: Any | None = None,
    ) -> None:
        if definitions_dir is None:
            self.definitions_dir = Path(__file__).parent / "definitions"
        else:
            self.definitions_dir = Path(definitions_dir)

        self._orch = orchestrator
        self._definitions: dict[str, PlaybookDefinition] = {}
        self.reload()

    @property
    def orchestrator(self) -> Any:
        if self._orch is None:
            from assistant.core.orchestrator import orchestrator
            self._orch = orchestrator
        return self._orch

    def reload(self) -> None:
        """Scan definitions directory and reload all YAML playbooks."""
        self._definitions.clear()
        if not self.definitions_dir.is_dir():
            return

        for yml_file in self.definitions_dir.glob("*.yaml"):
            try:
                with open(yml_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict) and "name" in data:
                    playbook = PlaybookDefinition(**data)
                    self._definitions[playbook.name] = playbook
            except Exception as e:
                # Log error or skip invalid playbook
                pass

    def list_playbooks(self) -> list[str]:
        """List all registered playbook names."""
        return list(self._definitions.keys())

    def get(self, name: str) -> Optional[PlaybookDefinition]:
        """Get a loaded playbook definition by name."""
        return self._definitions.get(name)

    def run(self, name: str, inputs: dict[str, Any] | None = None) -> PlaybookResult:
        """Execute a playbook step-by-step, evaluating conditions, rules, and collecting findings."""
        playbook = self.get(name)
        if not playbook:
            return PlaybookResult(
                playbook_name=name,
                ok=False,
                summary=f"Playbook '{name}' tidak ditemukan di sistem.",
            )

        inputs = inputs or {}

        # 1. Initialize context with inputs and defaults
        context: dict[str, Any] = {}
        for input_name, input_spec in playbook.inputs.items():
            default_val = None
            if isinstance(input_spec, dict):
                default_val = input_spec.get("default")
            context[input_name] = default_val

        # Overwrite with user inputs
        for k, v in inputs.items():
            if k in playbook.inputs:
                spec = playbook.inputs[k]
                if isinstance(spec, dict) and spec.get("type") == "int" and v is not None:
                    try:
                        context[k] = int(v)
                    except (ValueError, TypeError):
                        context[k] = v
                else:
                    context[k] = v

        step_results: dict[str, PlaybookStepResult] = {}
        aggregate_data: dict[str, Any] = {}
        summary_sections: list[str] = [
            f"=== Playbook Diagnosa: {playbook.name} ===",
        ]
        if playbook.description:
            summary_sections.append(f"Tujuan: {playbook.description}")

        # 2. Execute steps sequentially
        for step in playbook.steps:
            # Check conditional execution 'when'
            if step.when:
                should_run = safe_eval(step.when, context)
                if not should_run:
                    step_results[step.id] = PlaybookStepResult(
                        step_id=step.id,
                        tool_name=step.tool,
                        ok=True,
                        skipped=True,
                        skip_reason=f"Kondisi 'when: {step.when}' tidak terpenuhi",
                    )
                    continue

            # Resolve templated arguments
            resolved_args = {}
            for arg_k, arg_v in step.args.items():
                resolved_args[arg_k] = resolve_template_value(arg_v, context)

            # Execute tool through orchestrator
            tool_res = self.orchestrator.run_tool(step.tool, resolved_args)

            if not tool_res.ok:
                if step.optional:
                    step_results[step.id] = PlaybookStepResult(
                        step_id=step.id,
                        tool_name=step.tool,
                        ok=False,
                        error=tool_res.error,
                        skipped=True,
                        skip_reason=f"Optional step gagal: {tool_res.error}",
                    )
                    context[step.id] = {
                        "ok": False,
                        "data": {},
                        "summary": tool_res.error or "",
                    }
                    continue
                else:
                    step_results[step.id] = PlaybookStepResult(
                        step_id=step.id,
                        tool_name=step.tool,
                        ok=False,
                        error=tool_res.error,
                        summary=tool_res.summary or "",
                    )
                    summary_sections.append(f"[Step {step.id} GAGAL]: {tool_res.error}")
                    return PlaybookResult(
                        playbook_name=name,
                        ok=False,
                        steps=step_results,
                        summary="\n\n".join(summary_sections),
                        data=aggregate_data,
                    )

            # Tool succeeded
            step_results[step.id] = PlaybookStepResult(
                step_id=step.id,
                tool_name=step.tool,
                ok=True,
                data=tool_res.data,
                summary=tool_res.summary,
            )
            context[step.id] = {
                "ok": True,
                "data": tool_res.data,
                "summary": tool_res.summary,
            }
            aggregate_data[step.id] = tool_res.data
            if tool_res.summary:
                summary_sections.append(f"[{step.id}]\n{tool_res.summary}")

        # 3. Evaluate heuristic rules
        rule_findings: list[str] = []
        for rule in playbook.rules:
            matched = safe_eval(rule.condition, context)
            if matched:
                rule_findings.append(rule.finding)

        if rule_findings:
            summary_sections.append("Hasil Evaluasi Aturan (Findings):")
            for f in rule_findings:
                summary_sections.append(f"- {f}")

        # 4. Optional Web Research Step (Section 11 & 12)
        if playbook.optional_web_research:
            template = playbook.optional_web_research.get("query_template")
            if template:
                resolved_query = resolve_template_value(template, context)
                # Only run if resolved query has meaningful terms (not unreplaced braces)
                if resolved_query and "{" not in resolved_query and resolved_query.strip():
                    try:
                        from assistant.tools.web.researcher import web_researcher
                        res_data = web_researcher.research(resolved_query.strip(), max_sources=2)
                        if res_data.get("ok") and res_data.get("summary"):
                            summary_sections.append(f"Riset Web Terkait ({resolved_query.strip()}):\n{res_data['summary']}")
                            aggregate_data["web_research"] = res_data
                    except Exception:
                        pass

        return PlaybookResult(
            playbook_name=name,
            ok=True,
            steps=step_results,
            rule_findings=rule_findings,
            summary="\n\n".join(summary_sections),
            data=aggregate_data,
        )


# Global default playbook engine instance
playbook_engine = PlaybookEngine()
