import webrtcvad

SAMPLE_RATE = 16000
FRAME_MS = 30
frame_bytes = SAMPLE_RATE * FRAME_MS // 1000 * 2


class Vad:
    def __init__(self, aggressiveness: int = 2):
        self._vad = webrtcvad.Vad(aggressiveness)

    def is_speech(self, frame: bytes) -> bool:
        return self._vad.is_speech(frame, SAMPLE_RATE)
