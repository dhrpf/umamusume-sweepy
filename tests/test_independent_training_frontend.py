from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main


ROOT = Path(__file__).resolve().parent.parent


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_page_has_no_account_or_career_preset_selector():
    html = read("public/independent-training.html")

    assert 'id="independent-account"' in html
    assert 'id="career-preset"' not in html
    assert 'name="account"' not in html


def test_page_exposes_setup_queue_reroll_and_results_controls():
    html = read("public/independent-training.html")

    for element_id in (
        "active-run",
        "independent-setup-form",
        "trainee-select",
        "parent-one-select",
        "parent-two-select",
        "support-card-ids",
        "friend-viewer-id",
        "friend-card-id",
        "priority-skills",
        "race-agenda",
        "factor-reroll-enabled",
        "factor-targets",
        "add-factor-target",
        "run-count",
        "tp-mode",
        "add-runs",
        "start-queue",
        "stop-after-current",
        "resume-queue",
        "reconcile-queue",
        "queue-list",
        "recent-results",
    ):
        assert f'id="{element_id}"' in html


def test_factor_reroll_warning_is_explicit():
    html = read("public/independent-training.html")

    assert "30 TP" in html
    assert "once per run" in html.lower()
    assert "best of the original and rerolled result" in html.lower()


def test_frontend_uses_relative_api_slow_polling_and_server_owned_state():
    source = read("public/independent-training.js")

    assert "http://127.0.0.1" not in source
    assert '"/api/independent-training/status"' in source
    assert "setInterval(refreshStatus, 5000)" in source
    assert "Date.now() >= end" not in source
    assert "factor_lottery" not in source
    assert '"/api/independent-training/runs"' in source
    assert '"/api/independent-training/start"' in source
    assert '"/api/independent-training/stop-after-current"' in source
    assert '"/api/independent-training/resume"' in source
    assert '"/api/independent-training/reconcile"' in source


def test_frontend_does_not_persist_private_viewer_ids():
    source = read("public/independent-training.js")
    persistence = source.split("function persistConvenience", 1)[1].split(
        "function restoreConvenience", 1
    )[0]

    assert "friend_viewer_id" not in persistence
    assert "rental_viewer_id" not in persistence


@pytest.mark.parametrize(
    ("route", "content_type"),
    [
        ("/independent-training", "text/html"),
        ("/independent-training.js", "application/javascript"),
        ("/independent-training.css", "text/css"),
    ],
)
def test_static_routes_are_no_cache(route, content_type):
    response = TestClient(main.app).get(route)

    assert response.status_code == 200
    assert content_type in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-cache"


def test_dashboard_and_campaign_navigation_link_to_independent_training():
    assert 'href="/independent-training"' in read("public/index.html")
    assert 'href="/independent-training"' in read("public/campaigns.html")
