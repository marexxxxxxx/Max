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
