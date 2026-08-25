from max.agents.demo_agent import DemoAgent
from max.remote.server2 import MockServer2
from max.router.graph import build_graph
from tests.conftest import FakeClassifier, FakeDiarizer, FakeTranscriber


def _graph(classifier, agents=None, server2=None):
    agents = agents if agents is not None else {"demo-agent": DemoAgent()}
    registry = [{"name": "Alex"}]
    return build_graph(FakeTranscriber(), FakeDiarizer(), registry, classifier, agents,
                       server2 if server2 is not None else MockServer2())


def test_local_route():
    result = _graph(FakeClassifier()).invoke({"audio": b"xx"})
    assert result["route"] == "local"
    assert result["speaker"] == "Alex"
    assert result["answer"] == "Demo-Antwort zu: Testfrage"

def test_remote_route():
    result = _graph(FakeClassifier(remote_needed=True)).invoke({"audio": b"xx"})
    assert result["route"] == "remote"
    assert result["answer"].startswith("Ich schalte den Hauptrechner ein.")

def test_low_confidence_goes_remote():
    assert _graph(FakeClassifier(confidence=0.2)).invoke({"audio": b"xx"})["route"] == "remote"

def test_unknown_agent_goes_remote():
    assert _graph(FakeClassifier(agent="unbekannt")).invoke({"audio": b"xx"})["route"] == "remote"

def test_classifier_failure_goes_remote():
    class Broken:
        def classify(self, text, agents):
            raise RuntimeError("ollama down")
    assert _graph(Broken()).invoke({"audio": b"xx"})["route"] == "remote"
