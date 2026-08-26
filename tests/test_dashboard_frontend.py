import os


def test_index_html():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    static = os.path.join(root, "src", "max", "dashboard", "static")
    path = os.path.join(static, "index.html")
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        html = f.read()
    assert "EventSource" in html
    assert "/events" in html
    assert "/api/agents" in html
    assert "style.css" in html


def test_style_css():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "src", "max", "dashboard", "static", "style.css")
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        css = f.read()
    assert "background" in css


from pathlib import Path


def test_remote_latency_column():
    text = Path(__file__).parent.parent / "src" / "max" / "dashboard" / "static" / "index.html"
    text = text.read_text(encoding="utf-8")
    assert "latency_remote_ms" in text
    assert "Remote-Latenz" in text


def test_dashboard_calm_light_features():
    text = Path(__file__).parent.parent / "src" / "max" / "dashboard" / "static" / "index.html"
    text = text.read_text(encoding="utf-8")
    assert "theme-toggle" in text
    assert "badge" in text
    assert "latency-bar" in text
    assert "MAX_ROWS" in text
