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
    interview_mode: bool

# Interview-Modus (Subprojekt F): Marker, mit denen der Onboarding-Agent
# signalisiert, ob weitere Fragen folgen. Max. viele Turns pro Interview.
ASK_MARKER = "[ASK]"
DONE_MARKER = "[DONE]"
MAX_INTERVIEW_TURNS = 10
STT_ERROR_ANSWER = "Entschuldigung, ich konnte die Sprache nicht verstehen."
WAKE_FAILED_ANSWER = "Der Hauptrechner lässt sich leider nicht einschalten."


def build_graph(transcriber, diarizer, registry, classifier, profiles, runner, server2, recorder=None):
    """Baut die State-Maschine.

    profiles: Liste von Agent-Profilen (dicts mit „name", „keywords", ...).
    runner: AgentRunner, der die Fach-Agenten ausführt.
    recorder: optionale Telemetrie (TelemetryRecorder); Fehler dürfen die
    Pipeline nie crashen.
    """
    agent_names = [p["name"] for p in profiles]

    def _start(stage):
        # Telemetrie-Call: bei Fehler nur loggen, Pipeline weiterlaufen lassen
        if recorder is None:
            return
        try:
            recorder.start(stage)
        except Exception as e:
            print(f"[Max] Telemetrie-Error: {e}")

    def _end(stage):
        if recorder is None:
            return
        try:
            recorder.end(stage)
        except Exception as e:
            print(f"[Max] Telemetrie-Error: {e}")

    def _add_tokens(stage, n):
        if recorder is None:
            return
        try:
            recorder.add_tokens(stage, n)
        except Exception as e:
            print(f"[Max] Telemetrie-Error: {e}")

    def _tel_tokens(stage, text):
        if recorder is None:
            return
        try:
            recorder.add_tokens(stage, recorder.estimate_tokens(text))
        except Exception as e:
            print(f"[Max] Telemetrie-Error: {e}")

    def transcribe(state):
        _start("stt")
        try:
            text = transcriber.transcribe(state["audio"])
            segments = diarizer.diarize(state["audio"])
            speaker = resolve_speaker([s[0] for s in segments], registry)
        except Exception:
            # STT/Diarization down → lokale Entschuldigung statt Crash
            _end("stt")
            return {"text": "", "speaker": "unbekannt", "query": "",
                    "route": "local", "answer": STT_ERROR_ANSWER,
                    "awaiting_confirmation": False}
        _end("stt")
        return {"text": text, "speaker": speaker, "query": text}

    def classify(state):
        _start("router")
        try:
            c = classifier.classify(state["text"], agent_names)
        except Exception:
            # Fehlfall (z. B. ollama down) → sicher remote
            c = Classification("unknown", 0.0, True)
        _end("router")
        _add_tokens("router", c.tokens)
        return {"agent": c.agent, "confidence": c.confidence, "remote_needed": c.remote_needed}

    def route(state):
        # Onboarding-Anfragen laufen immer über den Interview-Node
        if state["agent"] == "onboarding":
            return "interview"
        if state["remote_needed"] or state["agent"] not in agent_names or state["confidence"] < 0.5:
            return "respond_remote"
        return "respond_local"

    def respond_local(state):
        profile = next((p for p in profiles if p["name"] == state["agent"]), None)
        if profile is None:
            return {"route": "hitl", "answer": HITL_QUESTION, "query": state["text"],
                    "awaiting_confirmation": True, "escalation_reason": "unbekannter Agent"}
        _start("agent")
        result = runner.run(profile, state["text"])
        _end("agent")
        _tel_tokens("agent", result.answer)
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
            _start("remote")
            if not server2.wake():
                _end("remote")
                return {"answer": WAKE_FAILED_ANSWER, "awaiting_confirmation": False}
            answer = server2.ask(state.get("query", ""))
            _end("remote")
            tokens = getattr(server2, "last_tokens", None)
            if tokens is None:
                _tel_tokens("remote", answer)
            else:
                _add_tokens("remote", tokens)
            return {"answer": answer, "awaiting_confirmation": False}
        return {"answer": "Alles klar, dann bleibe ich lokal.", "awaiting_confirmation": False}

    def interview(state):
        profile = next((p for p in profiles if p["name"] == "onboarding"), None)
        if profile is None:
            return {"route": "hitl", "answer": "Das Onboarding kann ich leider nicht durchführen.",
                    "query": state["text"], "awaiting_confirmation": False,
                    "interview_mode": False}
        _start("agent")
        result = runner.run(profile, state["text"])
        _end("agent")
        _tel_tokens("agent", result.answer)
        answer = result.answer
        interview_mode = False
        if result.escalated:
            answer = "Das Onboarding kann ich leider nicht durchführen."
        else:
            if ASK_MARKER in answer:
                interview_mode = True
                answer = answer.replace(ASK_MARKER, "").strip()
            if DONE_MARKER in answer:
                answer = answer.replace(DONE_MARKER, "").strip()
        return {"route": "local", "answer": answer, "awaiting_confirmation": False,
                "interview_mode": interview_mode}

    def post_transcribe(state):
        # STT-Fehler liefert bereits eine Antwort → direkt zu END
        if state.get("answer"):
            return "end"
        # Interview-Fortsetzung geht direkt zum Onboarding, sonst Klassifikation
        if state.get("interview_mode"):
            return "interview"
        return "classify"

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
    g.add_node("interview", interview)
    g.add_conditional_edges(START, start_router, {"transcribe": "transcribe", "confirm": "confirm"})
    g.add_conditional_edges("transcribe", post_transcribe,
                            {"end": END, "interview": "interview", "classify": "classify"})
    g.add_edge("interview", END)
    g.add_conditional_edges(
        "classify", route,
        {"respond_local": "respond_local", "respond_remote": "respond_remote", "interview": "interview"}
    )
    g.add_edge("respond_local", END)
    g.add_edge("respond_remote", END)
    g.add_edge("confirm", END)
    return g.compile()
