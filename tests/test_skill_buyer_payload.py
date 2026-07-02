from career_bot.skills import SkillBuyer


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
