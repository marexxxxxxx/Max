from max.agents.demo_agent import DemoAgent
from max.remote.server2 import MockServer2
from max.router.graph import build_graph
from tests.conftest import FakeClassifier, FakeDiarizer, FakeTranscriber


def test_e2e_local_flow():
    agents = {"demo-agent": DemoAgent()}
    g = build_graph(FakeTranscriber(), FakeDiarizer(), [{"name": "Alex"}],
                    FakeClassifier(), agents, MockServer2())
    result = g.invoke({"audio": b"synthetic-audio"})
    assert result["speaker"] == "Alex"
    assert result["route"] == "local"
    assert result["answer"] == "Demo-Antwort zu: Testfrage"


def test_e2e_remote_flow():
    agents = {"demo-agent": DemoAgent()}
    g = build_graph(FakeTranscriber(), FakeDiarizer(), [{"name": "Alex"}],
                    FakeClassifier(remote_needed=True), agents, MockServer2())
    result = g.invoke({"audio": b"synthetic-audio"})
    assert result["route"] == "remote"
    assert "[Großes Modell]" in result["answer"]
