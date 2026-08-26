from max.config import load_speakers, load_agent_profiles, resolve_speaker

def test_load_speakers(tmp_path):
    p = tmp_path / "speakers.yaml"
    p.write_text('speakers:\n  - name: Alex\n  - name: Sam\n', encoding="utf-8")
    reg = load_speakers(str(p))
    assert [s["name"] for s in reg] == ["Alex", "Sam"]

def test_load_agent_profiles(tmp_path):
    f = tmp_path / "demo.yaml"
    f.write_text('name: demo-agent\nkeywords: [demo]\n', encoding="utf-8")
    prof = load_agent_profiles(str(tmp_path))
    assert prof[0]["name"] == "demo-agent"

def test_resolve_speaker_single():
    reg = [{"name": "Alex"}]
    assert resolve_speaker(["SPEAKER_00"], reg) == "Alex"

def test_resolve_speaker_multiple():
    reg = [{"name": "Alex"}]
    assert resolve_speaker(["SPEAKER_00", "SPEAKER_01"], reg) == "unbekannt"


def test_onboarding_profile():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    profiles = load_agent_profiles(os.path.join(root, "config", "agents"))
    names = [p["name"] for p in profiles]
    assert "onboarding" in names
    ob = next(p for p in profiles if p["name"] == "onboarding")
    assert ob["person_path"] == "data/memory/person.yaml"
    assert "onboarding" in ob["keywords"]


def test_opencode_json_has_onboarding():
    import json
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = json.loads(open(os.path.join(root, "config", "opencode", "opencode.json"),
                          encoding="utf-8").read())
    assert "onboarding" in cfg["agent"]
