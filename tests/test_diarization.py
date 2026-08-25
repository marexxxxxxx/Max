import numpy as np
from max.pipeline.diarization import PyannoteDiarizer

def test_lazy_no_pipeline_on_init():
    assert PyannoteDiarizer()._pipe is None

def test_diarize_with_fake_pipeline(monkeypatch):
    class FakeDiag:
        def itertracks(self, yield_label=True):
            return iter([("single", "SPEAKER_00", 0.0, 1.5)])
    class FakePipeline:
        def __call__(self, audio):
            return FakeDiag()
    d = PyannoteDiarizer()
    d._pipe = FakePipeline()
    segs = d.diarize(np.zeros(1600, dtype=np.int16).tobytes())
    assert segs == [("SPEAKER_00", 0.0, 1.5)]
