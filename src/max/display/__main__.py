"""Entry-Point: python -m max.display

Startet den Display-Server auf localhost (Port via MAX_DISPLAY_PORT, Default 8080).
"""
import os

from max.display.server import DisplayServer


def main():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    card_dir = os.path.join(root, "data", "display", "cards")
    calendar_path = os.path.join(root, "config", "calendar.json")
    port = int(os.environ.get("MAX_DISPLAY_PORT", "8080"))
    DisplayServer(card_dir, calendar_path=calendar_path).serve_forever(port=port)


if __name__ == "__main__":
    main()
