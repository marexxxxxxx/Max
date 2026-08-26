"""Human-in-the-loop Gate: vor dem Umschalten auf Server 2 muss der
Nutzer per Sprache bestätigen.

Das Gate ist als Graph-Node integriert: nach „respond_remote" oder einer
Agent-Eskalation liefert der erste Turn die Frage (HITL_QUESTION).
Die Bestätigungsrunde kommt als zweiter Graph-Aufruf (state["confirmation"]);
der Node „confirm" entscheidet dann: ja → Server 2, nein → lokal bleiben.
"""

# Frage, die Max vor dem Server-2-Umschalten stellt
HITL_QUESTION = "Das braucht den großen Rechner (Server 2). Soll ich ihn einschalten?"

# Wörter, mit denen eine Bestätigung eindeutig beginnt
CONFIRMATION_WORDS = {"ja", "jaja", "yes", "bitte", "klar", "natürlich", "selbstverständlich", "absolut", "einverstanden"}
NEGATION_WORDS = {"nein", "nicht", "aber"}


def is_confirmation(text: str) -> bool:
    """Liefert True, wenn die Äußerung eine Bestätigung ist.

    Bestätigungs-Wort als erstes Wort + keine Negation (nein/nicht/aber)
    in den ersten drei Wörtern — deckt typische STT-Ergebnisse ab
    („jaja", „ja, ja", „Ja, aber …"). Anhängende Satzzeichen am ersten
    Wort werden vor dem Vergleich entfernt.
    """
    words = (text or "").strip().lower().split()
    if not words:
        return False
    first = words[0].strip(",.!?")
    if first not in CONFIRMATION_WORDS:
        return False
    return not any(w.strip(",.!?") in NEGATION_WORDS for w in words[:3])
