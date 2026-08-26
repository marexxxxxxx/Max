from max.agents.person import PersonMemory


def test_read_missing(tmp_path):
    mem = PersonMemory(str(tmp_path / "person.yaml"))
    assert mem.read() == {}


def test_write_category_roundtrip(tmp_path):
    mem = PersonMemory(str(tmp_path / "person.yaml"))
    mem.write_category("allergien", ["Milch"])
    mem.write_category("ziele", "80g Protein")
    assert mem.read() == {"allergien": ["Milch"], "ziele": "80g Protein"}


def test_get_context_empty(tmp_path):
    mem = PersonMemory(str(tmp_path / "person.yaml"))
    assert mem.get_context() == "(noch keine Erinnerungen)"


def test_get_context_with_profile(tmp_path):
    mem = PersonMemory(str(tmp_path / "person.yaml"))
    mem.write_category("allergien", ["Milch"])
    context = mem.get_context()
    assert "Personen-Profil:" in context
    assert "allergien" in context
