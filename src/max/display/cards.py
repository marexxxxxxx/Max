"""Card-Modul: Validierung und dateibasiertes Polling von Agent-Cards.

Fach-Agenten schreiben ihre Cards als JSON-Dateien in ein gemeinsames
Verzeichnis. Der Display-Server pollt dieses Verzeichnis und streamt
Änderungen per SSE.
"""
import json
import os

ALLOWED_TYPES = ("meal", "weather", "calendar", "clock", "generic")


def validate_card(raw: dict) -> dict | None:
    """Validiert eine Card. Gibt das Original zurück oder None bei Fehlern."""
    if not isinstance(raw, dict):
        return None
    for field in ("agent", "title", "type", "data", "updated_at"):
        if field not in raw:
            return None
    if raw["type"] not in ALLOWED_TYPES:
        return None
    if not isinstance(raw["data"], dict):
        return None
    return raw


class CardStore:
    """Liest Cards aus einem Verzeichnis und erkennt Änderungen per Datei-Mtime.

    poll() liefert alle Cards, die seit dem letzten Poll neu oder geändert wurden.
    """

    def __init__(self, directory: str):
        self.directory = directory
        self._last_seen: dict[str, float] = {}

    def _read_card(self, name: str) -> dict | None:
        path = os.path.join(self.directory, name)
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            card = validate_card(raw)
        except (json.JSONDecodeError, OSError):
            return None
        if card is None:
            return None
        card["_file"] = name
        return card

    def load_all(self) -> list[dict]:
        """Liest alle gültigen Cards aus dem Verzeichnis (sortiert)."""
        cards = []
        for name in sorted(os.listdir(self.directory)):
            if not name.endswith(".json"):
                continue
            card = self._read_card(name)
            if card is not None:
                cards.append(card)
        return cards

    def poll(self) -> list[dict]:
        """Erkennt neue/geänderte Cards anhand der Dateimtimes."""
        changed = []
        for name in sorted(os.listdir(self.directory)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(self.directory, name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if mtime > self._last_seen.get(name, 0.0):
                card = self._read_card(name)
                if card is None:
                    continue
                self._last_seen[name] = mtime
                changed.append(card)
        # gelöschte Dateien aus dem Mtime-Speicher entfernen
        existing = set(os.listdir(self.directory))
        self._last_seen = {k: v for k, v in self._last_seen.items() if k in existing}
        return changed
