from __future__ import annotations
from pathlib import Path
import yaml

# Einheitsmodell für den lokalen Klassifikator (muss im Ollama-Cache existieren)
DEFAULT_OLLAMA_MODEL = "qwen3.5:9b"


def load_speakers(path: str) -> list[dict]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return data.get("speakers", [])


def load_agent_profiles(directory: str) -> list[dict]:
    d = Path(directory)
    return [yaml.safe_load(f.read_text(encoding="utf-8"))
            for f in sorted(d.glob("*.yaml"))]


def resolve_speaker(speaker_ids: list[str], registry: list[dict]) -> str:
    unique = sorted(set(speaker_ids))
    if len(unique) == 1 and len(registry) >= 1:
        return registry[0]["name"]
    return "unbekannt"
