from max.agents.runner import MockAgentRunner
from max.remote.server2 import MockServer2
from max.smoke import run_smoke
from max.telemetry.store import TelemetryStore
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


def test_smoke_latency_measured(tmp_path):
    db = str(tmp_path / "t.db")
    profiles = [{"name": "ernaehrungsplaner", "keywords": ["ernährung"], "memory_dir": "x"}]
    run_smoke(
        b"xx", FakeTranscriber(), FakeDiarizer(), [{"name": "Alex"}],
        FakeClassifier(agent="ernaehrungsplaner"), profiles, MockAgentRunner(),
        MockServer2(), tts=FakeTts(), store_path=db,
    )
    store = TelemetryStore(db)
    rows = store.recent(1)
    store.close()
    assert rows[0]["latency_total_ms"] is not None
    assert rows[0]["latency_total_ms"] < 5000
