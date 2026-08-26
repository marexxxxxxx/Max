import os


def test_frontend_files():
    # tests/ liegt nur 1 Ebene unter dem Repo-Root → 2× dirname
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    static = os.path.join(root, "src", "max", "display", "static")
    with open(os.path.join(static, "index.html"), encoding="utf-8") as f:
        html = f.read()
    assert "EventSource" in html
    assert "/api/cards" in html
    assert "style.css" in html
    assert os.path.exists(os.path.join(static, "style.css"))


def test_mirror_2_features():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "src", "max", "display", "static", "index.html"), encoding="utf-8") as f:
        html = f.read()
    assert "weatherIcon" in html
    assert "today" in html
    assert "fade" in html
