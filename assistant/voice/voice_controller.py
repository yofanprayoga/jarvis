"""Voice Input Controller & Orchestrator Integration (Phase 11).

Implements the user-controlled voice input layer:
Microphone -> local STT -> existing Intent/Orchestrator -> existing tools

Strict Principles:
1. User-controlled & explicit push-to-talk / start-stop.
2. Zero background surveillance or continuous wake-word listening.
3. 100% offline local processing (winmm.dll + faster-whisper CPU).
4. Audio discarded immediately after transcription (no disk recording retained).
5. Comprehensive error recovery (mic unavailable, empty audio, cancelled, STT missing).
6. Identical PolicyEngine, L0-L3 enforcement, and audit trail as typed input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import enum
import threading
import time
from typing import Any, Callable, Optional

from assistant.core.orchestrator import Orchestrator, orchestrator as default_orchestrator
from assistant.voice.audio_capture import (
    AudioCaptureError,
    AudioRecorder,
    EmptyAudioError,
    MicrophoneUnavailableError,
    RecordingCancelledError,
    is_microphone_available,
    pcm_to_wav,
)
from assistant.voice.stt import (
    BaseSTTProvider,
    STTError,
    STTResult,
    STTUnavailableError,
    SpeechToTextEngine,
    stt_engine as default_stt_engine,
)


class VoiceState(enum.Enum):
    IDLE = "IDLE"
    RECORDING = "RECORDING"
    TRANSCRIBING = "TRANSCRIBING"
    DISPATCHING = "DISPATCHING"


@dataclass
class VoiceSessionResult:
    """Complete result of a voice interaction session."""
    ok: bool
    status: str
    transcript: str = ""
    language: str = "id"
    stt_duration_ms: float = 0.0
    audio_duration_s: float = 0.0
    error: Optional[str] = None
    orchestrator_result: Optional[dict[str, Any]] = None


class VoiceController:
    """Coordinates explicit microphone recording, local STT, and Orchestrator dispatch."""

    DEFAULT_MAX_DURATION_S = 15.0
    DEFAULT_MIN_DURATION_S = 0.3
    DEFAULT_SILENCE_RMS = 40.0
    DEFAULT_LANGUAGE = "id"

    def __init__(
        self,
        recorder: Optional[AudioRecorder] = None,
        stt: Optional[SpeechToTextEngine] = None,
        orch: Optional[Orchestrator] = None,
        default_language: str = DEFAULT_LANGUAGE,
        max_duration_s: float = DEFAULT_MAX_DURATION_S,
        on_status_change: Optional[Callable[[VoiceState, str], None]] = None,
        on_transcript: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.recorder = recorder or AudioRecorder()
        self.stt = stt or default_stt_engine
        self.orch = orch or default_orchestrator
        self.default_language = default_language
        self.max_duration_s = max_duration_s

        self.on_status_change = on_status_change
        self.on_transcript = on_transcript

        self._state = VoiceState.IDLE
        self._recording_start_time: float = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> VoiceState:
        return self._state

    def _set_state(self, new_state: VoiceState, message: str = "") -> None:
        self._state = new_state
        if self.on_status_change:
            try:
                self.on_status_change(new_state, message)
            except Exception:
                pass

    def is_mic_available(self) -> bool:
        """Return True if at least one audio recording device is available."""
        return is_microphone_available()

    def start_push_to_talk(self, device_id: int = 0) -> None:
        """Begin user-triggered voice recording session."""
        with self._lock:
            if self._state == VoiceState.RECORDING:
                return

            if not self.is_mic_available():
                self._set_state(VoiceState.IDLE, "Microphone tidak tersedia.")
                raise MicrophoneUnavailableError("Microphone tidak terdeteksi atau sedang dinonaktifkan.")

            self._recording_start_time = time.perf_counter()
            self.recorder.device_id = device_id
            self.recorder.start_recording()
            self._set_state(VoiceState.RECORDING, "Merekam suara... silakan bicara")

    def stop_and_transcribe(self, language: Optional[str] = None) -> tuple[bool, str, STTResult | None]:
        """Stop recording, transcribe audio, and return transcript without dispatching.

        Returns:
            (ok, message_or_error, stt_result)
        """
        with self._lock:
            if self._state != VoiceState.RECORDING and not self.recorder.is_recording:
                return False, "Perekaman suara belum dimulai.", None

            self._set_state(VoiceState.TRANSCRIBING, "Memproses transkripsi suara lokal...")

        try:
            pcm_bytes = self.recorder.stop_recording(
                min_duration_s=self.DEFAULT_MIN_DURATION_S,
                silence_rms_threshold=self.DEFAULT_SILENCE_RMS,
            )
            wav_bytes = pcm_to_wav(pcm_bytes, sample_rate=self.recorder.sample_rate)

            target_lang = language or self.default_language
            stt_res = self.stt.transcribe(wav_bytes, language=target_lang)

            if stt_res.is_empty or not stt_res.text.strip():
                self._set_state(VoiceState.IDLE, "Suara tidak terdengar atau terlalu singkat.")
                return False, "Suara tidak terdengar jelas atau terlalu hening.", stt_res

            transcript = stt_res.text.strip()
            if self.on_transcript:
                try:
                    self.on_transcript(transcript)
                except Exception:
                    pass

            self._set_state(VoiceState.IDLE, f"Transkripsi selesai: {transcript}")
            return True, transcript, stt_res

        except RecordingCancelledError:
            self._set_state(VoiceState.IDLE, "Perekaman dibatalkan.")
            return False, "Perekaman suara dibatalkan oleh pengguna.", None
        except EmptyAudioError as e:
            self._set_state(VoiceState.IDLE, str(e))
            return False, f"Tidak ada suara yang terdeteksi: {e}", None
        except STTUnavailableError as e:
            self._set_state(VoiceState.IDLE, "Model STT tidak tersedia.")
            return False, f"Layanan STT lokal tidak tersedia: {e}", None
        except Exception as e:
            self._set_state(VoiceState.IDLE, f"Kesalahan voice: {e}")
            return False, f"Kesalahan saat menangkap suara: {e}", None

    def cancel(self) -> None:
        """Cancel active recording session immediately."""
        with self._lock:
            self.recorder.cancel_recording()
            self._set_state(VoiceState.IDLE, "Perekaman dibatalkan.")

    def listen_and_execute(
        self,
        duration_s: Optional[float] = None,
        language: Optional[str] = None,
        dry_run: bool = False,
        device_id: int = 0,
    ) -> VoiceSessionResult:
        """Complete single-turn voice interaction:

        1. Capture speech (fixed duration or push-to-talk interval)
        2. Transcribe using local STT
        3. If not dry_run, dispatch to Orchestrator (Intent Router / Planner)
        4. Return structured VoiceSessionResult
        """
        listen_duration = duration_s or 4.0
        if listen_duration > self.max_duration_s:
            listen_duration = self.max_duration_s

        # 1. Check microphone availability
        if not self.is_mic_available():
            return VoiceSessionResult(
                ok=False,
                status="MIC_UNAVAILABLE",
                error="Microphone tidak terdeteksi atau tidak tersedia pada sistem.",
            )

        # 2. Record
        try:
            self.start_push_to_talk(device_id=device_id)
            time.sleep(listen_duration)
        except Exception as e:
            self.cancel()
            return VoiceSessionResult(
                ok=False,
                status="CAPTURE_FAILED",
                error=f"Gagal merekam suara: {e}",
            )

        # 3. Transcribe
        ok, transcript_or_err, stt_res = self.stop_and_transcribe(language=language)
        if not ok or not stt_res:
            return VoiceSessionResult(
                ok=False,
                status="TRANSCRIBE_FAILED",
                error=transcript_or_err,
                transcript="",
                language=language or self.default_language,
            )

        transcript = transcript_or_err
        target_lang = stt_res.language or language or self.default_language

        # 4. If dry-run, stop after transcription
        if dry_run:
            return VoiceSessionResult(
                ok=True,
                status="DRY_RUN_COMPLETE",
                transcript=transcript,
                language=target_lang,
                stt_duration_ms=stt_res.duration_ms,
                audio_duration_s=listen_duration,
            )

        # 5. Dispatch to existing Orchestrator
        self._set_state(VoiceState.DISPATCHING, f"Menjalankan perintah: '{transcript}'")
        try:
            orch_res = self.orch.handle_request(transcript)
            self._set_state(VoiceState.IDLE, "Perintah suara selesai dieksekusi.")
            return VoiceSessionResult(
                ok=True,
                status="EXECUTED",
                transcript=transcript,
                language=target_lang,
                stt_duration_ms=stt_res.duration_ms,
                audio_duration_s=listen_duration,
                orchestrator_result=orch_res,
            )
        except Exception as e:
            self._set_state(VoiceState.IDLE, f"Gagal mengeksekusi perintah: {e}")
            return VoiceSessionResult(
                ok=False,
                status="DISPATCH_FAILED",
                transcript=transcript,
                language=target_lang,
                stt_duration_ms=stt_res.duration_ms,
                audio_duration_s=listen_duration,
                error=f"Gagal mengeksekusi perintah suara di Orchestrator: {e}",
            )


# Global default VoiceController instance
voice_controller = VoiceController()
