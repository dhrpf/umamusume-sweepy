"""Smoke tests: verify every module can be imported without errors.

Catches missing deps, syntax errors, and module-level init failures.
"""
import pytest


# ── Modules with no external deps ──────────────────────────────────────

def test_import_delay():
    import career_bot.delay
    assert career_bot.delay.resolve_tp_mode("wait") == "wait"


def test_import_presets():
    import career_bot.presets
    assert callable(career_bot.presets.normalize_skill_list)


def test_import_report():
    import career_bot.report
    r = career_bot.report.new_report({"name": "test"}, 4)
    assert isinstance(r, dict)
    assert r["preset_name"] == "test"


def test_import_races():
    from career_bot.races import RacePlanner
    # Constructor doesn't fail on bad dir — _load() silently returns
    rp = RacePlanner("/nonexistent")
    assert rp.meta == {}


def test_import_events():
    from career_bot.events import EventManager
    # Constructor doesn't fail on bad dir — _load() silently returns
    em = EventManager("/nonexistent")
    assert em.outcomes == {}


def test_import_affinity():
    import career_bot.affinity
    assert callable(career_bot.affinity.card_to_chara_id)
    assert career_bot.affinity.card_to_chara_id(100701) == 1007


def test_import_master_data():
    import career_bot.master_data
    result = career_bot.master_data.status("/tmp")
    assert isinstance(result, dict)


def test_import_runner():
    pytest.importorskip("msgpack")
    from career_bot.runner import CareerRunner, runtime_output_root
    assert callable(runtime_output_root)


def test_import_skills():
    from career_bot.skills import SkillBuyer
    # Constructor doesn't fail on bad dir — data files are loaded on demand
    sb = SkillBuyer("/nonexistent")
    assert sb.skill_names == {}


def test_import_items():
    from career_bot.items import MantItemManager, ITEM_NAMES
    mgr = MantItemManager()
    assert isinstance(ITEM_NAMES, dict)
    assert mgr.current_turn is None


# ── Modules needing optional deps (msgpack, frida) ─────────────────────

def _has_dep(name):
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def test_import_client():
    pytest.importorskip("msgpack")
    from uma_api.client import UmaClient, runtime_output_root, get_hwid
    assert callable(runtime_output_root)
    hwid = get_hwid("test_seed")
    assert isinstance(hwid, dict)
    assert "udid" in hwid


def test_import_capture_dailies():
    pytest.importorskip("frida")
    from capture_dailies import unpack_request, JS_CAPTURE
    assert isinstance(JS_CAPTURE, str)
    assert len(JS_CAPTURE) > 100


@pytest.mark.skip(reason="Requires master.mdb on disk")
def test_master_data_generate(tmp_path):
    import career_bot.master_data
    result = career_bot.master_data.status(tmp_path)
    assert result.get("exists") is False
