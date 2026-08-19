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
        "parent-one-preview",
        "parent-two-preview",
        "deck-select",
        "deck-preview",
        "friend-support-select",
        "friend-support-preview",
        "priority-skill-picker",
        "priority-skill-search",
        "priority-skill-selection",
        "final-skill-picker",
        "final-skill-search",
        "final-skill-selection",
        "race-schedule-select",
        "independent-race-options",
        "independent-race-popup-overlay",
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


def test_parent_and_deck_controls_replace_raw_technical_inputs():
    html = read("public/independent-training.html")

    assert 'id="deck-select"' in html
    assert 'id="parent-one-preview"' in html
    assert 'id="parent-two-preview"' in html
    assert 'id="deck-preview"' in html
    assert 'id="deck-id"' not in html
    assert 'id="support-card-ids"' not in html


def test_frontend_renders_complete_parent_sparks_and_derives_saved_deck_ids():
    source = read("public/independent-training.js")

    assert "function renderParentPreview" in source
    assert "function renderDeckPreview" in source
    assert "function selectedDeckSupportIds" in source
    assert "tree?.self?.factors" in source
    assert "selectedDeckSupportIds()" in source
    assert "support_card_ids: supports" in source
    assert "bootstrap.decks" in source
    assert "Veteran #" in source
    assert "return 'Red'" in source


def test_friend_support_is_selected_on_independent_page_without_persisting_viewer_id():
    html = read("public/independent-training.html")
    source = read("public/independent-training.js")

    assert 'id="friend-support-select"' in html
    assert 'id="friend-viewer-id"' not in html
    assert 'id="friend-card-id"' not in html
    assert "session?.friends" in source
    assert "function selectedFriendSupport" in source
    assert "state.privateFriends" in source
    assert "friend_viewer_id: asPositiveInt(friend.viewer_id" in source


def test_race_schedule_reuses_dashboard_planner_instead_of_raw_ids():
    html = read("public/independent-training.html")
    source = read("public/independent-training.js")

    assert 'id="race-agenda"' not in html
    assert 'id="race-schedule-select"' in html
    assert 'id="independent-race-options"' in html
    assert 'id="independent-race-popup-overlay"' in html
    assert "/assets/data/uma_race_data.json" in source
    assert "saved_race_agendas" in source
    assert "function renderRacePlanner" in source
    assert "function selectedRaceArray" in source
    assert "race_array: selectedRaceArray()" in source
    assert "year:program_id" not in html


def test_trainee_objectives_fetch_replace_and_lock_planner_slots():
    source = read("public/independent-training.js")

    assert "objectiveRaceIds: []" in source
    assert "objectiveRequestController" in source
    assert "function loadTraineeObjectiveRaces" in source
    assert "/api/independent-training/trainees/${encodeURIComponent(cardId)}/objective-races" in source
    assert ".abort()" in source
    assert "objectiveRequestGeneration" in source
    assert "raceSlotKey" in source
    assert "OBJECTIVE" in source
    assert "state.objectiveRaceIds.includes" in source
    assert "els.trainee.addEventListener('change'" in source


def test_named_skill_pickers_separate_training_priority_from_final_purchase():
    html = read("public/independent-training.html")
    source = read("public/independent-training.js")

    assert "Independent Training Priority Skills" in html
    assert "Final Skills to Buy" in html
    assert 'id="priority-skills"' not in html
    assert 'id="priority-skill-search"' in html
    assert 'id="final-skill-search"' in html
    assert '"/api/skills"' in source
    assert "function renderSkillPicker" in source
    assert "priority_skill_array: state.prioritySkillIds" in source
    assert "final_skill_ids: [...state.finalSkillIds]" in source


def test_named_presets_save_and_restore_the_complete_independent_setup():
    html = read("public/independent-training.html")
    source = read("public/independent-training.js")

    for element_id in (
        "independent-preset-select",
        "independent-preset-name",
        "save-independent-preset",
        "load-independent-preset",
        "delete-independent-preset",
    ):
        assert f'id="{element_id}"' in html
    assert "function populateIndependentPresets" in source
    assert "function applyIndependentPreset" in source
    assert '"/api/independent-training/presets"' in source
    assert "prioritySkillIds" in source
    assert "finalSkillIds" in source
    assert "race_array" in source
    assert "friend_index" in source


def test_server_policy_uses_named_styles_and_read_only_detected_tp_cost():
    html = read("public/independent-training.html")
    source = read("public/independent-training.js")

    assert '<option value="1">Balanced</option>' in html
    assert '<option value="2">Stamina</option>' in html
    assert '<option value="3">Sprint</option>' in html
    assert 'id="detected-tp-cost"' in html
    assert 'id="use-tp"' not in html
    assert "use_tp:" not in source
    assert "detected_tp_cost" in source
    assert "tp_cost_source" in source
    assert "tpCostError ? `Unavailable · ${tpCostError}`" in source


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

    assert "privateFriend" not in persistence
    assert "privateFriends" not in persistence
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


def test_stuck_run_can_be_removed_from_the_active_card_and_queue():
    source = read("public/independent-training.js")

    assert "data-discard-run" in source
    assert "/discard" in source
    assert "function discardRun" in source
    assert "window.confirm" in source
    assert "reconcile/finish the server career first" in source
    assert "const discardable = active.state === 'NEEDS_ATTENTION';" in source


def test_terminal_runs_are_not_listed_as_queued():
    source = read("public/independent-training.js")

    assert "['COMPLETED', 'CANCELLED', 'FAILED'].includes(run.state)" in source


def test_untracked_server_career_can_be_collected_from_the_dashboard():
    source = read("public/independent-training.js")

    assert "status.untracked_server_run" in source
    assert 'id="adopt-server-run"' in source
    assert "/api/independent-training/adopt-server-run" in source
