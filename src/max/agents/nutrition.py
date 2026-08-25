"""Definition des Beispiel-Agenten „Ernährungsplaner" (Subprojekt B).

Dieses Modul liefert nur das Agent-Profil (Defaults). Der System-Prompt
lebt in config/opencode/ernaehrungsplaner.prompt.md und wird von
opencode.json referenziert — hier keine Duplizierung.

Die Plattform ist multi-agent tauglich: weitere Fach-Agenten folgen dem
selben Muster (YAML + prompt.md + opencode.json-Eintrag).
"""

# Agent-Name (ASCII-Identifier für die opencode CLI)
AGENT_NAME = "ernaehrungsplaner"


def nutrition_profile() -> dict:
    """Profil des Ernährungsplaners.

    Spiegelbild von config/agents/ernaehrungsplaner.yaml; das YAML ist die
    persistente Quelle, dieser dict ist das In-Memory-Äquivalent, das der
    Runner verwendet. memory_dir ist relativ zum Repo-Root.
    """
    return {
        "name": AGENT_NAME,
        "description": "Ernährungsplaner: plant Mahlzeiten, nutzt Mealie",
        "keywords": ["ernährung", "essen", "rezepte", "protein", "fitness", "plan"],
        "capabilities": ["meal plan", "recipes", "nutrition"],
        "runner": "opencode",
        "memory_dir": "data/agents/ernaehrungsplaner",
    }
