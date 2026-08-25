from max.agents.runner import MockAgentRunner
from max.remote.server2 import MockServer2
from max.router.graph import build_graph
from tests.conftest import FakeClassifier, FakeDiarizer, FakeTranscriber


def _profiles():
    return [{"name": "ernaehrungsplaner", "keywords": ["ernährung"], "memory_dir": "x"}]


def test_e2e_local_flow():
    g = build_graph(FakeTranscriber(), FakeDiarizer(), [{"name": "Alex"}],
                    FakeClassifier(agent="ernaehrungsplaner"), _profiles(),
                    MockAgentRunner(), MockServer2())
    result = g.invoke({"audio": b"synthetic-audio"})
    assert result["speaker"] == "Alex"
    assert result["route"] == "local"
    assert result["answer"] == "Mock-Antwort zu: Testfrage"


def test_e2e_extended_mode_flow():
    g = build_graph(FakeTranscriber(), FakeDiarizer(), [{"name": "Alex"}],
                    FakeClassifier(remote_needed=True), _profiles(),
                    MockAgentRunner(), MockServer2())
    first = g.invoke({"audio": b"synthetic-audio"})
    assert first["route"] == "hitl"
    assert first["awaiting_confirmation"] is True
    second = g.invoke({"confirmation": "Ja", "query": first["query"]})
    assert "[Großes Modell]" in second["answer"]
    assert second["awaiting_confirmation"] is False


def test_e2e_declined_remote_flow():
    g = build_graph(FakeTranscriber(), FakeDiarizer(), [{"name": "Alex"}],
                    FakeClassifier(remote_needed=True), _profiles(),
                    MockAgentRunner(), MockServer2())
    g.invoke({"audio": b"synthetic-audio"})
    second = g.invoke({"confirmation": "Nein", "query": "Testfrage"})
    assert second["answer"] == "Alles klar, dann bleibe ich lokal."
