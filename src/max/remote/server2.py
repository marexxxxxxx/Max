class MockServer2:
    """Stub für Server 2: simuliert Wake-Trigger und Antwort des großen Modells."""

    def wake(self) -> bool:
        return True

    def ask(self, query: str) -> str:
        return f"[Großes Modell] Antwort zu: {query}"
