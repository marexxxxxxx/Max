from max.remote.wake import CommandPowerSwitch, PowerSwitch


def test_power_switch_abstract():
    try:
        PowerSwitch().trigger()
        assert False, "trigger() muss NotImplementedError werfen"
    except NotImplementedError:
        pass


def test_command_power_switch_runs_command(tmp_path):
    marker = tmp_path / "marker"
    CommandPowerSwitch(f"touch {marker}").trigger()
    assert marker.exists()
