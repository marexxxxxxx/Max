from max.agents.nutrition import nutrition_profile
from max.agents.runner import OpencodeRunner, build_task_message


def test_build_task_message_with_card_path():
    msg = build_task_message("Plan für heute", "Memory...", card_path="data/display/cards/ernaehrungsplaner.json")
    assert "data/display/cards/ernaehrungsplaner.json" in msg
    assert "updated_at" in msg


def test_build_task_message_without_card_path():
    msg = build_task_message("Plan für heute", "Memory...")
    assert "Display-Card" not in msg


def test_nutrition_profile_has_card_path():
    profile = nutrition_profile()
    assert profile["card_path"] == "data/display/cards/ernaehrungsplaner.json"


def test_opencode_runner_resolves_card_path():
    runner = OpencodeRunner(opencode_dir="/home/user/max/config/opencode")
    assert runner._resolve_path("data/display/cards/x.json") == "/home/user/max/data/display/cards/x.json"
