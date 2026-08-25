import numpy as np
from max.pipeline.vad import Vad, frame_bytes

def _pcm(freq: float, silent: bool = False) -> bytes:
    n = 16000 * 30 // 1000
    t = np.arange(n) / 16000
    samples = np.zeros(n) if silent else 0.3 * np.sin(2 * np.pi * freq * t)
    return (samples * 32767).astype(np.int16).tobytes()

def test_speech_detected():
    assert Vad().is_speech(_pcm(440))

def test_silence_not_detected():
    assert not Vad().is_speech(_pcm(440, silent=True))

def test_frame_bytes():
    assert frame_bytes == 960  # 30 ms @ 16 kHz int16
