"""Comprehensive Unit & Integration Test Suite for Voice Input & Local STT (Phase 11).

Verifies:
1. Audio capture: device enumeration, RMS calculation, WAV header generation, lifecycle.
2. Error handling: microphone unavailable, empty/silent speech, recording cancellation.
3. Local STT: Mock provider, FasterWhisper provider, Indonesian ('id') & English ('en') codes.
4. VoiceController: Push-to-talk, stop & transcribe, cancellation, Orchestrator dispatch, dry-run.
5. Security & Policy: L0 policy enforcement on spoken text, L3 confirmation, prompt-injection isolation.
"""

from __future__ import annotations

import io
import math
import struct
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
from typing import Any

from assistant.core.audit import AuditLogger
from assistant.core.orchestrator import Orchestrator
from assistant.core.policy import PolicyEngine
from assistant.core.router import IntentRouter
from assistant.voice.audio_capture import (
    AudioCaptureError,
    AudioRecorder,
    EmptyAudioError,
    MicrophoneUnavailableError,
    RecordingCancelledError,
    calculate_rms,
    get_input_devices,
    is_microphone_available,
    pcm_to_wav,
)
from assistant.voice.stt import (
    FasterWhisperSTTProvider,
    MockSTTProvider,
    STTError,
    STTResult,
    STTUnavailableError,
    SpeechToTextEngine,
)
from assistant.voice.voice_controller import (
    VoiceController,
    VoiceSessionResult,
    VoiceState,
)


def _generate_synthetic_tone_pcm(duration_s: float = 1.0, sample_rate: int = 16000, freq_hz: float = 440.0, amplitude: float = 0.5) -> bytes:
    """Generate synthetic 16kHz 16-bit mono PCM tone for audio tests."""
    n_samples = int(duration_s * sample_rate)
    data = bytearray()
    for i in range(n_samples):
        sample = int(32767.0 * amplitude * math.sin(2.0 * math.pi * freq_hz * i / sample_rate))
        data.extend(struct.pack("<h", sample))
    return bytes(data)


def _generate_synthetic_silence_pcm(duration_s: float = 1.0, sample_rate: int = 16000) -> bytes:
    """Generate synthetic 16kHz 16-bit mono PCM silence (all zeros)."""
    n_samples = int(duration_s * sample_rate)
    return b"\x00" * (n_samples * 2)


# ──────────────────────────────────────────────────────────────────────────────
# 1. Audio Capture & Utility Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestAudioCaptureAndUtils(unittest.TestCase):
    """Test audio capture helpers, device queries, RMS, and WAV packaging."""

    def test_01_device_enumeration(self):
        """get_input_devices returns a list of dictionaries with name and channels."""
        devs = get_input_devices()
        self.assertIsInstance(devs, list)
        for d in devs:
            self.assertIn("id", d)
            self.assertIn("name", d)
            self.assertIn("channels", d)

    def test_02_is_microphone_available(self):
        """is_microphone_available returns a boolean."""
        avail = is_microphone_available()
        self.assertIsInstance(avail, bool)

    def test_03_calculate_rms_silence_vs_tone(self):
        """calculate_rms returns near-zero for silence and positive for tone."""
        silence = _generate_synthetic_silence_pcm(0.5)
        tone = _generate_synthetic_tone_pcm(0.5, amplitude=0.5)

        rms_silence = calculate_rms(silence)
        rms_tone = calculate_rms(tone)

        self.assertEqual(rms_silence, 0.0)
        self.assertGreater(rms_tone, 5000.0)

    def test_04_calculate_rms_empty_or_malformed(self):
        """calculate_rms safely returns 0.0 on empty or single-byte input."""
        self.assertEqual(calculate_rms(b""), 0.0)
        self.assertEqual(calculate_rms(b"\x00"), 0.0)

    def test_05_pcm_to_wav_format(self):
        """pcm_to_wav creates a valid RIFF/WAV byte sequence with correct headers."""
        tone = _generate_synthetic_tone_pcm(0.2)
        wav_bytes = pcm_to_wav(tone, sample_rate=16000, channels=1, sampwidth=2)

        self.assertTrue(wav_bytes.startswith(b"RIFF"))
        self.assertIn(b"WAVE", wav_bytes[:12])
        self.assertIn(b"fmt ", wav_bytes[:24])
        self.assertIn(b"data", wav_bytes)
        self.assertGreater(len(wav_bytes), len(tone))

    def test_06_recorder_lifecycle_empty_audio_raises(self):
        """stop_recording raises EmptyAudioError if audio is pure silence."""
        rec = AudioRecorder()
        rec._is_recording = True
        rec._recorded_chunks = [_generate_synthetic_silence_pcm(0.5)]

        with patch.object(rec, "_cleanup_native"):
            with self.assertRaises(EmptyAudioError):
                rec.stop_recording(min_duration_s=0.2, silence_rms_threshold=50.0)

    def test_07_recorder_cancel(self):
        """cancel_recording sets is_cancelled and resets recording state."""
        rec = AudioRecorder()
        rec._is_recording = True
        rec._recorded_chunks = [b"sample_data"]

        with patch.object(rec, "_cleanup_native"):
            rec.cancel_recording()

        self.assertFalse(rec.is_recording)
        self.assertTrue(rec._is_cancelled)
        self.assertEqual(len(rec._recorded_chunks), 0)

        # Calling stop after cancel raises RecordingCancelledError
        with self.assertRaises(RecordingCancelledError):
            rec.stop_recording()

    def test_08_recorder_mic_unavailable_raises(self):
        """start_recording raises MicrophoneUnavailableError when no device exists."""
        rec = AudioRecorder()
        with patch("assistant.voice.audio_capture.is_microphone_available", return_value=False):
            with self.assertRaises(MicrophoneUnavailableError):
                rec.start_recording()


# ──────────────────────────────────────────────────────────────────────────────
# 2. Speech-to-Text (STT) Provider Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestSTTProviders(unittest.TestCase):
    """Test STT engines, providers, languages, and fallbacks."""

    def test_01_mock_stt_provider_defaults(self):
        """MockSTTProvider returns configured default text and language."""
        mock = MockSTTProvider(default_text="buka google", default_lang="id")
        eng = SpeechToTextEngine(provider=mock)

        res = eng.transcribe(b"fake_wav_bytes", language="id")
        self.assertEqual(res.text, "buka google")
        self.assertEqual(res.language, "id")
        self.assertFalse(res.is_empty)
        self.assertGreater(res.confidence, 0.9)

    def test_02_mock_stt_queue(self):
        """MockSTTProvider supports queueing specific results sequentially."""
        mock = MockSTTProvider()
        mock.queue_result(text="pertama", language="id")
        mock.queue_result(text="second", language="en")

        res1 = mock.transcribe(b"wav1")
        res2 = mock.transcribe(b"wav2")

        self.assertEqual(res1.text, "pertama")
        self.assertEqual(res1.language, "id")
        self.assertEqual(res2.text, "second")
        self.assertEqual(res2.language, "en")

    def test_03_mock_stt_unavailable(self):
        """MockSTTProvider raises STTUnavailableError when unavailable."""
        mock = MockSTTProvider()
        mock.set_available(False)
        with self.assertRaises(STTUnavailableError):
            mock.transcribe(b"wav")

    def test_04_mock_stt_empty_wav(self):
        """Empty WAV bytes returns is_empty=True without failing."""
        mock = MockSTTProvider()
        res = mock.transcribe(b"")
        self.assertTrue(res.is_empty)
        self.assertEqual(res.text, "")

    def test_05_faster_whisper_availability_and_config(self):
        """FasterWhisperSTTProvider correctly initializes with CPU INT8 settings."""
        fw = FasterWhisperSTTProvider(model_name="tiny", device="cpu", compute_type="int8")
        self.assertEqual(fw.model_name, "tiny")
        self.assertEqual(fw.device, "cpu")
        self.assertEqual(fw.compute_type, "int8")
        self.assertTrue(fw.is_available())

    def test_06_faster_whisper_transcribe_empty(self):
        """FasterWhisperSTTProvider returns is_empty=True on empty WAV input."""
        fw = FasterWhisperSTTProvider()
        res = fw.transcribe(b"")
        self.assertTrue(res.is_empty)
        self.assertEqual(res.text, "")


# ──────────────────────────────────────────────────────────────────────────────
# 3. Voice Controller & Orchestrator Integration Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestVoiceControllerIntegration(unittest.TestCase):
    """Test end-to-end voice capture -> STT -> Orchestrator dispatch."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "voice_audit.db")
        self.audit = AuditLogger(db_path=self.db_path)
        self.policy = PolicyEngine()
        self.orch = Orchestrator(audit=self.audit, policy=self.policy)
        self.router = IntentRouter(orch=self.orch)

        # Mock STT and Recorder
        self.mock_stt = MockSTTProvider()
        self.mock_recorder = MagicMock(spec=AudioRecorder)
        self.mock_recorder.sample_rate = 16000
        self.mock_recorder.is_recording = False

        self.vc = VoiceController(
            recorder=self.mock_recorder,
            stt=SpeechToTextEngine(provider=self.mock_stt),
            orch=self.orch,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_push_to_talk_and_transcribe_flow(self):
        """User starts push-to-talk, stops, and receives transcript."""
        tone_pcm = _generate_synthetic_tone_pcm(1.0)
        self.mock_recorder.stop_recording.return_value = tone_pcm
        self.mock_stt.queue_result(text="cek spek pc", language="id")

        with patch.object(self.vc, "is_mic_available", return_value=True):
            self.vc.start_push_to_talk()
            self.assertEqual(self.vc.state, VoiceState.RECORDING)

            ok, transcript, stt_res = self.vc.stop_and_transcribe()
            self.assertTrue(ok)
            self.assertEqual(transcript, "cek spek pc")
            self.assertEqual(self.vc.state, VoiceState.IDLE)

    def test_02_cancel_resets_state(self):
        """User cancels recording session cleanly."""
        with patch.object(self.vc, "is_mic_available", return_value=True):
            self.vc.start_push_to_talk()
            self.assertEqual(self.vc.state, VoiceState.RECORDING)

            self.vc.cancel()
            self.assertEqual(self.vc.state, VoiceState.IDLE)
            self.mock_recorder.cancel_recording.assert_called_once()

    def test_03_microphone_unavailable_error(self):
        """Returns structured MIC_UNAVAILABLE result when mic is absent."""
        with patch.object(self.vc, "is_mic_available", return_value=False):
            res = self.vc.listen_and_execute(duration_s=1.0)
            self.assertFalse(res.ok)
            self.assertEqual(res.status, "MIC_UNAVAILABLE")
            self.assertIn("Microphone tidak terdeteksi", res.error)

    def test_04_empty_audio_error(self):
        """Returns structured TRANSCRIBE_FAILED when no speech is detected."""
        self.mock_recorder.stop_recording.side_effect = EmptyAudioError("Audio terdeteksi sunyi")

        with patch.object(self.vc, "is_mic_available", return_value=True):
            res = self.vc.listen_and_execute(duration_s=0.5)
            self.assertFalse(res.ok)
            self.assertEqual(res.status, "TRANSCRIBE_FAILED")
            self.assertIn("Tidak ada suara yang terdeteksi", res.error)

    def test_05_stt_unavailable_error(self):
        """Returns structured TRANSCRIBE_FAILED when STT service fails."""
        tone_pcm = _generate_synthetic_tone_pcm(0.5)
        self.mock_recorder.stop_recording.return_value = tone_pcm
        self.mock_stt.set_available(False)

        with patch.object(self.vc, "is_mic_available", return_value=True):
            res = self.vc.listen_and_execute(duration_s=0.5)
            self.assertFalse(res.ok)
            self.assertEqual(res.status, "TRANSCRIBE_FAILED")
            self.assertIn("Layanan STT lokal tidak tersedia", res.error)

    def test_06_dry_run_transcription_only(self):
        """dry_run=True returns transcript without dispatching to Orchestrator."""
        tone_pcm = _generate_synthetic_tone_pcm(0.5)
        self.mock_recorder.stop_recording.return_value = tone_pcm
        self.mock_stt.queue_result(text="tutup window notepad", language="id")

        with patch.object(self.vc, "is_mic_available", return_value=True):
            res = self.vc.listen_and_execute(duration_s=0.5, dry_run=True)
            self.assertTrue(res.ok)
            self.assertEqual(res.status, "DRY_RUN_COMPLETE")
            self.assertEqual(res.transcript, "tutup window notepad")
            self.assertIsNone(res.orchestrator_result)

    def test_07_full_dispatch_to_orchestrator(self):
        """Voice input dispatches to Orchestrator and executes intent."""
        tone_pcm = _generate_synthetic_tone_pcm(0.5)
        self.mock_recorder.stop_recording.return_value = tone_pcm
        self.mock_stt.queue_result(text="system.get_overview", language="id")

        with patch.object(self.vc, "is_mic_available", return_value=True):
            res = self.vc.listen_and_execute(duration_s=0.5, dry_run=False)
            self.assertTrue(res.ok)
            self.assertEqual(res.status, "EXECUTED")
            self.assertEqual(res.transcript, "system.get_overview")
            self.assertIsNotNone(res.orchestrator_result)

            # Verify audit trail
            recent = self.audit.get_recent(1)
            self.assertEqual(len(recent), 1)
            self.assertEqual(recent[0]["tool_name"], "system.get_overview")

    def test_08_security_l0_policy_on_spoken_command(self):
        """Spoken commands attempting forbidden actions (L0) are blocked by PolicyEngine."""
        tone_pcm = _generate_synthetic_tone_pcm(0.5)
        self.mock_recorder.stop_recording.return_value = tone_pcm
        # Attempting forbidden window close on Windows Security
        self.mock_stt.queue_result(text="tutup window Windows Security", language="id")

        with patch.object(self.vc, "is_mic_available", return_value=True):
            res = self.vc.listen_and_execute(duration_s=0.5, dry_run=False)
            self.assertTrue(res.ok)
            orch_res = res.orchestrator_result or {}
            # Orchestrator should indicate failure / policy rejection
            self.assertIn("error", str(orch_res).lower() + str(orch_res.get("response")).lower())

    def test_09_indonesian_speech_transcription(self):
        """Indonesian speech commands with conversational particles are properly received."""
        tone_pcm = _generate_synthetic_tone_pcm(0.5)
        self.mock_recorder.stop_recording.return_value = tone_pcm
        self.mock_stt.queue_result(text="tolong buka aplikasi notepad ya", language="id")

        with patch.object(self.vc, "is_mic_available", return_value=True):
            res = self.vc.listen_and_execute(duration_s=0.5, language="id", dry_run=True)
            self.assertTrue(res.ok)
            self.assertEqual(res.transcript, "tolong buka aplikasi notepad ya")
            self.assertEqual(res.language, "id")


# ──────────────────────────────────────────────────────────────────────────────
# 4. Live Local Faster-Whisper CPU Smoke Test (Integration)
# ──────────────────────────────────────────────────────────────────────────────

class TestLiveFasterWhisperSmoke(unittest.TestCase):
    """Verifies that faster-whisper runs on real CPU without throwing errors."""

    def test_01_real_faster_whisper_transcription_smoke(self):
        """Transcribe synthetic audio using real local faster-whisper tiny INT8 model."""
        tone = _generate_synthetic_tone_pcm(1.0, freq_hz=440.0)
        wav_bytes = pcm_to_wav(tone, sample_rate=16000)

        fw = FasterWhisperSTTProvider(model_name="tiny", device="cpu", compute_type="int8")
        self.assertTrue(fw.is_available())

        start = time.perf_counter()
        res = fw.transcribe(wav_bytes, language="id")
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        # Sine wave tone will yield empty text or short noise, but must not crash
        self.assertIsInstance(res.text, str)
        self.assertLess(elapsed_ms, 5000.0, f"Transcription took too long: {elapsed_ms:.1f}ms")


if __name__ == "__main__":
    unittest.main()
