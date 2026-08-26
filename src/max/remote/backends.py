"""Modell-Backends für Server 2: Ollama (Default), Generic-HTTP, Stub."""
import json
import urllib.request


class StubBackend:
    """Feste Antwort für Dev/Tests."""

    def __init__(self, answer: str = "Antwort des großen Modells"):
        self.answer = answer

    def ask(self, query: str) -> tuple[str, int]:
        return self.answer, len(self.answer.split())


class OllamaBackend:
    """Spricht die Ollama-HTTP-API auf Server 2 an (Port 11434)."""

    def __init__(self, host: str = "127.0.0.1", port: int = 11434, model: str = "llama3", timeout: float = 60.0):
        self.host = host
        self.port = port
        self.model = model
        self.timeout = timeout

    def ask(self, query: str) -> tuple[str, int]:
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": query}],
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"http://{self.host}:{self.port}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data["message"]["content"], int(data.get("count", 0))


class GenericHttpBackend:
    """Beliebige Model-API: POST {"query": ...} → {"answer": ..., "tokens": ...}."""

    def __init__(self, url: str, headers: dict | None = None, timeout: float = 60.0):
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout

    def ask(self, query: str) -> tuple[str, int]:
        body = json.dumps({"query": query}).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=body,
            headers={"Content-Type": "application/json", **self.headers},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data["answer"], int(data.get("tokens", 0))
