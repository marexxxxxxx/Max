from max.tts.kokoro_tts import chunk_text, KokoroTts

def test_chunk_text_short():
    assert chunk_text("Hallo Welt.", max_chars=100) == ["Hallo Welt."]

def test_chunk_text_splits_long():
    text = ("Satz eins. " * 30)
    chunks = chunk_text(text, max_chars=100)
    assert all(len(c) <= 100 for c in chunks)
    assert len(chunks) > 1

def test_kokoro_tts_with_fake_k(monkeypatch):
    class FakeK:
        def generate(self, text):
            return (b"fake-audio", 22050)
    tts = KokoroTts()
    monkeypatch.setattr(KokoroTts, "_ensure", lambda self: FakeK())
    out = tts.synthesize_chunks("Hallo Welt. Bye.")
    assert out == [b"fake-audio", b"fake-audio"]
