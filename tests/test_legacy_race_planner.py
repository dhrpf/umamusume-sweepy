from career_bot.campaigns.legacy.race_planner import build_shared_g1_agenda


def race(program_id, turn, date, name):
    return {
        "id": program_id * 1000 + turn,
        "program_id": program_id,
        "turn": turn,
        "name": name,
        "date": date,
        "type": "G1",
        "terrain": "Turf",
        "distance": "Medium",
    }


def test_agenda_prefers_senior_repeat_outside_summer_camp():
    rows = [
        race(1, 37, "Classic Year Early Jul", "Race A"),
        race(1, 65, "Senior Year Early Sep", "Race A"),
        race(2, 41, "Classic Year Early Sep", "Race B"),
    ]

    result = build_shared_g1_agenda(rows)

    assert [(row["program_id"], row["turn"]) for row in result["agenda"]] == [
        (2, 41),
        (1, 65),
    ]
    assert result["skipped"] == []


def test_agenda_avoids_four_race_chain_when_alternate_exists():
    rows = [
        race(1, 20, "Classic Year Early Jan", "Race A"),
        race(2, 21, "Classic Year Late Jan", "Race B"),
        race(3, 22, "Classic Year Early Feb", "Race C"),
        race(4, 23, "Classic Year Late Feb", "Race D"),
        race(4, 70, "Senior Year Late Nov", "Race D"),
    ]

    result = build_shared_g1_agenda(rows, prefer_senior_repeats=False)

    turns = [row["turn"] for row in result["agenda"]]
    assert turns == [20, 21, 22, 70]
    assert result["maximum_consecutive_races"] == 3


def test_agenda_filters_non_g1_wrong_surface_and_wrong_distance():
    rows = [
        race(1, 20, "Classic Year Early Jan", "Valid"),
        {**race(2, 21, "Classic Year Late Jan", "G2"), "type": "G2"},
        {**race(3, 22, "Classic Year Early Feb", "Dirt"), "terrain": "Dirt"},
        {**race(4, 23, "Classic Year Late Feb", "Sprint"), "distance": "Sprint"},
    ]

    result = build_shared_g1_agenda(rows)

    assert [row["name"] for row in result["agenda"]] == ["Valid"]
