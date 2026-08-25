from max.agents.demo_agent import DemoAgent


def build_agents(profiles: list[dict]) -> dict[str, DemoAgent]:
    agents = {}
    for p in profiles:
        if p.get("name") == "demo-agent":
            agents[p["name"]] = DemoAgent()
    return agents
