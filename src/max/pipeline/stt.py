class WhisperTranscriber:
    def __init__(self, model_size: str = "small", language: str = "de"):
        self.model_size = model_size
        self.language = language
        self._model = None

    def _ensure(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_size, language=self.language)
        return self._model

    def transcribe(self, audio: bytes) -> str:
        segments, _ = self._ensure().transcribe(audio)
        return " ".join(s.text for s in segments).strip()
