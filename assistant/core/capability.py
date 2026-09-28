"""System Capability & Readiness Checker (Packaging & Deployment Prototype).

Assesses host hardware, OS environment, and subsystem readiness for Jarvis deployment:
- Windows build and architecture
- CPU / RAM / Disk headroom
- Audio / Microphone devices (native winmm)
- GPU telemetry
- STT model availability (faster-whisper)
- Browser automation runtime (Playwright Chromium)
- Local LLM service (Ollama)

States:
- READY: Fully operational and available.
- OPTIONAL: Optional subsystem not configured; core functions normally.
- DEGRADED: Subsystem available but operating with performance or model constraints.
- MISSING: Required component absent for a specific feature.
- UNSUPPORTED: Host environment does not satisfy minimum requirements.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
import ctypes
from typing import Any, Dict


class CapabilityStatus:
    READY = "READY"
    OPTIONAL = "OPTIONAL"
    DEGRADED = "DEGRADED"
    MISSING = "MISSING"
    UNSUPPORTED = "UNSUPPORTED"


class CapabilityChecker:
    """Evaluates host system capabilities against Jarvis runtime requirements."""

    MIN_RAM_GB = 4.0
    REC_RAM_GB = 8.0
    MIN_DISK_FREE_GB = 3.0

    @classmethod
    def check_os(cls) -> Dict[str, Any]:
        """Check Windows OS version, build, and architecture."""
        system = platform.system()
        machine = platform.machine()
        release = platform.release()
        version = platform.version()

        if system != "Windows":
            return {
                "name": "Operating System",
                "status": CapabilityStatus.UNSUPPORTED,
                "details": f"Non-Windows OS detected: {system} ({machine}). Jarvis requires Windows 10/11 x64.",
                "value": f"{system} {machine}",
            }

        if machine not in ("AMD64", "x86_64"):
            return {
                "name": "Operating System",
                "status": CapabilityStatus.UNSUPPORTED,
                "details": f"Architecture {machine} unsupported. Native Win32/UIA and CTranslate2 require x86_64.",
                "value": f"{system} {release} ({machine})",
            }

        # Check build number for WinRT OCR and modern UIA features (>= 19041 recommended)
        build_num = 0
        try:
            parts = version.split(".")
            if len(parts) >= 3:
                build_num = int(parts[2])
        except Exception:
            pass

        if build_num > 0 and build_num < 17763:
            return {
                "name": "Operating System",
                "status": CapabilityStatus.DEGRADED,
                "details": f"Windows build {build_num} is older than 1809. WinRT OCR and modern UIA may fail.",
                "value": f"Windows {release} (Build {build_num})",
            }

        return {
            "name": "Operating System",
            "status": CapabilityStatus.READY,
            "details": f"Windows {release} x64 (Build {build_num}) fully compatible with native Win32/UIA/WinRT.",
            "value": f"Windows {release} (Build {build_num})",
        }

    @classmethod
    def check_resources(cls) -> Dict[str, Any]:
        """Check CPU, RAM, and Disk space."""
        try:
            import psutil

            # CPU
            cpu_count = psutil.cpu_count(logical=True)
            physical_cores = psutil.cpu_count(logical=False) or cpu_count

            # RAM
            mem = psutil.virtual_memory()
            total_ram_gb = round(mem.total / (1024**3), 1)
            avail_ram_gb = round(mem.available / (1024**3), 1)

            # Disk
            disk = psutil.disk_usage(os.path.abspath("."))
            free_disk_gb = round(disk.free / (1024**3), 1)

            details_parts = [
                f"CPU: {physical_cores}C/{cpu_count}T",
                f"RAM: {avail_ram_gb} GB avail / {total_ram_gb} GB total",
                f"Disk: {free_disk_gb} GB free",
            ]

            if total_ram_gb < cls.MIN_RAM_GB:
                status = CapabilityStatus.UNSUPPORTED
                details = f"RAM insufficient (< {cls.MIN_RAM_GB} GB). " + " ".join(details_parts)
            elif total_ram_gb < cls.REC_RAM_GB:
                status = CapabilityStatus.DEGRADED
                details = f"RAM constrained ({total_ram_gb} GB < {cls.REC_RAM_GB} GB). Fast-path works; local LLM will cause memory pressure."
            elif free_disk_gb < cls.MIN_DISK_FREE_GB:
                status = CapabilityStatus.DEGRADED
                details = f"Low disk space (< {cls.MIN_DISK_FREE_GB} GB free). " + " ".join(details_parts)
            else:
                status = CapabilityStatus.READY
                details = " ".join(details_parts)

            return {
                "name": "System Resources",
                "status": status,
                "details": details,
                "value": f"{total_ram_gb}GB RAM, {free_disk_gb}GB Free Disk",
            }
        except Exception as e:
            return {
                "name": "System Resources",
                "status": CapabilityStatus.DEGRADED,
                "details": f"Failed to probe system resources: {e}",
                "value": "Unknown",
            }

    @classmethod
    def check_audio(cls) -> Dict[str, Any]:
        """Check recording endpoint availability via native winmm."""
        if platform.system() != "Windows":
            return {
                "name": "Microphone / Audio",
                "status": CapabilityStatus.OPTIONAL,
                "details": "Non-Windows OS; native winmm unavailable.",
                "value": "0 Devices",
            }

        try:
            winmm = ctypes.windll.winmm
            num_devs = winmm.waveInGetNumDevs()
            if num_devs > 0:
                return {
                    "name": "Microphone / Audio",
                    "status": CapabilityStatus.READY,
                    "details": f"{num_devs} audio input device(s) detected via Win32 waveIn API.",
                    "value": f"{num_devs} Device(s)",
                }
            else:
                return {
                    "name": "Microphone / Audio",
                    "status": CapabilityStatus.OPTIONAL,
                    "details": "No microphone input devices detected. Voice input disabled; CLI & chat UI remain fully functional.",
                    "value": "0 Devices",
                }
        except Exception as e:
            return {
                "name": "Microphone / Audio",
                "status": CapabilityStatus.OPTIONAL,
                "details": f"winmm check failed: {e}. Voice input optional.",
                "value": "Error",
            }

    @classmethod
    def check_gpu(cls) -> Dict[str, Any]:
        """Probe GPU devices."""
        try:
            from assistant.tools.system.gpu import get_gpu_info
            res = get_gpu_info()
            if res.ok and res.data:
                gpus = res.data.get("gpus", [])
                if gpus:
                    gpu_names = [g.get("name", "Unknown GPU") for g in gpus]
                    return {
                        "name": "GPU Acceleration",
                        "status": CapabilityStatus.READY,
                        "details": f"GPU(s) detected: {', '.join(gpu_names)}",
                        "value": ", ".join(gpu_names),
                    }
        except Exception:
            pass

        return {
            "name": "GPU Acceleration",
            "status": CapabilityStatus.OPTIONAL,
            "details": "Integrated or software GPU. Inference configured for CPU.",
            "value": "CPU Mode",
        }

    @classmethod
    def check_stt(cls) -> Dict[str, Any]:
        """Check faster-whisper library and model availability."""
        try:
            import faster_whisper
            from assistant.voice.stt import FasterWhisperSTTProvider
            provider = FasterWhisperSTTProvider(model_name="tiny")
            is_ready = provider.is_available()
            if is_ready:
                return {
                    "name": "Local STT (faster-whisper)",
                    "status": CapabilityStatus.READY,
                    "details": "faster-whisper engine and 'tiny' model weights are installed and ready for offline CPU transcription.",
                    "value": "Ready (tiny INT8)",
                }
            else:
                return {
                    "name": "Local STT (faster-whisper)",
                    "status": CapabilityStatus.DEGRADED,
                    "details": "faster-whisper library installed but model weights not pre-cached. Requires initial one-time download.",
                    "value": "Model Pending",
                }
        except ImportError:
            return {
                "name": "Local STT (faster-whisper)",
                "status": CapabilityStatus.OPTIONAL,
                "details": "faster-whisper not installed. Voice push-to-talk disabled; all other 65 tools functional.",
                "value": "Not Installed",
            }
        except Exception as e:
            return {
                "name": "Local STT (faster-whisper)",
                "status": CapabilityStatus.OPTIONAL,
                "details": f"STT probe failed: {e}",
                "value": "Error",
            }

    @classmethod
    def check_browser(cls) -> Dict[str, Any]:
        """Check Playwright and Chromium browser availability."""
        try:
            import playwright
            # Check if Chromium binary exists in LocalAppData\ms-playwright
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            pw_cache = os.path.join(local_app_data, "ms-playwright")
            chromium_found = False
            if os.path.isdir(pw_cache):
                for item in os.listdir(pw_cache):
                    if "chromium" in item.lower():
                        chromium_found = True
                        break

            if chromium_found:
                return {
                    "name": "Browser Automation (Playwright)",
                    "status": CapabilityStatus.READY,
                    "details": "Playwright library and Chromium headless runtime present for isolated browser automation.",
                    "value": "Ready (Chromium)",
                }
            else:
                return {
                    "name": "Browser Automation (Playwright)",
                    "status": CapabilityStatus.OPTIONAL,
                    "details": "Playwright installed but Chromium binary not found in ms-playwright. Run 'playwright install chromium' to enable.",
                    "value": "Chromium Missing",
                }
        except ImportError:
            return {
                "name": "Browser Automation (Playwright)",
                "status": CapabilityStatus.OPTIONAL,
                "details": "Playwright not installed. Browser tools disabled; other tools functional.",
                "value": "Not Installed",
            }

    @classmethod
    def check_llm(cls) -> Dict[str, Any]:
        """Check Ollama service and Qwen 2.5 3B model availability."""
        import urllib.request
        import json

        ollama_url = "http://127.0.0.1:11434/api/tags"
        try:
            req = urllib.request.Request(ollama_url, headers={"User-Agent": "Jarvis-CapabilityCheck"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = [m.get("name", "") for m in data.get("models", [])]
                    qwen_present = any("qwen2.5:3b" in m.lower() or "qwen" in m.lower() for m in models)
                    if qwen_present:
                        return {
                            "name": "Local LLM Server (Ollama)",
                            "status": CapabilityStatus.READY,
                            "details": f"Ollama service active on localhost:11434 with recommended model available ({', '.join(models)}).",
                            "value": "Ready (Ollama)",
                        }
                    else:
                        return {
                            "name": "Local LLM Server (Ollama)",
                            "status": CapabilityStatus.DEGRADED,
                            "details": f"Ollama active but 'qwen2.5:3b-instruct' not pulled. Found: {models or 'none'}. Run 'ollama pull qwen2.5:3b-instruct'.",
                            "value": "Model Missing",
                        }
        except Exception:
            pass

        return {
            "name": "Local LLM Server (Ollama)",
            "status": CapabilityStatus.OPTIONAL,
            "details": "Ollama service not running at localhost:11434. Fast-path intent router (<1s) and deterministic diagnostic playbooks operate normally without LLM.",
            "value": "Offline / Not Running",
        }

    @classmethod
    def evaluate_all(cls) -> Dict[str, Any]:
        """Evaluate all system capabilities and return comprehensive report."""
        checks = [
            cls.check_os(),
            cls.check_resources(),
            cls.check_audio(),
            cls.check_gpu(),
            cls.check_stt(),
            cls.check_browser(),
            cls.check_llm(),
        ]

        overall = CapabilityStatus.READY
        for c in checks:
            st = c["status"]
            if st == CapabilityStatus.UNSUPPORTED:
                overall = CapabilityStatus.UNSUPPORTED
                break
            elif st == CapabilityStatus.DEGRADED and overall != CapabilityStatus.UNSUPPORTED:
                overall = CapabilityStatus.DEGRADED

        return {
            "overall_status": overall,
            "checks": checks,
        }

    @classmethod
    def format_cli_report(cls) -> str:
        """Format capabilities as human-readable CLI table."""
        eval_result = cls.evaluate_all()
        overall = eval_result["overall_status"]

        lines = [
            "=" * 72,
            f" JARVIS SYSTEM CAPABILITY & READINESS REPORT: [{overall}]",
            "=" * 72,
        ]

        for c in eval_result["checks"]:
            st = c["status"]
            name = c["name"]
            val = c["value"]
            details = c["details"]
            badge = f"[{st}]"
            lines.append(f"{badge:<14} {name:<32} {val}")
            lines.append(f"               Details: {details}")
            lines.append("-" * 72)

        return "\n".join(lines)
