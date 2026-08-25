"""Tests für den AgentStore (YAML-Read/Write für Dashboard)."""
import pytest

from max.dashboard.agents import AgentExistsError, AgentNotFoundError, AgentStore


@pytest.fixture
def store(tmp_path):
    return AgentStore(str(tmp_path))


def test_list_agents(store):
    store.create({"name": "demo", "description": "Demo-Agent"})
    store.create({"name": "other", "description": "Anderer Agent"})
    agents = store.list_agents()
    assert [a["name"] for a in agents] == ["demo", "other"]
    for a in agents:
        assert a["path"].endswith(f"{a['name']}.yaml")


def test_create_conflict(store):
    store.create({"name": "demo", "description": "Demo-Agent"})
    with pytest.raises(AgentExistsError):
        store.create({"name": "demo", "description": "Nochmal"})


def test_update(store):
    store.create({"name": "demo", "description": "alt"})
    store.update("demo", {"name": "demo", "description": "neu"})
    agents = store.list_agents()
    assert agents[0]["description"] == "neu"


def test_update_missing(store):
    with pytest.raises(AgentNotFoundError):
        store.update("ghost", {"name": "ghost", "description": "x"})
