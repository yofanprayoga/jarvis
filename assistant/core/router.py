"""Fast-Path Intent Router (Section 9)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
import yaml
from assistant.core.orchestrator import orchestrator, Orchestrator
from assistant.tools.base import ToolResult
from assistant.tools.launch.app_launcher import app_indexer, AppIndexer
from assistant.tools.launch.site_manager import site_manager, SiteManager


@dataclass
class RouteResult:
    matched: bool
    route: str  # "fast" or "llm"
    intent: Optional[str] = None
    tool_name: Optional[str] = None
    args: Optional[dict[str, Any]] = None
    tool_result: Optional[ToolResult] = None
    message: Optional[str] = None


class IntentRouter:
    """Matches user natural language input against fast-path patterns in intents.yaml."""

    # Filler words stripped during normalization
    FILLER_WORDS = {
        "tolong", "dong", "coba", "bantu", "pls", "please",
        "lah", "deh", "sih", "ya", "nih", "kan", "kek",
    }

    def __init__(
        self,
        intents_file: str = "config/intents.yaml",
        sites: SiteManager | None = None,
        apps: AppIndexer | None = None,
        orch: Orchestrator | None = None,
    ) -> None:
        self.intents_file = Path(intents_file)
        self.sites = sites or site_manager
        self.apps = apps or app_indexer
        self.orch = orch or orchestrator
        self.rules: list[dict[str, Any]] = []
        self._load_rules()

    def _load_rules(self) -> None:
        if not self.intents_file.is_file():
            return
        try:
            with open(self.intents_file, "r", encoding="utf-8") as f:
                raw_rules = yaml.safe_load(f) or []
            self.rules = raw_rules
        except Exception:
            self.rules = []

    def normalize(self, text: str) -> str:
        """Lowercase, trim trailing sentence punctuation, and strip common filler words."""
        cleaned = text.strip()
        # Remove trailing sentence punctuation (? ! .)
        cleaned = re.sub(r"[?!.]+$", "", cleaned).strip()
        # Remove commas and question/exclamation marks
        cleaned = re.sub(r"[,?!]", " ", cleaned)
        tokens = cleaned.split()
        filtered = [t for t in tokens if t.lower() not in self.FILLER_WORDS]
        return " ".join(filtered)

    def _compile_pattern(self, pattern: str) -> re.Pattern:
        """Convert a pattern like 'cari {query} di youtube' to a regex with named capture groups."""
        # Replace slots with unique placeholders before escaping
        slot_types = {
            "{url}": r"(?P<url>\S+)",
            "{site}": r"(?P<site>\S+)",
            "{folder}": r"(?P<folder>.+?)",
            "{app}": r"(?P<app>.+?)",
            "{query}": r"(?P<query>.+)",
            "{title}": r"(?P<title>.+)",
        }
        
        # Build regex
        tokens = pattern.split()
        regex_parts = []
        for t in tokens:
            if t in slot_types:
                regex_parts.append(slot_types[t])
            else:
                regex_parts.append(re.escape(t))
        
        regex_str = r"\s+".join(regex_parts)
        return re.compile(f"^{regex_str}$", re.IGNORECASE)

    def route(self, raw_input: str) -> RouteResult:
        """Evaluate input against fast-path intent patterns."""
        normalized = self.normalize(raw_input)
        if not normalized:
            return RouteResult(
                matched=False,
                route="none",
                message="Input kosong.",
            )

        for rule in self.rules:
            intent_name = rule.get("intent", "unknown")
            patterns = rule.get("patterns", [])
            tool_name = rule.get("tool")
            args_template = rule.get("args", {})
            resolve_specs = rule.get("resolve", {})

            for pat in patterns:
                regex = self._compile_pattern(pat)
                match = regex.match(normalized)
                if not match:
                    continue

                slots = match.groupdict()
                slots = {k: v.strip() for k, v in slots.items()}

                # Check if slots resolve against required registries
                resolve_ok = True
                resolved_slots = dict(slots)

                for slot_name, resolver_type in resolve_specs.items():
                    val = slots.get(slot_name)
                    if not val:
                        resolve_ok = False
                        break

                    if resolver_type == "sites":
                        resolved_url = self.sites.resolve(val)
                        if not resolved_url:
                            resolve_ok = False
                            break
                        resolved_slots[slot_name] = resolved_url

                    elif resolver_type == "apps":
                        resolved_app = self.apps.resolve(val)
                        if not resolved_app:
                            resolve_ok = False
                            break
                        resolved_slots[slot_name] = resolved_app

                if not resolve_ok:
                    continue  # pattern matched syntax but slots failed resolution

                # Substitute slots into args
                call_args = {}
                for arg_k, arg_v in args_template.items():
                    if isinstance(arg_v, str):
                        rendered = arg_v
                        for s_k, s_v in resolved_slots.items():
                            rendered = rendered.replace(f"{{{s_k}}}", str(s_v))
                        call_args[arg_k] = rendered
                    else:
                        call_args[arg_k] = arg_v

                # Execute directly via orchestrator
                tool_res = self.orch.run_tool(tool_name, call_args)
                return RouteResult(
                    matched=True,
                    route="fast",
                    intent=intent_name,
                    tool_name=tool_name,
                    args=call_args,
                    tool_result=tool_res,
                    message=tool_res.summary,
                )

        # Unmatched in fast path -> Fallback
        return RouteResult(
            matched=False,
            route="llm",
            message="Perintah tidak dikenali di jalur cepat (Fast Path). LLM planner belum terhubung.",
        )


# Global default intent router instance
intent_router = IntentRouter()
