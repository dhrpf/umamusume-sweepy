import json

from career_bot.aptitude import _factor_name_to_key, _grade_for_stars, predict_aptitude


def _cat(result, key):
    return next(c for c in result["prediction"]["categories"] if c["key"] == key)


def test_predict_aptitude_uses_base_and_self_factors_only(tmp_path):
    data_dir = tmp_path
    (data_dir / "chara_aptitude.json").write_text(json.dumps({"100": {"turf": 5, "mile": 7}}))
    parents = [
        {
            "tree": {
                "self": {"factors": [{"id": 1}, {"id": 2}]},
                "p1": {"factors": [{"id": 3}]},
            }
        }
    ]
    factor_map = {
        "1": {"category": "aptitude", "name": "Turf", "stars": 2},
        "2": {"category": "aptitude", "name": "Mile", "stars": 3},
        "3": {"category": "aptitude", "name": "Dirt", "stars": 3},
    }

    out = predict_aptitude(parents, factor_map, trainee_card_id=100, data_dir=data_dir)

    assert out["has_base"] is True
    assert _cat(out, "turf")["grade"] == "A"
    assert _cat(out, "mile")["grade"] == "S"
    assert _cat(out, "dirt")["stars"] == 0


def test_predict_aptitude_falls_back_to_star_grade_without_base():
    out = predict_aptitude(
        [{"tree": {"self": {"factors": [{"id": "x"}]}}}],
        {"x": {"category": "aptitude", "name": "Oikomi", "stars": 10}},
    )

    assert out["has_base"] is False
    assert _cat(out, "end")["grade"] == "A"


def test_factor_name_aliases_and_star_grade_thresholds():
    assert _factor_name_to_key("Pace Chaser aptitude") == "pace"
    assert _factor_name_to_key("senko") == "pace"
    assert _grade_for_stars(0) == "F"
    assert _grade_for_stars(14) == "S"
