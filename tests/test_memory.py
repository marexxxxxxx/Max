from max.agents.memory import FileMemory


def test_empty_context(tmp_path):
    mem = FileMemory(str(tmp_path))
    assert mem.read_profile() == {}
    assert mem.get_context() == "(noch keine Erinnerungen)"


def test_profile_roundtrip(tmp_path):
    mem = FileMemory(str(tmp_path))
    mem.write_profile("allergien", "Erdnüsse")
    assert mem.read_profile() == {"allergien": "Erdnüsse"}


def test_append_note(tmp_path):
    mem = FileMemory(str(tmp_path))
    mem.append_note("Liebt Zitronen")
    mem.append_note("Vermeidet Zucker")
    text = (tmp_path / "memory.md").read_text(encoding="utf-8")
    assert "Liebt Zitronen" in text
    assert "Vermeidet Zucker" in text


def test_context_includes_profile_and_notes(tmp_path):
    mem = FileMemory(str(tmp_path))
    mem.write_profile("sport", "Krafttraining")
    mem.append_note("Ziel: 80g Protein")
    context = mem.get_context()
    assert "sport: Krafttraining" in context
    assert "Ziel: 80g Protein" in context
