from max.agents.runner import MockAgentRunner
from max.remote.server2 import MockServer2
from max.smoke import run_smoke
from tests.conftest import FakeClassifier, FakeDiarizer, FakeTranscriber


class FakeTts:
    def synthesize_chunks(self, text: str) -> list[bytes]:
        return [b"xx"]


def test_smoke_local(tmp_path):
    profiles = [{"name": "ernaehrungsplaner", "keywords": ["ernährung"], "memory_dir": "x"}]
    summary = run_smoke(
        b"xx", FakeTranscriber(), FakeDiarizer(), [{"name": "Alex"}],
        FakeClassifier(agent="ernaehrungsplaner"), profiles, MockAgentRunner(),
        MockServer2(), tts=FakeTts(), store_path=str(tmp_path / "t.db"),
    )
    assert summary["route"] == "local"
    assert summary["speaker"] == "Alex"
    assert summary["tts_bytes"] == 2
    assert summary["telemetry_recorded"] is True
