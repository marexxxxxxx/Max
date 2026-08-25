from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from max.config import resolve_speaker
from max.router.classify import Classification


class State(TypedDict):
    audio: bytes
    text: str
    speaker: str
    agent: str
    confidence: float
    remote_needed: bool
    route: str
    answer: str


def build_graph(transcriber, diarizer, registry, classifier, agents, server2):
    def transcribe(state):
        text = transcriber.transcribe(state["audio"])
        segments = diarizer.diarize(state["audio"])
        speaker = resolve_speaker([s[0] for s in segments], registry)
        return {"text": text, "speaker": speaker}

    def classify(state):
        try:
            c = classifier.classify(state["text"], list(agents.keys()))
        except Exception:
            c = Classification("unknown", 0.0, True)
        return {"agent": c.agent, "confidence": c.confidence, "remote_needed": c.remote_needed}

    def route(state):
        if state["remote_needed"] or state["agent"] not in agents or state["confidence"] < 0.5:
            return {"route": "remote"}
        return {"route": "local"}

    def respond_local(state):
        return {"answer": agents[state["agent"]].run(state["text"])}

    def respond_remote(state):
        server2.wake()
        return {"answer": f"Ich schalte den Hauptrechner ein. {server2.ask(state['text'])}"}

    g = StateGraph(State)
    g.add_node("transcribe", transcribe)
    g.add_node("classify", classify)
    g.add_node("route", route)
    g.add_node("respond_local", respond_local)
    g.add_node("respond_remote", respond_remote)
    g.add_edge(START, "transcribe")
    g.add_edge("transcribe", "classify")
    g.add_edge("classify", "route")
    g.add_conditional_edges("route",
                            lambda s: "respond_local" if s["route"] == "local" else "respond_remote")
    g.add_edge("respond_local", END)
    g.add_edge("respond_remote", END)
    return g.compile()
