import os

from datetime import datetime

from max.display.providers import calendar_card, clock_card, weather_card


def test_clock_card_shape():
    card = clock_card()
    assert card["agent"] == "display"
    assert card["type"] == "clock"
    datetime.fromisoformat(card["data"]["time"])


def test_weather_card_with_fake_fetcher():
    def fake_fetch(lat, lon):
        return {"hourly": {"temperature_2m": [21.5], "weather_code": [1]}}
    card = weather_card(fake_fetch, 52.52, 13.405)
    assert card["type"] == "weather"
    assert card["data"]["temperature"] == "21,5 °C"
    assert card["data"]["condition"]


def test_weather_card_returns_none_on_error():
    def broken_fetch(lat, lon):
        raise RuntimeError("offline")
    assert weather_card(broken_fetch, 52.52, 13.405) is None


def test_calendar_card(tmp_path):
    path = tmp_path / "calendar.json"
    path.write_text('{"events": [{"date": "2026-08-25", "title": "Zahnarzt"}]}', encoding="utf-8")
    card = calendar_card(str(path))
    assert card["type"] == "calendar"
    assert len(card["data"]["events"]) == 1


def test_calendar_card_missing_file():
    assert calendar_card("/nonexistent/calendar.json") is None


def test_calendar_card_empty():
    import json
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "calendar.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"events": []}, f)
        assert calendar_card(path) is None
