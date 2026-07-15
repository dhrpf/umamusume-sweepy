from pathlib import Path

import main


ROOT = Path(__file__).resolve().parent.parent


def test_career_runner_snapshot_exposes_backend_loop_state(monkeypatch):
    monkeypatch.setattr(main.career_runner, "snapshot", lambda: {"running": False, "finished": True})
    monkeypatch.setattr(main.time, "time", lambda: 1000.0)
    monkeypatch.setattr(main, "backend_loop_status", {
        "active": True,
        "phase": "waiting_tp",
        "message": "Waiting for TP regen (4/30)",
        "wait_until": 1120.0,
    })

    snapshot = main._career_runner_snapshot()

    assert snapshot["running"] is False
    assert snapshot["loop"] == {
        "active": True,
        "phase": "waiting_tp",
        "message": "Waiting for TP regen (4/30)",
        "wait_until": 1120.0,
        "remaining_sec": 120,
    }


def test_frontend_has_loop_indicator_and_stop_control():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")

    assert 'id="career-loop-indicator"' in index_html
    assert 'id="career-loop-stop-btn"' in index_html
    assert "function renderCareerLoopIndicator(loop)" in app_js
    assert "runner.loop && runner.loop.active" in app_js
    assert "'/api/career/runner/stop'" in app_js
    assert ".career-loop-indicator" in styles
