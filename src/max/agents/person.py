"""Gemeinsames Personen-Profil (Subprojekt F).

Ein strukturiertes Profil der Person (Allergien, Ziele, Vorlieben,
Beschränkungen), das von allen Agenten geteilt wird. Die Datei liegt in
data/memory/person.yaml (Pfad via Constructor). Die Agenten schreiben die
Datei per opencode-Dateitools; der Python-Runner liest sie und injiziert den
Kontext in die Task-Prompts.
"""
import os

import yaml


class PersonMemory:
    """Datei-Personen-Profil: person.yaml."""

    def __init__(self, path: str):
        self.path = path

    def read(self) -> dict:
        """Liest person.yaml; existiert die Datei nicht, leeres dict."""
        if not os.path.exists(self.path):
            return {}
        with open(self.path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def write_category(self, key: str, value) -> None:
        """Schreibt eine Kategorie in person.yaml (idempotent)."""
        profile = self.read()
        profile[key] = value
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            yaml.safe_dump(profile, f, allow_unicode=True, sort_keys=False)

    def get_context(self) -> str:
        """Personen-Profil als kompakten Kontext-Text für Task-Prompts."""
        profile = self.read()
        if not profile:
            return "(noch keine Erinnerungen)"
        lines = ["Personen-Profil:"]
        for key, value in profile.items():
            lines.append(f"  {key}: {value}")
        return "\n".join(lines)
