from uma_api.client import UmaClient


def make_client():
    client = UmaClient.__new__(UmaClient)
    calls = []

    def fake_call(endpoint, payload=None, *args, **kwargs):
        calls.append((endpoint, payload, args, kwargs))
        return {"endpoint": endpoint, "payload": payload}

    client.call = fake_call
    return client, calls


def assert_one_call(calls, endpoint, payload):
    assert calls == [(endpoint, payload, (), {})]


def test_team_stadium_wrappers_match_icarus_42_contract():
    client, calls = make_client()

    client.team_stadium_index()
    assert_one_call(calls, "team_stadium/index", None)

    calls.clear()
    client.team_stadium_opponent_list()
    assert_one_call(calls, "team_stadium/opponent_list", None)

    calls.clear()
    opponent = {"strength": 2, "opponent_viewer_id": 123}
    client.team_stadium_decide_frame_order(opponent)
    assert_one_call(
        calls,
        "team_stadium/decide_frame_order",
        {"opponent_info": opponent},
    )

    calls.clear()
    client.team_stadium_start()
    assert_one_call(calls, "team_stadium/start", {"item_id_array": []})

    calls.clear()
    client.team_stadium_replay_check()
    assert_one_call(calls, "team_stadium/replay_check", {"round": 5})

    calls.clear()
    client.team_stadium_all_race_end()
    assert_one_call(calls, "team_stadium/all_race_end", None)


def test_daily_race_wrappers_match_icarus_42_contract():
    client, calls = make_client()

    client.trained_chara_load()
    assert_one_call(calls, "trained_chara/load", None)

    calls.clear()
    client.daily_race_index()
    assert_one_call(calls, "daily_race/index", None)

    calls.clear()
    client.daily_race_race_entry(12003, 900001)
    assert_one_call(
        calls,
        "daily_race/race_entry",
        {"daily_race_id": 12003, "trained_chara_id": 900001},
    )

    calls.clear()
    client.daily_race_reflect_item_effect()
    assert_one_call(calls, "daily_race/reflect_item_effect", {"item_id_array": []})

    calls.clear()
    client.daily_race_race_start(4, is_short=1)
    assert_one_call(
        calls,
        "daily_race/race_start",
        {"running_style": 4, "is_short": 1},
    )

    calls.clear()
    result_array = [{"viewer_id": 1, "finish_order": 1}]
    client.daily_race_replay_check(result_array)
    assert_one_call(
        calls,
        "daily_race/replay_check",
        {"race_result_array": result_array},
    )


def test_daily_legend_and_shop_wrappers_match_icarus_42_contract():
    client, calls = make_client()

    client.daily_legend_race_index()
    assert_one_call(calls, "daily_legend_race/index", None)

    calls.clear()
    client.daily_legend_race_race_entry(15021, 900001)
    assert_one_call(
        calls,
        "daily_legend_race/race_entry",
        {"daily_legend_race_id": 15021, "trained_chara_id": 900001},
    )

    calls.clear()
    client.daily_legend_race_reflect_item_effect([41])
    assert_one_call(
        calls,
        "daily_legend_race/reflect_item_effect",
        {"item_id_array": [41]},
    )

    calls.clear()
    client.daily_legend_race_race_start(3)
    assert_one_call(
        calls,
        "daily_legend_race/race_start",
        {"running_style": 3, "is_short": 0},
    )

    calls.clear()
    client.daily_legend_race_replay_check()
    assert_one_call(calls, "daily_legend_race/replay_check", {})

    calls.clear()
    client.item_show_exchange()
    assert_one_call(calls, "item/show_exchange", None)

    calls.clear()
    exchange = [{"exchange_id": 7001, "count": 1, "ex_param": {"open_count": 2}}]
    balances = [{"item_id": 59, "number": 1000}]
    client.item_exchange_multi(exchange, balances, "2026/07/13 16:00:00")
    assert_one_call(
        calls,
        "item/exchange_multi",
        {
            "exchange_item_info_array": exchange,
            "use_item_info_array": balances,
            "get_list_time": "2026/07/13 16:00:00",
        },
    )
