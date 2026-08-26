from max.main import make_server2, resolve_model
from max.remote.client import RemoteServer2Client
from max.remote.server2 import MockServer2
from max.remote.wake import CommandPowerSwitch


def test_resolve_model_default():
    assert resolve_model({}) == "qwen3.5:9b"


def test_resolve_model_env_override():
    assert resolve_model({"MAX_OLLAMA_MODEL": "other-model"}) == "other-model"


def test_mock_by_default():
    assert isinstance(make_server2({}), MockServer2)


def test_remote_client_from_env():
    s2 = make_server2({"MAX_REMOTE_HOST": "10.0.0.5", "MAX_REMOTE_PORT": "9000"})
    assert isinstance(s2, RemoteServer2Client)
    assert s2.host == "10.0.0.5"
    assert s2.port == 9000


def test_power_switch_from_env():
    s2 = make_server2({
        "MAX_REMOTE_HOST": "10.0.0.5",
        "MAX_POWER_SWITCH_CMD": "curl http://switch/wake",
    })
    assert isinstance(s2.power_switch, CommandPowerSwitch)


def test_no_power_switch_without_env():
    s2 = make_server2({"MAX_REMOTE_HOST": "10.0.0.5"})
    assert s2.power_switch is None


def test_main_imports_without_portaudio():
    # sounddevice wird lazy importiert → Import muss ohne PortAudio funktionieren
    import max.main


def test_interview_overrun_ends_cleanly():
    from max.main import INTERVIEW_OVERFLOW_ANSWER, apply_interview_state
    result = {"interview_mode": True, "answer": "Wie sind deine Allergien?"}
    mode, turns = apply_interview_state(result, False, 10)
    assert mode is False
    assert turns == 11
    assert result["answer"] == INTERVIEW_OVERFLOW_ANSWER


def test_interview_normal_turn_continues():
    from max.main import apply_interview_state
    result = {"interview_mode": True, "answer": "Wie sind deine Allergien?"}
    mode, turns = apply_interview_state(result, False, 1)
    assert (mode, turns) == (True, 2)


def test_interview_done_resets():
    from max.main import apply_interview_state
    result = {"interview_mode": False, "answer": "Fertig"}
    mode, turns = apply_interview_state(result, True, 5)
    assert (mode, turns) == (False, 0)
