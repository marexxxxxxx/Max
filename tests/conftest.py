from max.router.classify import Classification


class FakeTranscriber:
    def transcribe(self, audio: bytes) -> str:
        return "Testfrage"


class FakeDiarizer:
    def diarize(self, audio: bytes):
        return [("SPEAKER_00", 0.0, 1.0)]


class FakeClassifier:
    def __init__(self, agent="demo-agent", confidence=0.9, remote_needed=False):
        self.agent = agent
        self.confidence = confidence
        self.remote_needed = remote_needed

    def classify(self, text: str, agents: list[str]) -> Classification:
        return Classification(self.agent, self.confidence, self.remote_needed)
