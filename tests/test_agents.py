from max.agents.demo_agent import DemoAgent
from max.agents.registry import build_agents


def test_demo_agent_run():
    assert DemoAgent().run("Testfrage") == "Demo-Antwort zu: Testfrage"


def test_build_agents():
    profiles = [{"name": "demo-agent", "keywords": []}]
    agents = build_agents(profiles)
    assert "demo-agent" in agents
    assert isinstance(agents["demo-agent"], DemoAgent)


def test_build_agents_unknown_name_skipped():
    agents = build_agents([{"name": "unknown-agent"}])
    assert agents == {}
