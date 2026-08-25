import re


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


class KokoroTts:
    def __init__(self, voice: str = "af_de-1"):
        self.voice = voice
        self._k = None

    def _ensure(self):
        if self._k is None:
            from kokoro import K
            self._k = K(self.voice)
        return self._k

    def synthesize_chunks(self, text: str) -> list[bytes]:
        k = self._ensure()
        out = []
        for chunk in chunk_text(text):
            audio, _ = k.generate(chunk)
            out.append(audio.tobytes() if hasattr(audio, "tobytes") else audio)
        return out
