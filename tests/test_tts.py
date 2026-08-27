from max.tts.piper_tts import chunk_text, PiperTts


def test_chunk_text_short():
    assert chunk_text("Hallo Welt.", max_chars=100) == ["Hallo Welt."]


def test_chunk_text_splits_long():
    text = ("Satz eins. " * 30)
    chunks = chunk_text(text, max_chars=100)
    assert all(len(c) <= 100 for c in chunks)
    assert len(chunks) > 1


class _FakeChunk:
    def __init__(self, data: bytes):
        self._data = data

    @property
    def audio_int16_bytes(self):
        return self._data


class _FakeVoice:
    def synthesize(self, text):
        return [_FakeChunk(b"fake-audio")]


def test_piper_tts_with_fake_voice(monkeypatch):
    tts = PiperTts()
    monkeypatch.setattr(PiperTts, "_ensure", lambda self: _FakeVoice())
    out = tts.synthesize_chunks("Hallo Welt. Bye.")
    assert out == [b"fake-audio", b"fake-audio"]
