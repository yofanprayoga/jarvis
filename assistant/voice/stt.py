"""Local Speech-to-Text (STT) Engine & Providers (Phase 11).

Provides local, CPU-friendly speech recognition:
- FasterWhisperSTTProvider: CTranslate2 INT8 quantized Whisper ('tiny' by default).
- MockSTTProvider: Deterministic provider for automated testing and offline development.
- SpeechToTextEngine: Unified interface with language selection and lazy initialization.
- Strict isolation: 100% offline, zero cloud tokens, zero API keys.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import io
import os
from pathlib import Path
import time
from typing import Any, Optional

# Suppress HuggingFace symlink warning on Windows Developer Mode
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


# ──────────────────────────────────────────────────────────────────────────────
# Data Models & Exceptions
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class STTResult:
    """Outcome of a speech-to-text transcription."""
    text: str
    language: str
    confidence: float
    duration_ms: float
    is_empty: bool = False
    raw_segments: list[dict[str, Any]] = None

    def __post_init__(self):
        if self.raw_segments is None:
            self.raw_segments = []


class STTError(Exception):
    """Base exception for Speech-to-Text errors."""
    pass


class STTUnavailableError(STTError):
    """Raised when the STT library or model is missing or cannot be loaded."""
    pass


# ──────────────────────────────────────────────────────────────────────────────
# Base Provider Interface
# ──────────────────────────────────────────────────────────────────────────────

class BaseSTTProvider(ABC):
    """Abstract interface for local speech-to-text providers."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this provider is ready to transcribe."""
        pass

    @abstractmethod
    def transcribe(self, wav_bytes: bytes, language: Optional[str] = "id") -> STTResult:
        """Transcribe audio WAV bytes into text."""
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Faster-Whisper Provider (CTranslate2 INT8 CPU)
# ──────────────────────────────────────────────────────────────────────────────

class FasterWhisperSTTProvider(BaseSTTProvider):
    """Local offline STT provider using faster-whisper with INT8 quantization."""

    DEFAULT_MODEL = "tiny"
    DEFAULT_CACHE_DIR = "data/models/stt"

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        download_root: str = DEFAULT_CACHE_DIR,
        device: str = "cpu",
        compute_type: str = "int8",
        cpu_threads: int = 4,
    ) -> None:
        self.model_name = model_name
        self.download_root = download_root
        self.device = device
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads
        self._model = None
        self._load_error: Optional[str] = None

    def _ensure_model(self) -> Any:
        """Lazy-load WhisperModel on first transcription."""
        if self._model is not None:
            return self._model

        if self._load_error is not None:
            raise STTUnavailableError(f"STT Model gagal dimuat: {self._load_error}")

        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            self._load_error = f"faster-whisper tidak terinstal: {e}"
            raise STTUnavailableError(self._load_error) from e

        cache_path = Path(self.download_root)
        cache_path.mkdir(parents=True, exist_ok=True)

        try:
            self._model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
                cpu_threads=self.cpu_threads,
                download_root=str(cache_path),
            )
            return self._model
        except Exception as e:
            self._load_error = f"Gagal memuat model Whisper ('{self.model_name}'): {e}"
            raise STTUnavailableError(self._load_error) from e

    def is_available(self) -> bool:
        """Check if faster-whisper library is importable and model can be loaded."""
        try:
            import faster_whisper  # noqa: F401
            return True
        except ImportError:
            return False

    def transcribe(self, wav_bytes: bytes, language: Optional[str] = "id") -> STTResult:
        """Transcribe in-memory WAV bytes using faster-whisper.

        Args:
            wav_bytes: Complete RIFF/WAV audio bytes (16kHz 16-bit mono recommended).
            language: Target language code ('id' for Indonesian, 'en' for English, or None for auto).
        """
        if not wav_bytes:
            return STTResult(text="", language=language or "unknown", confidence=0.0, duration_ms=0.0, is_empty=True)

        model = self._ensure_model()

        start_time = time.perf_counter()
        audio_stream = io.BytesIO(wav_bytes)

        try:
            segments, info = model.transcribe(
                audio_stream,
                language=language,
                beam_size=1,  # Greedy search for fastest CPU inference
                temperature=0.0,
                vad_filter=True,  # Voice activity detection filtering
            )

            seg_list = []
            text_parts = []
            for s in segments:
                text_parts.append(s.text.strip())
                seg_list.append({
                    "start": s.start,
                    "end": s.end,
                    "text": s.text.strip(),
                    "avg_logprob": s.avg_logprob,
                })

            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 1)
            full_text = " ".join(text_parts).strip()
            is_empty = len(full_text) == 0

            # Calculate confidence score from avg_logprob if available
            confidence = 1.0
            if seg_list and hasattr(info, "language_probability"):
                confidence = round(float(info.language_probability), 3)

            return STTResult(
                text=full_text,
                language=info.language or language or "unknown",
                confidence=confidence,
                duration_ms=duration_ms,
                is_empty=is_empty,
                raw_segments=seg_list,
            )
        except Exception as e:
            raise STTError(f"Kesalahan saat transkripsi suara: {e}") from e


# ──────────────────────────────────────────────────────────────────────────────
# Mock STT Provider (For Unit & Offline Testing)
# ──────────────────────────────────────────────────────────────────────────────

class MockSTTProvider(BaseSTTProvider):
    """Deterministic mock STT provider for tests and development."""

    def __init__(self, default_text: str = "buka notepad", default_lang: str = "id") -> None:
        self.default_text = default_text
        self.default_lang = default_lang
        self._preset_queue: list[STTResult] = []
        self._available = True

    def is_available(self) -> bool:
        return self._available

    def set_available(self, available: bool) -> None:
        self._available = available

    def queue_result(self, text: str, language: str = "id", confidence: float = 0.98, is_empty: bool = False) -> None:
        """Queue a specific transcription result for next call."""
        self._preset_queue.append(
            STTResult(
                text=text,
                language=language,
                confidence=confidence,
                duration_ms=5.0,
                is_empty=is_empty,
            )
        )

    def transcribe(self, wav_bytes: bytes, language: Optional[str] = "id") -> STTResult:
        if not self._available:
            raise STTUnavailableError("Mock STT provider is set to unavailable.")

        if not wav_bytes:
            return STTResult(text="", language=language or "id", confidence=0.0, duration_ms=0.5, is_empty=True)

        if self._preset_queue:
            return self._preset_queue.pop(0)

        return STTResult(
            text=self.default_text,
            language=language or self.default_lang,
            confidence=0.95,
            duration_ms=5.0,
            is_empty=len(self.default_text.strip()) == 0,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Unified SpeechToTextEngine
# ──────────────────────────────────────────────────────────────────────────────

class SpeechToTextEngine:
    """Unified coordinator for local speech recognition."""

    def __init__(self, provider: Optional[BaseSTTProvider] = None) -> None:
        if provider is not None:
            self._provider = provider
        else:
            self._provider = FasterWhisperSTTProvider()

    @property
    def provider(self) -> BaseSTTProvider:
        return self._provider

    def set_provider(self, provider: BaseSTTProvider) -> None:
        self._provider = provider

    def is_available(self) -> bool:
        return self._provider.is_available()

    def transcribe(self, wav_bytes: bytes, language: Optional[str] = "id") -> STTResult:
        """Transcribe WAV audio bytes to text."""
        return self._provider.transcribe(wav_bytes=wav_bytes, language=language)


# Global default STT engine instance
stt_engine = SpeechToTextEngine()
