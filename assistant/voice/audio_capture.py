"""Native Windows Audio Capture using winmm.dll (Phase 11).

Provides explicit, user-controlled microphone recording:
- Native Win32 waveIn API via ctypes (zero external C audio dependencies).
- Strict 16000 Hz, 16-bit, mono PCM (standard input format for Whisper / local STT).
- Push-to-talk or explicit start/stop/cancel control.
- Explicit device enumeration and availability checks.
- Energy/RMS calculation for silence and volume detection.
- WAV container generation using Python's built-in wave module.
- Strict isolation: zero continuous listening, zero background recording.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import io
import math
import struct
import threading
import time
import wave
from typing import Any, Optional

_winmm = ctypes.windll.winmm

# ──────────────────────────────────────────────────────────────────────────────
# Win32 waveIn Structures & Constants
# ──────────────────────────────────────────────────────────────────────────────

WAVE_FORMAT_PCM = 1
MMSYSERR_NOERROR = 0

CALLBACK_FUNCTION = 0x00030000
CALLBACK_EVENT = 0x00050000
CALLBACK_NULL = 0x00000000

WIM_OPEN = 0x3BE
WIM_CLOSE = 0x3BF
WIM_DATA = 0x3C0

WAVE_MAPPER = -1


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


class WAVEHDR(ctypes.Structure):
    pass


WAVEHDR._fields_ = [
    ("lpData", ctypes.POINTER(ctypes.c_char)),
    ("dwBufferLength", wintypes.DWORD),
    ("dwBytesRecorded", wintypes.DWORD),
    ("dwUser", wintypes.DWORD),
    ("dwFlags", wintypes.DWORD),
    ("dwLoops", wintypes.DWORD),
    ("lpNext", ctypes.POINTER(WAVEHDR)),
    ("reserved", wintypes.DWORD),
]


class WAVEINCAPSW(ctypes.Structure):
    _fields_ = [
        ("wMid", wintypes.WORD),
        ("wPid", wintypes.WORD),
        ("vDriverVersion", wintypes.DWORD),
        ("szPname", ctypes.c_wchar * 32),
        ("dwFormats", wintypes.DWORD),
        ("wChannels", wintypes.WORD),
        ("wReserved1", wintypes.WORD),
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Custom Exceptions
# ──────────────────────────────────────────────────────────────────────────────

class AudioCaptureError(Exception):
    """Base error for voice capture operations."""
    pass


class MicrophoneUnavailableError(AudioCaptureError):
    """Raised when no recording device is found or microphone is disconnected."""
    pass


class RecordingCancelledError(AudioCaptureError):
    """Raised when the user cancels recording."""
    pass


class EmptyAudioError(AudioCaptureError):
    """Raised when recorded audio contains only silence or zero bytes."""
    pass


# ──────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ──────────────────────────────────────────────────────────────────────────────

def get_input_devices() -> list[dict[str, Any]]:
    """List all available Windows waveIn audio recording devices."""
    num_devs = _winmm.waveInGetNumDevs()
    devices = []
    for i in range(num_devs):
        caps = WAVEINCAPSW()
        res = _winmm.waveInGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps))
        if res == MMSYSERR_NOERROR:
            devices.append({
                "id": i,
                "name": caps.szPname.strip(),
                "channels": caps.wChannels,
            })
    return devices


def is_microphone_available() -> bool:
    """Return True if at least one audio recording device is available."""
    return _winmm.waveInGetNumDevs() > 0


def calculate_rms(pcm_bytes: bytes) -> float:
    """Calculate Root Mean Square (RMS) amplitude of 16-bit mono PCM bytes."""
    if not pcm_bytes or len(pcm_bytes) < 2:
        return 0.0

    n_samples = len(pcm_bytes) // 2
    sum_squares = 0.0

    for i in range(n_samples):
        sample = struct.unpack_from("<h", pcm_bytes, i * 2)[0]
        sum_squares += float(sample * sample)

    mean_square = sum_squares / max(1, n_samples)
    return math.sqrt(mean_square)


def pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 16000, channels: int = 1, sampwidth: int = 2) -> bytes:
    """Pack raw PCM bytes into a standard RIFF/WAV byte container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


# ──────────────────────────────────────────────────────────────────────────────
# AudioRecorder
# ──────────────────────────────────────────────────────────────────────────────

class AudioRecorder:
    """User-controlled native Win32 audio recorder for local speech input.

    Uses a double-buffered waveIn mechanism to continuously capture 16kHz mono audio.
    """

    DEFAULT_SAMPLE_RATE = 16000
    DEFAULT_BUFFER_DURATION = 0.2  # 200ms per buffer chunk
    NUM_BUFFERS = 3

    def __init__(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        device_id: int = 0,
        buffer_duration_s: float = DEFAULT_BUFFER_DURATION,
    ) -> None:
        self.sample_rate = sample_rate
        self.device_id = device_id
        self.buffer_duration_s = buffer_duration_s
        self.buffer_size = int(self.sample_rate * 2 * self.buffer_duration_s)  # 16-bit mono = 2 bytes/sample

        self._h_wave_in: Optional[wintypes.HANDLE] = None
        self._buffers: list[tuple[ctypes.Array, WAVEHDR]] = []
        self._recorded_chunks: list[bytes] = []
        self._is_recording = False
        self._is_cancelled = False
        self._lock = threading.Lock()
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    def start_recording(self) -> None:
        """Start explicit user-controlled recording session."""
        with self._lock:
            if self._is_recording:
                return

            if not is_microphone_available():
                raise MicrophoneUnavailableError("Microphone tidak tersedia atau tidak terdeteksi pada sistem Windows.")

            self._recorded_chunks.clear()
            self._is_cancelled = False
            self._stop_event.clear()

            # Configure 16000 Hz, 16-bit, 1 channel PCM
            wfx = WAVEFORMATEX()
            wfx.wFormatTag = WAVE_FORMAT_PCM
            wfx.nChannels = 1
            wfx.nSamplesPerSec = self.sample_rate
            wfx.wBitsPerSample = 16
            wfx.nBlockAlign = 2
            wfx.nAvgBytesPerSec = self.sample_rate * 2
            wfx.cbSize = 0

            h_in = wintypes.HANDLE()
            res = _winmm.waveInOpen(
                ctypes.byref(h_in),
                self.device_id,
                ctypes.byref(wfx),
                0,
                0,
                CALLBACK_NULL,
            )
            if res != MMSYSERR_NOERROR:
                raise AudioCaptureError(f"Gagal membuka perangkat microphone (winmm waveInOpen error code: {res}).")

            self._h_wave_in = h_in

            # Allocate and prepare headers
            self._buffers.clear()
            for _ in range(self.NUM_BUFFERS):
                raw_buf = (ctypes.c_char * self.buffer_size)()
                hdr = WAVEHDR()
                hdr.lpData = ctypes.cast(raw_buf, ctypes.POINTER(ctypes.c_char))
                hdr.dwBufferLength = self.buffer_size
                hdr.dwFlags = 0

                prep_res = _winmm.waveInPrepareHeader(self._h_wave_in, ctypes.byref(hdr), ctypes.sizeof(hdr))
                if prep_res != MMSYSERR_NOERROR:
                    self._cleanup_native()
                    raise AudioCaptureError(f"Gagal mempersiapkan audio buffer header (error: {prep_res}).")

                add_res = _winmm.waveInAddBuffer(self._h_wave_in, ctypes.byref(hdr), ctypes.sizeof(hdr))
                if add_res != MMSYSERR_NOERROR:
                    self._cleanup_native()
                    raise AudioCaptureError(f"Gagal mendaftarkan audio buffer (error: {add_res}).")

                self._buffers.append((raw_buf, hdr))

            start_res = _winmm.waveInStart(self._h_wave_in)
            if start_res != MMSYSERR_NOERROR:
                self._cleanup_native()
                raise AudioCaptureError(f"Gagal memulai perekaman audio (error: {start_res}).")

            self._is_recording = True

            # Start buffer poll worker
            self._worker_thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._worker_thread.start()

    def _poll_loop(self) -> None:
        """Poll completed buffers while recording."""
        WHDR_DONE = 0x00000001

        while not self._stop_event.is_set():
            time.sleep(0.04)
            with self._lock:
                if not self._is_recording or not self._h_wave_in:
                    break

                for raw_buf, hdr in self._buffers:
                    if hdr.dwFlags & WHDR_DONE:
                        bytes_rec = hdr.dwBytesRecorded
                        if bytes_rec > 0:
                            data = ctypes.string_at(hdr.lpData, bytes_rec)
                            self._recorded_chunks.append(data)

                        # Reset flags and requeue buffer
                        hdr.dwBytesRecorded = 0
                        hdr.dwFlags &= ~WHDR_DONE
                        _winmm.waveInAddBuffer(self._h_wave_in, ctypes.byref(hdr), ctypes.sizeof(hdr))

    def stop_recording(self, min_duration_s: float = 0.3, silence_rms_threshold: float = 50.0) -> bytes:
        """Stop recording and return raw 16kHz mono PCM bytes.

        Raises:
            RecordingCancelledError: If cancelled.
            EmptyAudioError: If recorded audio is too short or below silence threshold.
        """
        with self._lock:
            if not self._is_recording:
                if self._is_cancelled:
                    raise RecordingCancelledError("Perekaman audio telah dibatalkan.")
                pcm = b"".join(self._recorded_chunks)
                if not pcm:
                    raise EmptyAudioError("Tidak ada data audio yang terekam.")
                return pcm

            self._stop_event.set()
            self._is_recording = False

            if self._h_wave_in:
                _winmm.waveInStop(self._h_wave_in)
                _winmm.waveInReset(self._h_wave_in)

            # Harvest any remaining recorded bytes in buffers
            for raw_buf, hdr in self._buffers:
                if hdr.dwBytesRecorded > 0:
                    data = ctypes.string_at(hdr.lpData, hdr.dwBytesRecorded)
                    self._recorded_chunks.append(data)

            self._cleanup_native()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=0.5)

        if self._is_cancelled:
            raise RecordingCancelledError("Perekaman audio dibatalkan oleh pengguna.")

        pcm_data = b"".join(self._recorded_chunks)
        total_duration_s = len(pcm_data) / (self.sample_rate * 2)

        if total_duration_s < min_duration_s:
            raise EmptyAudioError(
                f"Durasi audio terlalu singkat ({total_duration_s:.2f}s < {min_duration_s:.2f}s)."
            )

        rms = calculate_rms(pcm_data)
        if rms < silence_rms_threshold:
            raise EmptyAudioError(
                f"Audio terdeteksi sunyi (RMS {rms:.1f} < threshold {silence_rms_threshold:.1f})."
            )

        return pcm_data

    def cancel_recording(self) -> None:
        """Cancel the current recording without processing."""
        with self._lock:
            self._is_cancelled = True
            self._stop_event.set()
            self._is_recording = False
            self._recorded_chunks.clear()

            if self._h_wave_in:
                _winmm.waveInStop(self._h_wave_in)
                _winmm.waveInReset(self._h_wave_in)
                self._cleanup_native()

    def _cleanup_native(self) -> None:
        """Safely release waveIn buffers and handle."""
        if not self._h_wave_in:
            return

        for raw_buf, hdr in self._buffers:
            _winmm.waveInUnprepareHeader(self._h_wave_in, ctypes.byref(hdr), ctypes.sizeof(hdr))

        _winmm.waveInClose(self._h_wave_in)
        self._h_wave_in = None
        self._buffers.clear()

    def record_for_duration(
        self,
        duration_s: float,
        min_duration_s: float = 0.3,
        silence_rms_threshold: float = 50.0,
    ) -> bytes:
        """Convenience method to record synchronously for a fixed duration."""
        self.start_recording()
        time.sleep(duration_s)
        return self.stop_recording(
            min_duration_s=min_duration_s,
            silence_rms_threshold=silence_rms_threshold,
        )
