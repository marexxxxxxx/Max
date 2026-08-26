import socket
import time

from max.agents.runner import MockAgentRunner
from max.remote.backends import StubBackend
from max.remote.client import RemoteServer2Client
from max.remote.service import Server2Service
from max.router.graph import build_graph
from max.telemetry.recorder import TelemetryRecorder
from tests.conftest import FakeClassifier, FakeDiarizer, FakeTranscriber


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_remote_e2e():
    port = _free_port()
    Server2Service(StubBackend("Stub-Antwort"), port=port).start_in_thread()
    time.sleep(0.2)
    client = RemoteServer2Client("127.0.0.1", port)
    recorder = TelemetryRecorder()
    g = build_graph(
        FakeTranscriber(), FakeDiarizer(), [{"name": "Alex"}],
        FakeClassifier(remote_needed=True),
        [{"name": "ernaehrungsplaner", "keywords": ["ernährung"], "memory_dir": "x"}],
        MockAgentRunner(),
        client,
        recorder=recorder,
    )
    recorder.begin_request()
    first = g.invoke({"audio": b"xx"})
    assert first["awaiting_confirmation"] is True
    second = g.invoke({"confirmation": "Ja", "query": first["query"]})
    assert second["answer"] == "Stub-Antwort"
    record = recorder.build("Alex", "Testfrage", "", True)
    assert record["latency_remote_ms"] is not None
    assert record["tokens_remote"] == 1
