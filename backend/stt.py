"""Local Whisper speech-to-text on one short clip. Runs offline, no key."""
import os
import threading

from faster_whisper import WhisperModel

MODEL_SIZE = os.getenv("WHISPER_MODEL", "base")

_model = None
_model_lock = threading.Lock()


def _get_model() -> WhisperModel:
    global _model
    with _model_lock:
        if _model is None:
            _model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


def transcribe(path: str) -> str:
    segments, _info = _get_model().transcribe(path)
    return " ".join(segment.text.strip() for segment in segments).strip()
