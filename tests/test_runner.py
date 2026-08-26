import os

from max.agents.person import PersonMemory
from max.agents.runner import (
    MockAgentRunner,
    OpencodeRunner,
    build_task_message,
    parse_agent_output,
)


def test_parse_plain_answer():
    result = parse_agent_output("Hier ist dein Ernährungsplan.")
    assert result.answer == "Hier ist dein Ernährungsplan."
    assert result.escalated is False


def test_parse_escalation():
    result = parse_agent_output("Ich brauche den großen Rechner. [ESCALATE] medizinische Frage")
    assert result.escalated is True
    assert result.escalation_reason == "medizinische Frage"
    assert result.answer == "Ich brauche den großen Rechner."


def test_parse_escalation_only():
    result = parse_agent_output("[ESCALATE] zu komplex")
    assert result.escalated is True
    assert result.escalation_reason == "zu komplex"
    assert result.answer == ""


def test_build_task_message():
    msg = build_task_message("Plane eine Woche", "Profil: sport: Krafttraining")
    assert "Plane eine Woche" in msg
    assert "Profil: sport: Krafttraining" in msg
    assert "[ESCALATE]" in msg


def test_mock_runner_plain():
    runner = MockAgentRunner()
    result = runner.run({"name": "x"}, "Aufgabe")
    assert result.escalated is False
    assert "Aufgabe" in result.answer


def test_mock_runner_escalation():
    runner = MockAgentRunner(escalated=True, reason="nur mit Server 2")
    result = runner.run({"name": "x"}, "Aufgabe")
    assert result.escalated is True
    assert result.escalation_reason == "nur mit Server 2"


def test_opencode_runner_fake_bin(tmp_path):
    # Kleiner Stellvertreter für die opencode CLI: gibt eine Eskalation aus
    script = tmp_path / "fake-opencode"
    script.write_text(
        "#!/bin/sh\nprintf 'Antwort vorab [ESCALATE] Grund der Eskalation'\n",
        encoding="utf-8",
    )
    os.chmod(script, 0o755)
    runner = OpencodeRunner(opencode_bin=str(script), opencode_dir=str(tmp_path), timeout=10.0)
    result = runner.run(
        {"name": "ernaehrungsplaner", "memory_dir": str(tmp_path / "mem")},
        "Aufgabe",
    )
    assert result.escalated is True
    assert result.escalation_reason == "Grund der Eskalation"
    assert result.answer == "Antwort vorab"


def test_relative_memory_dir_resolved_against_repo_root(tmp_path):
    # opencode_dir = <tmp>/config/opencode → Repo-Root = <tmp>
    root = str(tmp_path / "repo")
    os.makedirs(os.path.join(root, "config", "opencode"), exist_ok=True)
    runner = OpencodeRunner(opencode_dir=os.path.join(root, "config", "opencode"))
    assert runner._resolve_memory_dir({"memory_dir": "data/agents/x"}) == \
        os.path.join(root, "data", "agents", "x")
    assert runner._resolve_path("data/memory/person.yaml") == \
        os.path.join(root, "data", "memory", "person.yaml")


def test_opencode_runner_command():
    runner = OpencodeRunner(opencode_bin="opencode", opencode_dir="/tmp/x")
    cmd = runner.build_command({"name": "ernaehrungsplaner"})
    assert cmd == ["opencode", "run", "--dir", "/tmp/x", "--agent", "ernaehrungsplaner"]


def test_build_task_message_with_person():
    msg = build_task_message(
        "Plane eine Woche",
        "Profil: sport: Krafttraining",
        person_context="Personen-Profil:\n  allergien: ['Milch']",
        person_path="/data/memory/person.yaml",
    )
    assert "Personen-Profil:\n  allergien: ['Milch']" in msg
    assert "/data/memory/person.yaml" in msg


def test_opencode_runner_with_person_memory(tmp_path):
    script = tmp_path / "fake-opencode"
    script.write_text("#!/bin/sh\nprintf 'Alles klar'\n", encoding="utf-8")
    os.chmod(script, 0o755)
    person = PersonMemory(str(tmp_path / "person.yaml"))
    person.write_category("allergien", ["Milch"])
    runner = OpencodeRunner(
        opencode_bin=str(script), opencode_dir=str(tmp_path),
        timeout=10.0, person_memory=person,
    )
    result = runner.run(
        {"name": "x", "memory_dir": str(tmp_path / "mem"),
         "person_path": str(tmp_path / "person.yaml")},
        "Aufgabe",
    )
    assert result.answer == "Alles klar"
    assert result.escalated is False
