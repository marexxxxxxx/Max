from max.router.classify import parse_classification, OllamaClassifier


def test_parse_valid():
    raw = '{"agent": "demo-agent", "confidence": 0.9, "remote_needed": false}'
    c = parse_classification(raw)
    assert (c.agent, c.confidence, c.remote_needed) == ("demo-agent", 0.9, False)


def test_parse_embedded():
    raw = 'Hier ist das Ergebnis: {"agent": "demo-agent", "confidence": 0.7, "remote_needed": true} hoffentlich'
    c = parse_classification(raw)
    assert c.remote_needed is True and c.agent == "demo-agent"


def test_parse_garbage_falls_back_to_remote():
    c = parse_classification("keine json hier")
    assert c.remote_needed is True and c.agent == "unknown" and c.confidence == 0.0


def test_classifier_with_mocked_ollama(monkeypatch):
    def fake_chat(model, messages):
        return {"message": {"content": '{"agent": "demo-agent", "confidence": 0.8, "remote_needed": false}'}}
    import ollama
    monkeypatch.setattr(ollama, "chat", fake_chat)
    c = OllamaClassifier("test-model").classify("Hallo", ["demo-agent"])
    assert c.agent == "demo-agent" and c.remote_needed is False


def test_classifier_tokens_fallback_without_count(monkeypatch):
    def fake_chat(model, messages):
        return {"message": {"content": '{"agent": "demo-agent", "confidence": 0.8, "remote_needed": false}'}}
    import ollama
    monkeypatch.setattr(ollama, "chat", fake_chat)
    c = OllamaClassifier("test-model").classify("Hallo", ["demo-agent"])
    assert c.tokens > 0
