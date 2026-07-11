import pytest

from career_bot.skills import SkillBuyer
from uma_api.client import StateRecoveryError


class Client:
    def __init__(self):
        self.payload = None

    def gain_skills(self, payload, turn):
        self.payload = payload
        return {"data": {}}


def test_gold_skill_payload_includes_bundled_ids_first():
    buyer = SkillBuyer("/nonexistent")
    client = Client()
    state = {
        "data": {
            "chara_info": {
                "turn": 47,
                "skill_point": 312,
                "skill_tips_array": [{"group_id": 20035}],
            }
        }
    }
    buyer.group_to_skill_ids = {20035: [200351, 200352]}

    state, bought = buyer._buy_batch(client, state, [{
        "skill_id": 200351,
        "cost": 283,
        "bundled_skill_ids": [200352],
    }], 47)

    assert bought == 1
    assert client.payload == [{"skill_id": 200352, "level": 1}, {"skill_id": 200351, "level": 1}]


def test_circle_skill_uses_master_cost_for_affordability():
    buyer = SkillBuyer("/nonexistent")
    buyer.skill_names = {200352: "Corner Recovery ○"}
    buyer.skill_costs = {200352: 170}
    buyer.skill_rarities = {200352: 1}
    buyer.skill_grade_values = {200352: 217}
    buyer.skill_id_exists = {200352}
    buyer.group_to_skill_ids = {20035: [200352]}
    buyer.skill_to_group_id = {200352: 20035}
    state = {
        "data": {
            "chara_info": {
                "turn": 78,
                "skill_point": 102,
                "skill_tips_array": [{"group_id": 20035, "rarity": 1, "level": 3}],
            }
        }
    }

    state, bought = buyer.buy(Client(), state, {"learn_skill_threshold": 1})

    assert bought == 0
    assert buyer.last_result == {"skip": "not_enough_points", "points": 102}


def test_buy_batch_allows_disable_singlemode_skill():
    buyer = SkillBuyer("/nonexistent")
    buyer.skill_costs = {210061: 200}
    buyer.skill_disabled_singlemode = {210061}
    buyer.group_to_skill_ids = {21006: [210061]}
    client = Client()
    state = {
        "data": {
            "chara_info": {
                "turn": 78,
                "skill_point": 621,
                "skill_tips_array": [{"group_id": 21006}],
            }
        }
    }

    state, bought = buyer._buy_batch(client, state, [{"skill_id": 210061, "cost": 200}], 78)

    assert bought == 1
    assert client.payload == [{"skill_id": 210061, "level": 1}]


def test_buy_batch_reraises_state_recovery_error():
    class FailingClient:
        def gain_skills(self, payload, turn):
            raise StateRecoveryError("API error 501 on tool/start_session: session fully invalidated")

    buyer = SkillBuyer("/nonexistent")
    buyer.group_to_skill_ids = {20035: [200351]}
    state = {
        "data": {
            "chara_info": {
                "turn": 47,
                "skill_point": 312,
                "skill_tips_array": [{"group_id": 20035}],
            }
        }
    }

    with pytest.raises(StateRecoveryError):
        buyer._buy_batch(FailingClient(), state, [{"skill_id": 200351, "cost": 100}], 47)


def test_skips_lower_tier_when_higher_owned():
    """Owning Pace Chaser Savvy ◎ must not try to buy ○ (server 205)."""
    buyer = SkillBuyer("/nonexistent")
    buyer.skill_names = {
        201531: "Pace Chaser Savvy ◎",
        201532: "Pace Chaser Savvy ○",
    }
    buyer.skill_costs = {201531: 130, 201532: 110}
    buyer.skill_rarities = {201531: 1, 201532: 1}
    buyer.skill_grade_values = {201531: 217, 201532: 174}
    buyer.skill_id_exists = {201531, 201532}
    buyer.group_to_skill_ids = {20153: [201532, 201531]}
    buyer.skill_to_group_id = {201531: 20153, 201532: 20153}

    assert buyer._resolve_buyable_tier(20153, 1, {201531}) == 0
    assert buyer._resolve_buyable_tier(20153, 1, set()) == 201532
    assert buyer._resolve_buyable_tier(20153, 1, {201532}) == 201531

    state = {
        "data": {
            "chara_info": {
                "turn": 78,
                "skill_point": 621,
                "skill_array": [{"skill_id": 201531, "level": 1}],
                "skill_tips_array": [{"group_id": 20153, "rarity": 1, "level": 1}],
            }
        }
    }
    state, bought = buyer.buy(Client(), state, {"learn_skill_threshold": 1})
    assert bought == 0
    assert buyer.last_result.get("skip") in {"no_candidates", "not_enough_points"}
    assert all(c["skill_id"] != 201532 for c in buyer.last_candidates)


def test_buy_batch_skips_unaffordable_second_chunk():
    """After chunk1, only skills that fit remaining SP may be sent (was overspend 205→501)."""
    costs = {
        201532: 99, 200582: 162, 201332: 108, 200332: 117,
        200012: 81, 200062: 81, 201112: 90,
    }

    class TrackingClient:
        def __init__(self):
            self.calls = []
            self.sp = 733

        def gain_skills(self, payload, turn):
            spend = sum(costs[item["skill_id"]] for item in payload)
            assert spend <= self.sp, f"overspend {spend} > {self.sp} payload={payload}"
            self.sp -= spend
            self.calls.append([item["skill_id"] for item in payload])
            return {
                "data": {
                    "chara_info": {
                        "turn": turn,
                        "skill_point": self.sp,
                        "skill_array": [{"skill_id": sid, "level": 1} for sid in self.calls[-1]],
                        "skill_tips_array": [
                            {"group_id": 20153}, {"group_id": 20058}, {"group_id": 20133},
                            {"group_id": 20033}, {"group_id": 20001}, {"group_id": 20006},
                            {"group_id": 20111},
                        ],
                    }
                }
            }

    buyer = SkillBuyer("/nonexistent")
    buyer.group_to_skill_ids = {
        20153: [201532], 20058: [200582], 20133: [201332], 20033: [200332],
        20001: [200012], 20006: [200062], 20111: [201112],
    }
    client = TrackingClient()
    state = {
        "data": {
            "chara_info": {
                "turn": 32,
                "skill_point": 733,
                "skill_tips_array": [
                    {"group_id": 20153}, {"group_id": 20058}, {"group_id": 20133},
                    {"group_id": 20033}, {"group_id": 20001}, {"group_id": 20006},
                    {"group_id": 20111},
                ],
            }
        }
    }
    candidates = [
        {"skill_id": 201532, "cost": 99},
        {"skill_id": 200582, "cost": 162},
        {"skill_id": 201332, "cost": 108},
        {"skill_id": 200332, "cost": 117},
        # after chunk1 SP=247; 81+81+90=252 would 205 — only 81+81 fit
        {"skill_id": 200012, "cost": 81},
        {"skill_id": 200062, "cost": 81},
        {"skill_id": 201112, "cost": 90},
    ]

    state, bought = buyer._buy_batch(client, state, candidates, 32)

    assert client.calls[0] == [201532, 200582, 201332, 200332]
    assert 201112 not in {sid for call in client.calls for sid in call}
    assert all(sum(costs[s] for s in call) <= 733 for call in client.calls)
    assert bought == 6  # 4 + two 81-cost; 90 left unaffordable
    assert client.sp == 733 - (99 + 162 + 108 + 117 + 81 + 81)
    assert int((state.get("data") or {}).get("chara_info", {}).get("skill_point") or 0) == client.sp


def test_rebuy_owned_red_to_clear_debuff():
    """Own Firm Conditions × → re-buy 200153 alone to clear debuff."""
    buyer = SkillBuyer("/nonexistent")
    buyer.skill_names = {
        200151: "Firm Conditions ◎",
        200152: "Firm Conditions ○",
        200153: "Firm Conditions ×",
        201902: "Head-On",
    }
    buyer.skill_costs = {200151: 110, 200152: 90, 200153: 50, 201902: 180}
    buyer.skill_rarities = {200151: 1, 200152: 1, 200153: 1, 201902: 1}
    buyer.skill_grade_values = {200151: 174, 200152: 129, 200153: -129, 201902: 217}
    buyer.skill_id_exists = {200151, 200152, 200153, 201902}
    buyer.skill_disabled_singlemode = {200153}
    buyer.group_to_skill_ids = {20015: [200152, 200151, 200153], 20190: [201902]}
    buyer.skill_to_group_id = {
        200151: 20015, 200152: 20015, 200153: 20015, 201902: 20190,
    }

    assert buyer._resolve_buyable_tier(20015, 1, {200153}) == 0
    assert buyer._resolve_buyable_tier(20015, 1, set()) == 200152

    client = Client()
    state = {
        "data": {
            "chara_info": {
                "turn": 78,
                "skill_point": 621,
                "skill_array": [{"skill_id": 200153, "level": 1}],
                "skill_tips_array": [
                    {"group_id": 20015, "rarity": 1, "level": 1},
                    {"group_id": 20190, "rarity": 1, "level": 2},
                ],
            }
        }
    }
    state, bought = buyer.buy(client, state, {"learn_skill_threshold": 1})
    assert bought == 1
    assert client.payload == [{"skill_id": 200153, "level": 1}]
    assert buyer.last_selected[0]["skill_id"] == 200153
    assert buyer.last_selected[0]["clears_red"] is True
    assert all(c["skill_id"] != 200152 for c in buyer.last_selected)
