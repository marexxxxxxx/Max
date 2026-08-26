"""Standard-Cards für den Smart Mirror: Uhrzeit, Wetter, Kalender.

Wetter kommt von open-meteo (free, ohne API-Key). Alle Provider sind
best-effort: bei Fehlern geben sie None zurück, statt zu crashen.
"""
import datetime
import json
import urllib.request

# Default-Standort (Berlin)
DEFAULT_LAT = 52.52
DEFAULT_LON = 13.405

# open-meteo weather_code → deutsche Beschreibung
WEATHER_TEXT = {
    0: "klar",
    1: "meist klar",
    2: "leicht bewölkt",
    3: "bedeckt",
    45: "Nebel",
    48: "nebelfrost",
    51: "Nieselregen",
    53: "Nieselregen",
    55: "Nieselregen",
    61: "leichter Regen",
    63: "Regen",
    65: "starker Regen",
    71: "leichter Schnee",
    73: "Schnee",
    77: "starker Schnee",
    80: "Regenschauer",
    81: "Regenschauer",
    82: "starke Regenschauer",
    95: "Gewitter",
    96: "Gewitter mit Hagel",
    99: "starkes Gewitter",
}


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _format_temperature(value: float) -> str:
    return f"{value:.1f}".replace(".", ",") + " °C"


def clock_card() -> dict:
    """Uhrzeit-Card (HH:MM, für den Smart Mirror gut lesbar)."""
    return {
        "agent": "display",
        "title": "Zeit",
        "type": "clock",
        "data": {"time": datetime.datetime.now().strftime("%H:%M")},
        "updated_at": _now_iso(),
    }


def open_meteo_fetcher(lat: float, lon: float) -> dict:
    """Holt aktuelle Wetterdaten von open-meteo (ohne API-Key)."""
    url = (
        "https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
        "&hourly=temperature_2m,weather_code".format(lat=lat, lon=lon)
    )
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def weather_card(fetcher, lat: float, lon: float) -> dict | None:
    """Wetter-Card aus einem Fetcher (testbar mit Fake). Fehler → None."""
    try:
        data = fetcher(lat, lon)
        temperature = data["hourly"]["temperature_2m"][0]
        code = data["hourly"]["weather_code"][0]
    except Exception:
        return None
    return {
        "agent": "display",
        "title": "Wetter",
        "type": "weather",
        "data": {
            "temperature": _format_temperature(temperature),
            "condition": WEATHER_TEXT.get(code, "unbekannt"),
        },
        "updated_at": _now_iso(),
    }


def calendar_card(path: str) -> dict | None:
    """Kalender-Card aus einer lokalen JSON-Datei. Fehlt/leer → None."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        events = raw.get("events", [])
    except (OSError, json.JSONDecodeError):
        return None
    if not events:
        return None
    today = datetime.date.today().isoformat()
    lines = []
    for event in events:
        date = event.get("date", "")
        title = event.get("title", "")
        prefix = "heute" if date == today else date
        lines.append(f"{prefix}: {title}")
    return {
        "agent": "display",
        "title": "Kalender",
        "type": "calendar",
        "data": {"events": lines},
        "updated_at": _now_iso(),
    }
