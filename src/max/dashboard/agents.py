"""Agent-Store: liest und schreibt Agent-Profile (YAML) in config/agents/."""
from pathlib import Path

import yaml


class AgentExistsError(Exception):
    """Agent-Name existiert bereits."""


class AgentNotFoundError(Exception):
    """Agent existiert nicht."""


class AgentStore:
    def __init__(self, directory: str):
        self.directory = Path(directory)

    def list_agents(self) -> list[dict]:
        """Listet alle Profile (mit Pfad), sortiert nach Datei-Name."""
        out = []
        for f in sorted(self.directory.glob("*.yaml")):
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data["path"] = str(f)
                out.append(data)
        return out

    def _path_for(self, name: str) -> Path:
        return self.directory / f"{name}.yaml"

    def create(self, profile: dict) -> str:
        """Erstellt ein neues Profil. Existiert es bereits: AgentExistsError."""
        name = profile["name"]
        path = self._path_for(name)
        if path.exists():
            raise AgentExistsError(name)
        path.write_text(self._to_yaml(profile), encoding="utf-8")
        return str(path)

    def update(self, name: str, profile: dict) -> str:
        """Aktualisiert ein bestehendes Profil. Existiert es nicht: AgentNotFoundError."""
        path = self._path_for(name)
        if not path.exists():
            raise AgentNotFoundError(name)
        path.write_text(self._to_yaml(profile), encoding="utf-8")
        return str(path)

    @staticmethod
    def _to_yaml(profile: dict) -> str:
        return yaml.safe_dump(profile, allow_unicode=True)
