import json
import re
from dataclasses import dataclass


@dataclass
class Classification:
    agent: str
    confidence: float
    remote_needed: bool
    tokens: int = 0


SYSTEM_PROMPT = (
    "Klassifiziere die Anfrage. Antworte NUR mit JSON im Format "
    '{{"agent": <name>, "confidence": <Zahl 0-1>, "remote_needed": <true|false>}}. '
    "Verfügbare lokale Agenten: {agents}"
)


def parse_classification(raw: str, tokens: int = 0) -> Classification:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return Classification("unknown", 0.0, True, tokens)
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return Classification("unknown", 0.0, True, tokens)
    return Classification(
        str(data.get("agent", "unknown")),
        float(data.get("confidence", 0.0)),
        bool(data.get("remote_needed", False)),
        tokens,
    )


class OllamaClassifier:
    def __init__(self, model: str):
        self.model = model

    def classify(self, text: str, agents: list[str]) -> Classification:
        import ollama
        prompt = SYSTEM_PROMPT.format(agents=", ".join(agents)) + f"\n\nAnfrage: {text}"
        resp = ollama.chat(model=self.model, messages=[{"role": "user", "content": prompt}])
        return parse_classification(resp["message"]["content"], tokens=resp.get("count", 0))
