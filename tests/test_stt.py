import pytest
from max.pipeline.stt import WhisperTranscriber

def test_lazy_no_model_on_init():
    t = WhisperTranscriber()
    assert t._model is None

def test_transcribe_with_fake_model(monkeypatch):
    class FakeModel:
        def transcribe(self, audio, language=None):
            return ([type("S", (), {"text": "Hallo Welt"})()], None)
    monkeypatch.setattr(WhisperTranscriber, "_ensure", lambda self: FakeModel())
    assert WhisperTranscriber().transcribe(b"audio") == "Hallo Welt"
