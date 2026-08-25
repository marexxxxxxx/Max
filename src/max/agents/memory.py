"""Dateibasiertes Agent-Memory (Subprojekt B).

Jeder Fach-Agent führt sein eigenes kleines Gedächtnis:
- profile.yaml: strukturierte Angaben über die Person (Allergien, Ziele, Vorlieben)
- memory.md: freie Notizen (Gesprächshistorie, Korrekturen)

Die Memory-Dateien werden VON den Agenten selbst mit ihren Dateitools
geschrieben. Der Runner liest sie nur und injiziert den Inhalt als Kontext
in den Task-Prompt. Ein Vector- oder DB-Backend kann später über das
AgentMemory-Interface nachgerüstet werden, ohne den Runner zu ändern.
"""
import os

import yaml


class AgentMemory:
    """Abstraktes Interface für Agent-Memory.

    Die Methoden beschreiben die Minimal-Vertragsfläche, die der Runner
    braucht, um Kontext für den Task-Prompt zu sammeln.
    """

    def get_context(self) -> str:
        """Kompakter Kontext-Text für den Task-Prompt."""
        raise NotImplementedError

    def read_profile(self) -> dict:
        """Strukturiertes Profil (dict) zurückgeben."""
        raise NotImplementedError

    def write_profile(self, key: str, value) -> None:
        """Einen Wert ins Profil schreiben."""
        raise NotImplementedError

    def append_note(self, text: str) -> None:
        """Eine Notiz an memory.md anhängen."""
        raise NotImplementedError


class FileMemory(AgentMemory):
    """Datei-Memory: profile.yaml + memory.md im Agent-Verzeichnis."""

    def __init__(self, agent_dir: str):
        self.agent_dir = agent_dir
        self.profile_path = os.path.join(agent_dir, "profile.yaml")
        self.note_path = os.path.join(agent_dir, "memory.md")

    def read_profile(self) -> dict:
        """Liest profile.yaml; existiert die Datei nicht, leeres dict."""
        if not os.path.exists(self.profile_path):
            return {}
        with open(self.profile_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def write_profile(self, key: str, value) -> None:
        """Schreibt einen Wert in profile.yaml (idempotent, übergibt alte Werte)."""
        profile = self.read_profile()
        profile[key] = value
        os.makedirs(self.agent_dir, exist_ok=True)
        with open(self.profile_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(profile, f, allow_unicode=True, sort_keys=False)

    def append_note(self, text: str) -> None:
        """Hängt eine Zeile an memory.md an (Datei wird bei Bedarf angelegt)."""
        os.makedirs(self.agent_dir, exist_ok=True)
        with open(self.note_path, "a", encoding="utf-8") as f:
            f.write(f"\n{text}\n")

    def get_context(self) -> str:
        """Stellt Profil + Notizen als kompakten Kontext-Text zusammen."""
        profile = self.read_profile()
        lines = []
        if profile:
            lines.append("Profil:")
            for key, value in profile.items():
                lines.append(f"  {key}: {value}")
        if os.path.exists(self.note_path):
            with open(self.note_path, encoding="utf-8") as f:
                notes = f.read().strip()
            if notes:
                lines.append("Notizen:")
                lines.append(notes)
        if not lines:
            return "(noch keine Erinnerungen)"
        return "\n".join(lines)


if __name__ == "__main__":
    pass
