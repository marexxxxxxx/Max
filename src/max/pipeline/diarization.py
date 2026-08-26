class PyannoteDiarizer:
    def __init__(self):
        self._pipe = None

    def _ensure(self):
        if self._pipe is None:
            from pyannote.audio import Pipeline
            self._pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.0")
        return self._pipe

    def diarize(self, audio: bytes) -> list[tuple[str, float, float]]:
        import numpy as np
        if len(audio) % 2:
            audio = audio[:-1]
        data = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        if data.size == 0:
            return []
        diarization = self._ensure()(data)
        return [(spk, float(start), float(end))
                for _, spk, start, end in diarization.itertracks(yield_label=True)]
