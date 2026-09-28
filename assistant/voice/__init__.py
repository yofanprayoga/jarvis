"""Voice Input & Local Speech-to-Text Package (Phase 11)."""

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
    BaseSTTProvider,
    FasterWhisperSTTProvider,
    MockSTTProvider,
    STTError,
    STTResult,
    STTUnavailableError,
    SpeechToTextEngine,
    stt_engine,
)
from assistant.voice.voice_controller import (
    VoiceController,
    VoiceSessionResult,
    VoiceState,
    voice_controller,
)

__all__ = [
    # Audio capture
    "AudioCaptureError",
    "AudioRecorder",
    "EmptyAudioError",
    "MicrophoneUnavailableError",
    "RecordingCancelledError",
    "calculate_rms",
    "get_input_devices",
    "is_microphone_available",
    "pcm_to_wav",
    # STT
    "BaseSTTProvider",
    "FasterWhisperSTTProvider",
    "MockSTTProvider",
    "STTError",
    "STTResult",
    "STTUnavailableError",
    "SpeechToTextEngine",
    "stt_engine",
    # Voice controller
    "VoiceController",
    "VoiceSessionResult",
    "VoiceState",
    "voice_controller",
]
