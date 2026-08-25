from max.remote.server2 import MockServer2

def test_wake_returns_true():
    assert MockServer2().wake() is True

def test_ask_returns_answer():
    assert MockServer2().ask("Pong") == "[Großes Modell] Antwort zu: Pong"
