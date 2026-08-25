import os

from max.agents.nutrition import AGENT_NAME, nutrition_profile


def test_profile_fields():
    profile = nutrition_profile()
    assert profile["name"] == AGENT_NAME
    assert profile["runner"] == "opencode"
    assert "ernährung" in profile["keywords"]
    assert profile["memory_dir"] == "data/agents/ernaehrungsplaner"


def test_config_files_exist():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert os.path.exists(os.path.join(root, "config", "agents", "ernaehrungsplaner.yaml"))
    assert os.path.exists(os.path.join(root, "config", "opencode", "opencode.json"))
    assert os.path.exists(os.path.join(root, "config", "opencode", "ernaehrungsplaner.prompt.md"))
    # Demo-Agent wird vom Ernährungsplaner ersetzt
    assert not os.path.exists(os.path.join(root, "config", "agents", "demo.yaml"))
