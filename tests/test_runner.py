import os

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


def test_opencode_runner_command():
    runner = OpencodeRunner(opencode_bin="opencode", opencode_dir="/tmp/x")
    cmd = runner.build_command({"name": "ernaehrungsplaner"})
    assert cmd == ["opencode", "run", "--dir", "/tmp/x", "--agent", "ernaehrungsplaner"]
