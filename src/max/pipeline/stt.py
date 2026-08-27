class WhisperTranscriber:
    def __init__(self, model_size: str = "small", language: str = "de"):
        self.model_size = model_size
        self.language = language
        self._model = None

    def _ensure(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_size)
        return self._model

    def transcribe(self, audio: bytes) -> str:
        import io
        buf = io.BytesIO(audio)
        segments, _ = self._ensure().transcribe(buf, language=self.language)
        return " ".join(s.text for s in segments).strip()
