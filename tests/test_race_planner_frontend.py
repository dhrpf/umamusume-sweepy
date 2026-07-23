from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_race_planner_falls_back_to_gametora_banner_by_program_id():
    app_js = (ROOT / "public" / "app.js").read_text(encoding="utf-8")

    assert "function fallbackRaceBanner" in app_js
    assert "https://media.gametora.com/umamusume/races/banners/en/${programId}.png" in app_js
    assert "fallbackRaceBanner(this, ${Number(selected.program_id || 0)})" in app_js
    assert "fallbackRaceBanner(this, ${Number(race.program_id || 0)})" in app_js
