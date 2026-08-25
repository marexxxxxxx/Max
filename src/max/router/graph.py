"""LangGraph-State-Maschine: Transkription → Sprecher → Klassifikation → Routing → Antwort.

Routing-Regeln (Subprojekt B):
- remote_needed (Klassifikator), niedrige Konfidenz (< 0.5) oder unbekannter Agent
  → HITL-Gate („respond_remote")
- bekannter Agent mit hoher Konfidenz → lokal: Fach-Agent via AgentRunner
- Agent-Selbst-Eskalation ([ESCALATE]) → dasselbe HITL-Gate

HITL-Gate: Die Frage (HITL_QUESTION) ist die Antwort des ersten Turns.
Die Bestätigungsrunde kommt als zweiter Graph-Aufruf (state["confirmation"]);
der Node „confirm" schaltet dann auf Server 2 (ja) oder bleibt lokal (nein).
"""
from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from max.config import resolve_speaker
from max.router.classify import Classification
from max.router.hitl import HITL_QUESTION, is_confirmation


class State(TypedDict):
    audio: bytes
    text: str
    speaker: str
    agent: str
    confidence: float
    remote_needed: bool
    route: str
    answer: str
    query: str
    awaiting_confirmation: bool
    confirmation: str | None
    escalation_reason: str | None


def build_graph(transcriber, diarizer, registry, classifier, profiles, runner, server2):
    """Baut die State-Maschine.

    profiles: Liste von Agent-Profilen (dicts mit „name", „keywords", ...).
    runner: AgentRunner, der die Fach-Agenten ausführt.
    """
    agent_names = [p["name"] for p in profiles]

    def transcribe(state):
        text = transcriber.transcribe(state["audio"])
        segments = diarizer.diarize(state["audio"])
        speaker = resolve_speaker([s[0] for s in segments], registry)
        return {"text": text, "speaker": speaker, "query": text}

    def classify(state):
        try:
            c = classifier.classify(state["text"], agent_names)
        except Exception:
            # Fehlfall (z. B. ollama down) → sicher remote
            c = Classification("unknown", 0.0, True)
        return {"agent": c.agent, "confidence": c.confidence, "remote_needed": c.remote_needed}

    def route(state):
        if state["remote_needed"] or state["agent"] not in agent_names or state["confidence"] < 0.5:
            return "respond_remote"
        return "respond_local"

    def respond_local(state):
        profile = next((p for p in profiles if p["name"] == state["agent"]), None)
        if profile is None:
            return {"route": "hitl", "answer": HITL_QUESTION, "query": state["text"],
                    "awaiting_confirmation": True, "escalation_reason": "unbekannter Agent"}
        result = runner.run(profile, state["text"])
        if result.escalated:
            return {"route": "hitl", "answer": HITL_QUESTION, "query": state["text"],
                    "awaiting_confirmation": True, "escalation_reason": result.escalation_reason}
        return {"route": "local", "answer": result.answer, "awaiting_confirmation": False}

    def respond_remote(state):
        return {"route": "hitl", "answer": HITL_QUESTION, "query": state["text"],
                "awaiting_confirmation": True, "escalation_reason": "remote_needed"}

    def confirm(state):
        # Bestätigungsrunde: „Ja" schaltet Server 2 ein, sonst lokal bleiben
        if is_confirmation(state.get("confirmation") or ""):
            server2.wake()
            return {"answer": server2.ask(state.get("query", "")), "awaiting_confirmation": False}
        return {"answer": "Alles klar, dann bleibe ich lokal.", "awaiting_confirmation": False}

    def start_router(state):
        # Erster Turn enthält Audio, Bestätigungsrunde kommt ohne Audio
        if state.get("audio"):
            return "transcribe"
        return "confirm"

    g = StateGraph(State)
    g.add_node("transcribe", transcribe)
    g.add_node("classify", classify)
    g.add_node("respond_local", respond_local)
    g.add_node("respond_remote", respond_remote)
    g.add_node("confirm", confirm)
    g.add_conditional_edges(START, start_router, {"transcribe": "transcribe", "confirm": "confirm"})
    g.add_edge("transcribe", "classify")
    g.add_conditional_edges(
        "classify", route, {"respond_local": "respond_local", "respond_remote": "respond_remote"}
    )
    g.add_edge("respond_local", END)
    g.add_edge("respond_remote", END)
    g.add_edge("confirm", END)
    return g.compile()
