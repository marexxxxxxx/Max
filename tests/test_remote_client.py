import socket
import time

from max.remote.backends import StubBackend
from max.remote.client import RemoteServer2Client
from max.remote.service import Server2Service


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class BootOnTrigger:
    """Simuliert das Einschalten des Hauptrechners: bei trigger() kommt Server 2 up."""

    def __init__(self, port):
        self.port = port

    def trigger(self):
        Server2Service(StubBackend("Pong"), port=self.port).start_in_thread()


def test_wake_true_with_running_service():
    port = _free_port()
    Server2Service(StubBackend("Pong"), port=port).start_in_thread()
    time.sleep(0.2)
    assert RemoteServer2Client("127.0.0.1", port).wake() is True


def test_ask_returns_answer_and_tokens():
    port = _free_port()
    Server2Service(StubBackend("Pong"), port=port).start_in_thread()
    time.sleep(0.2)
    client = RemoteServer2Client("127.0.0.1", port)
    assert client.ask("Hallo") == "Pong"
    assert client.last_tokens == 1


def test_wake_false_without_power_switch():
    port = _free_port()  # kein Service auf diesem Port
    client = RemoteServer2Client("127.0.0.1", port, wake_timeout=0.2, poll_interval=0.1)
    assert client.wake() is False


def test_ask_fallback_when_unreachable():
    port = _free_port()
    client = RemoteServer2Client("127.0.0.1", port)
    assert client.ask("Hallo") == "Der Hauptrechner ist nicht erreichbar"


def test_wake_with_power_switch():
    port = _free_port()
    client = RemoteServer2Client(
        "127.0.0.1", port,
        power_switch=BootOnTrigger(port),
        wake_timeout=10.0, poll_interval=0.1,
    )
    assert client.wake() is True
