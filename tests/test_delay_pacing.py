import random
import pytest
from career_bot import delay


# --- resolve_tp_mode ---

def test_resolve_tp_mode_wait():
    assert delay.resolve_tp_mode("wait") == "wait"
    assert delay.resolve_tp_mode("WAIT") == "wait"
    assert delay.resolve_tp_mode("  wait ") == "wait"

def test_resolve_tp_mode_carat_default():
    assert delay.resolve_tp_mode("carat") == "carat"
    assert delay.resolve_tp_mode("") == "carat"
    assert delay.resolve_tp_mode(None) == "carat"
    assert delay.resolve_tp_mode("bogus") == "carat"
    assert delay.resolve_tp_mode(123) == "carat"


# --- pick_delay_seconds ---

def test_pick_delay_zero_range_returns_fallback():
    assert delay.pick_delay_seconds(0, 0) == delay.DEFAULT_RUN_DELAY_FALLBACK_SEC

def test_pick_delay_within_range_minutes_to_seconds():
    rng = random.Random(1)
    for _ in range(100):
        v = delay.pick_delay_seconds(10, 50, rng=rng)
        assert 10 * 60 <= v <= 50 * 60

def test_pick_delay_clamps_max_below_min():
    assert delay.pick_delay_seconds(30, 10) == 30 * 60

def test_pick_delay_negative_treated_as_zero():
    assert delay.pick_delay_seconds(-5, -1) == delay.DEFAULT_RUN_DELAY_FALLBACK_SEC


# --- compute_regen_wait_seconds ---

def test_regen_wait_deficit():
    assert delay.compute_regen_wait_seconds(30, 27) == 1860

def test_regen_wait_floor_when_no_deficit():
    assert delay.compute_regen_wait_seconds(30, 30) == delay.TP_REGEN_MIN_WAIT_SEC
    assert delay.compute_regen_wait_seconds(30, 40) == delay.TP_REGEN_MIN_WAIT_SEC

def test_regen_wait_large_deficit():
    assert delay.compute_regen_wait_seconds(30, 0) == 18060


# --- decide_tp_action ---

def test_decide_ok_when_enough_tp():
    assert delay.decide_tp_action(30, 30, "wait", False) == "ok"
    assert delay.decide_tp_action(30, 45, "carat", False) == "ok"

def test_decide_ok_when_no_requirement():
    assert delay.decide_tp_action(0, 0, "wait", False) == "ok"

def test_decide_stop_takes_precedence():
    assert delay.decide_tp_action(30, 0, "wait", True) == "stop"
    assert delay.decide_tp_action(30, 0, "carat", True) == "stop"

def test_decide_wait_mode():
    assert delay.decide_tp_action(30, 0, "wait", False) == "wait"

def test_decide_carat_default():
    assert delay.decide_tp_action(30, 0, "carat", False) == "carat"
    assert delay.decide_tp_action(30, 0, "bogus", False) == "carat"
