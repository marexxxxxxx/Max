"""Startpunkt: python -m max.dashboard"""
import os

from max.dashboard.server import DashboardServer


def main():
    port = int(os.environ.get("MAX_DASHBOARD_PORT", "8081"))
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    server = DashboardServer(
        db_path=os.path.join(root, "data", "telemetry.db"),
        agents_dir=os.path.join(root, "config", "agents"),
    )
    server.serve_forever(port=port)


if __name__ == "__main__":
    main()
