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
CONFIRMATION_WORDS = {"ja", "yes", "bitte", "klar", "natürlich", "selbstverständlich", "absolut"}


def is_confirmation(text: str) -> bool:
    """Liefert True, wenn die Äußerung mit einem eindeutigen Ja beginnt.

    Wir prüfen nur das erste Wort, damit „Nein, lass ihn aus" nicht
    versehentlich als Zustimmung gezählt wird. Anhängende Satzzeichen
    am ersten Wort (z. B. „ja,") werden vor dem Vergleich entfernt.
    """
    words = (text or "").strip().lower().split()
    if not words:
        return False
    return words[0].strip(",.!?") in CONFIRMATION_WORDS
