from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_dailies_page_and_routes_are_exposed():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
    main_py = (ROOT / "main.py").read_text(encoding="utf-8")

    for element_id in (
        "dailies-nav-btn",
        "dailies-view",
        "daily-team-trials",
        "daily-daily-races",
        "daily-legend-races",
        "daily-shop",
        "daily-veteran",
        "daily-opponent",
        "daily-legend-id",
        "dailies-run",
        "dailies-stop",
        "dailies-log",
    ):
        assert f'id="{element_id}"' in index_html

    assert "navigateDailiesPage" in app_js
    assert 'fetch("/api/dailies/status")' in app_js
    assert 'fetch("/api/dailies/legend_options"' in app_js
    assert 'fetch("/api/dailies/run"' in app_js
    assert 'fetch("/api/dailies/stop"' in app_js
    assert "setInterval(pollDailies, 2000)" in app_js

    assert '@app.get("/api/dailies/status")' in main_py
    assert '@app.post("/api/dailies/legend_options")' in main_py
    assert '@app.post("/api/dailies/run")' in main_py
    assert '@app.post("/api/dailies/stop")' in main_py
    assert '@app.get("/dailies", response_class=HTMLResponse)' in main_py
