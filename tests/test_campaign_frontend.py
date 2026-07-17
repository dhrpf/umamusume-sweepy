import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_campaign_loop_ui_uses_member_names_instead_of_raw_chara_ids():
    app_js = (ROOT / "public" / "campaigns.js").read_text(encoding="utf-8")

    assert "function loopMembers(loop)" in app_js
    assert "members.map((member) => escapeHtml(member.name))" in app_js
    assert "data-pin-id=\"${member.charaId}\"" in app_js
    assert "data-deck-chara=\"${member.charaId}\"" in app_js
    assert "final_parent_chara_id: Number(state.draft.selectedFinalParent.chara_id)" in app_js
    assert "ids.map((id) => `Chara ${id}`)" not in app_js
    assert "`Assign a deck to Chara ${charaId}.`" not in app_js


def test_campaign_manual_loadout_supports_per_member_friend_selection():
    html = (ROOT / "public" / "campaigns.html").read_text(encoding="utf-8")
    app_js = (ROOT / "public" / "campaigns.js").read_text(encoding="utf-8")

    assert 'id="refresh-friend-supports-btn"' in html
    assert "friendSupports: []" in app_js
    assert "friendAssignments: {}" in app_js
    assert "function loadFriendSupports" in app_js
    assert "'/api/career/friends'" in app_js
    assert "data-friend-chara" in app_js
    assert "friend_support:" in app_js
    assert "viewer_id" in app_js
    assert "support_card_id" in app_js


def test_campaign_detail_can_start_a_prepared_auto_run_after_resume():
    app_js = (ROOT / "public" / "campaigns.js").read_text(encoding="utf-8")

    assert "const preparedAutoRun" in app_js
    assert "next === 'start_career' || preparedAutoRun" in app_js
    assert "['approve-run', 'Start Career']" in app_js


def test_campaign_detail_polls_running_and_auto_selecting_states():
    app_js = (ROOT / "public" / "campaigns.js").read_text(encoding="utf-8")

    assert "function pollCampaignProgress" in app_js
    assert "['SELECTING_LINEAGE', 'RUNNING_CAREER', 'EVALUATING_RESULT']" in app_js
    assert "`/api/campaigns/${encodeURIComponent(id)}/advance`" in app_js
    assert "setInterval(pollCampaignProgress" in app_js


def test_campaign_builder_exposes_target_stop_instead_of_hardcoding_it():
    html = (ROOT / "public" / "campaigns.html").read_text(encoding="utf-8")
    app_js = (ROOT / "public" / "campaigns.js").read_text(encoding="utf-8")

    assert 'id="stop-when-target-reached"' in html
    assert "stopWhenTargetReached: false" in app_js
    assert "stop_when_target_reached: state.draft.options.stopWhenTargetReached" in app_js
    assert "stop_when_target_reached: true" not in app_js


def test_campaign_loop_request_includes_selected_final_parent_character():
    app_js = (ROOT / "public" / "campaigns.js").read_text(encoding="utf-8")

    assert "final_parent_chara_id" in app_js
    assert "state.draft.selectedFinalParent.chara_id" in app_js


def test_campaign_tradeoff_renders_current_challenger_sparks_and_history():
    app_js = (ROOT / "public" / "campaigns.js").read_text(encoding="utf-8")

    assert "function selectedCandidate(campaign)" in app_js
    assert "function candidateCard(candidate, role, campaign)" in app_js
    assert "function renderTargetSparks(candidate)" in app_js
    assert "function renderOwnSparks(candidate)" in app_js
    assert "function renderLineageSparks(candidate)" in app_js
    assert "function renderCandidateDelta(current, challenger)" in app_js
    assert "Other candidates" in app_js
    assert "candidate-history-table" in app_js
    history_renderer = app_js.split("function renderCandidateHistory", 1)[1].split("function agendaProgramIds", 1)[0]
    assert "data-candidate-id" not in history_renderer
    assert "candidates.map((candidate) => `<article class=\"candidate-choice\"" not in app_js


def test_campaign_detail_uses_usage_and_selected_candidate_progress_fallbacks():
    app_js = (ROOT / "public" / "campaigns.js").read_text(encoding="utf-8")

    assert "campaign.usage?.runs" in app_js
    assert "selected?.evaluation?.required_progress" in app_js
    assert "selected?.evaluation?.preferred_progress" in app_js
    assert "Raw campaign data" in app_js


def test_campaign_final_setup_resolves_uma_and_parent_names_before_ids():
    app_js = (ROOT / "public" / "campaigns.js").read_text(encoding="utf-8")

    assert "function resolveUmaIdentity(cardId)" in app_js
    assert "function resolveParentIdentity(campaign, finalParent)" in app_js
    assert "state.session?.parents" in app_js
    assert "campaignCandidates(campaign)" in app_js
    assert "Final Uma" in app_js
    assert "Final Parent" in app_js
    assert "Card #${escapeHtml(finalUma.cardId" in app_js
    assert "Veteran #${escapeHtml(finalParent.trainedCharaId" in app_js
    assert "<p>Uma: ${escapeHtml(spec.final_uma?.card_id" not in app_js


def test_campaign_final_setup_identity_has_readable_layout_styles():
    css = (ROOT / "public" / "campaigns.css").read_text(encoding="utf-8")

    assert ".setup-identity-list" in css
    assert ".setup-identity-row" in css
    assert ".setup-identity-meta" in css


def test_campaign_race_agenda_uses_priority_groups_and_program_metadata():
    app_js = (ROOT / "public" / "campaigns.js").read_text(encoding="utf-8")

    assert "function renderRaceAgenda" in app_js
    assert "spec.race_plan" in app_js
    assert "'/assets/data/uma_race_data.json'" in app_js
    assert "Number(race?.program_id)" in app_js
    assert "raceById: new Map()" in app_js
    assert "CORE" in app_js
    assert "OPTIONAL" in app_js
    assert "DEFERABLE" in app_js


def test_campaign_race_metadata_contains_campaign_program_ids():
    race_data = json.loads((ROOT / "public" / "assets" / "data" / "uma_race_data.json").read_text(encoding="utf-8"))
    by_program_id = {int(row["program_id"]): row for row in race_data["races"]}

    assert by_program_id[624]["name"] == "Asahi Hai Futurity Stakes"
    assert by_program_id[163]["name"] == "Satsuki Sho"
    assert by_program_id[79]["name"] == "Japan Cup"


def test_campaign_tradeoff_and_agenda_have_responsive_component_styles():
    css = (ROOT / "public" / "campaigns.css").read_text(encoding="utf-8")

    for selector in (
        ".tradeoff-grid",
        ".candidate-card",
        ".candidate-metrics",
        ".spark-chip",
        ".spark-chip.is-blue",
        ".spark-chip.is-pink",
        ".candidate-delta",
        ".candidate-history-table",
        ".race-group-card",
        ".race-row",
    ):
        assert selector in css
