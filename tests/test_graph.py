from max.agents.runner import AgentResult, MockAgentRunner
from max.remote.server2 import MockServer2
from max.router.graph import build_graph
from tests.conftest import FakeClassifier, FakeDiarizer, FakeTranscriber


def _profiles():
    return [{"name": "ernaehrungsplaner", "keywords": ["ernährung"], "memory_dir": "x"}]


def _graph(classifier, runner=None, transcriber=None):
    runner = runner if runner is not None else MockAgentRunner()
    return build_graph(
        transcriber or FakeTranscriber(), FakeDiarizer(), [{"name": "Alex"}],
        classifier, _profiles(), runner, MockServer2(),
    )


def test_local_route():
    result = _graph(FakeClassifier(agent="ernaehrungsplaner")).invoke({"audio": b"xx"})
    assert result["route"] == "local"
    assert result["speaker"] == "Alex"
    assert result["answer"] == "Mock-Antwort zu: Testfrage"
    assert result["awaiting_confirmation"] is False


def test_remote_route_asks_confirmation():
    result = _graph(FakeClassifier(remote_needed=True)).invoke({"audio": b"xx"})
    assert result["route"] == "hitl"
    assert result["awaiting_confirmation"] is True
    assert result["answer"].startswith("Das braucht den großen Rechner")
    assert result["query"] == "Testfrage"


def test_low_confidence_goes_hitl():
    result = _graph(FakeClassifier(confidence=0.2, agent="ernaehrungsplaner")).invoke({"audio": b"xx"})
    assert result["route"] == "hitl"
    assert result["awaiting_confirmation"] is True


def test_unknown_agent_goes_hitl():
    result = _graph(FakeClassifier(agent="unbekannt")).invoke({"audio": b"xx"})
    assert result["route"] == "hitl"


def test_classifier_failure_goes_hitl():
    class Broken:
        def classify(self, text, agents):
            raise RuntimeError("ollama down")
    result = _graph(Broken()).invoke({"audio": b"xx"})
    assert result["route"] == "hitl"


def test_agent_escalation_goes_hitl():
    runner = MockAgentRunner(escalated=True, reason="medizinische Frage")
    result = _graph(FakeClassifier(agent="ernaehrungsplaner"), runner).invoke({"audio": b"xx"})
    assert result["route"] == "hitl"
    assert result["awaiting_confirmation"] is True
    assert result["escalation_reason"] == "medizinische Frage"


def test_confirmation_yes_calls_server2():
    g = _graph(FakeClassifier(remote_needed=True))
    first = g.invoke({"audio": b"xx"})
    second = g.invoke({"confirmation": "Ja", "query": first["query"]})
    assert "[Großes Modell]" in second["answer"]
    assert second["awaiting_confirmation"] is False


def test_confirmation_no_stays_local():
    g = _graph(FakeClassifier(remote_needed=True))
    first = g.invoke({"audio": b"xx"})
    second = g.invoke({"confirmation": "Nein", "query": first["query"]})
    assert second["answer"] == "Alles klar, dann bleibe ich lokal."
    assert second["awaiting_confirmation"] is False


class FakeInterviewRunner:
    """Erster Turn: Frage + [ASK], zweiter Turn: Abschluss + [DONE]."""
    def __init__(self):
        self.calls = 0

    def run(self, agent_profile, task):
        self.calls += 1
        if self.calls == 1:
            return AgentResult(answer="Wie sind deine Allergien? [ASK]")
        return AgentResult(answer="Alles notiert [DONE]")


def _graph_interview(runner):
    profiles = [{"name": "onboarding", "keywords": ["onboarding"], "memory_dir": "x"}]
    return build_graph(
        FakeTranscriber(), FakeDiarizer(), [{"name": "Alex"}],
        FakeClassifier(agent="onboarding"), profiles, runner, MockServer2(),
    )


def test_interview_mode_continues():
    runner = FakeInterviewRunner()
    g = _graph_interview(runner)
    first = g.invoke({"audio": b"xx"})
    assert first["interview_mode"] is True
    assert "[ASK]" not in first["answer"]
    assert runner.calls == 1
    second = g.invoke({"audio": b"xx", "interview_mode": True})
    assert second["interview_mode"] is False
    assert "[DONE]" not in second["answer"]
    assert runner.calls == 2


def test_interview_no_marker_ends():
    runner = MockAgentRunner(answer="Interview fertig")
    g = _graph_interview(runner)
    result = g.invoke({"audio": b"xx"})
    assert result["interview_mode"] is False


class BrokenTranscriber:
    def transcribe(self, audio):
        raise RuntimeError("Whisper ist down")


class FakeDeadServer2:
    def wake(self):
        return False
    def ask(self, query):
        raise AssertionError("ask darf bei fehlgeschlagener Wake nicht aufgerufen werden")


def test_wake_failure_gives_clear_message():
    g = build_graph(
        FakeTranscriber(), FakeDiarizer(), [{"name": "Alex"}],
        FakeClassifier(remote_needed=True), _profiles(), MockAgentRunner(), FakeDeadServer2(),
    )
    first = g.invoke({"audio": b"xx"})
    second = g.invoke({"confirmation": "Ja", "query": first["query"]})
    assert second["answer"] == "Der Hauptrechner lässt sich leider nicht einschalten."
    assert second["awaiting_confirmation"] is False


def test_transcribe_failure_routes_local_with_apology():
    result = _graph(FakeClassifier(remote_needed=False), transcriber=BrokenTranscriber()).invoke({"audio": b"xx"})
    assert result["route"] == "local"
    assert result["answer"] == "Entschuldigung, ich konnte die Sprache nicht verstehen."
    assert result["awaiting_confirmation"] is False
