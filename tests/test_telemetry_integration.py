from max.agents.runner import MockAgentRunner
from max.remote.server2 import MockServer2
from max.router.graph import build_graph
from max.telemetry.recorder import TelemetryRecorder
from max.telemetry.store import TelemetryStore
from tests.conftest import FakeClassifier, FakeDiarizer, FakeTranscriber


def _profiles():
    return [{"name": "ernaehrungsplaner", "keywords": ["ernährung"], "memory_dir": "x"}]


def _graph(recorder=None):
    return build_graph(
        FakeTranscriber(), FakeDiarizer(), [{"name": "Alex"}],
        FakeClassifier(agent="ernaehrungsplaner"), _profiles(),
        MockAgentRunner(), MockServer2(),
        recorder=recorder,
    )


def test_local_request_recorded(tmp_path):
    recorder = TelemetryRecorder()
    recorder.begin_request()
    result = _graph(recorder).invoke({"audio": b"xx"})
    store = TelemetryStore(str(tmp_path / "telemetry.db"))
    store.record(recorder.build(
        speaker=result["speaker"],
        text=result["text"],
        agent=result["agent"],
        remote_needed=bool(result["remote_needed"]),
    ))
    row = store.recent(1)[0]
    assert row["agent"] == "ernaehrungsplaner"
    assert row["remote_needed"] == 0
    assert row["latency_stt_ms"] is not None
    assert row["latency_total_ms"] > 0


class BrokenRecorder:
    def begin_request(self):
        pass

    def start(self, stage):
        raise RuntimeError("telemetrie kaputt")

    def end(self, stage):
        raise RuntimeError("telemetrie kaputt")

    def add_tokens(self, stage, n):
        raise RuntimeError("telemetrie kaputt")

    def estimate_tokens(self, text):
        return 0

    def build(self, *args):
        return {}


def test_recorder_failure_does_not_crash():
    result = _graph(BrokenRecorder()).invoke({"audio": b"xx"})
    assert result["route"] == "local"
    assert result["answer"] == "Mock-Antwort zu: Testfrage"
