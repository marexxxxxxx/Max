import json

from max.display.cards import CardStore, validate_card


def test_validate_card_ok():
    card = {
        "agent": "test",
        "title": "Titel",
        "type": "generic",
        "data": {"foo": "bar"},
        "updated_at": "2026-08-25T12:00:00+00:00",
    }
    assert validate_card(card) is card


def test_validate_card_rejects_missing_fields():
    assert validate_card({"agent": "test"}) is None
    assert validate_card({"agent": "test", "title": "T"}) is None


def test_validate_card_rejects_bad_type():
    assert validate_card(
        {
            "agent": "a",
            "title": "T",
            "type": "unknown",
            "data": {},
            "updated_at": "2026-08-25T12:00:00+00:00",
        }
    ) is None


def test_card_store_load_and_poll(tmp_path):
    store = CardStore(str(tmp_path))
    assert store.load_all() == []
    (tmp_path / "agent1.json").write_text(
        json.dumps(
            {
                "agent": "agent1",
                "title": "T1",
                "type": "generic",
                "data": {"x": 1},
                "updated_at": "2026-08-25T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    cards = store.load_all()
    assert len(cards) == 1
    assert cards[0]["agent"] == "agent1"
    # Erster Poll: neue Cards werden erkannt
    changed = store.poll()
    assert len(changed) == 1
    # Zweiter Poll: keine Änderung
    assert store.poll() == []
