import re
from pathlib import Path


DEFAULT_VOICE = "de_DE-thorsten-medium.onnx"


def _default_voice_path() -> str:
    root = Path(__file__).resolve().parents[3]
    return str(root / "data" / "voices" / DEFAULT_VOICE)


def chunk_text(text: str, max_chars: int = 200) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[str] = []
    for s in sentences:
        while len(s) > max_chars:
            chunks.append(s[:max_chars])
            s = s[max_chars:]
        if s:
            chunks.append(s)
    return chunks


class PiperTts:
    def __init__(self, voice_path: str | None = None):
        self.voice_path = voice_path or _default_voice_path()
        self._voice = None

    def _ensure(self):
        if self._voice is None:
            from piper import PiperVoice
            self._voice = PiperVoice.load(self.voice_path)
        return self._voice

    def synthesize_chunks(self, text: str) -> list[bytes]:
        voice = self._ensure()
        out: list[bytes] = []
        for chunk in chunk_text(text):
            for audio in voice.synthesize(chunk):
                out.append(audio.audio_int16_bytes)
        return out
