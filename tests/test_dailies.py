import base64
import gzip
import struct

from career_bot.dailies import (
    DAILY_RACE_CAP,
    TEAM_TRIAL_CAP,
    DailiesRunner,
    _fmt_get_list_time,
    best_running_style,
    parse_race_result_array,
)


def synthetic_race_scenario():
    horse_result_size = 64
    blob = bytearray()
    blob += struct.pack("<i", 0)
    blob += struct.pack("<fiii", 0.0, 3, 0, horse_result_size)
    blob += struct.pack("<i", 0)
    blob += struct.pack("<ii", 0, 0)
    blob += struct.pack("<i", 0)
    for finish_order, finish_time, finish_time_raw in (
        (2, 12.3456, 12.5000),
        (0, 10.1111, 10.2500),
        (1, 11.2222, 11.5000),
    ):
        row = bytearray(horse_result_size)
        struct.pack_into("<i", row, 0, finish_order)
        struct.pack_into("<f", row, 4, finish_time)
        struct.pack_into("<f", row, 27, finish_time_raw)
        blob += row
    horses = [
        {"frame_order": 1, "viewer_id": 101},
        {"frame_order": 2, "viewer_id": 202},
        {"frame_order": 3, "viewer_id": 303},
    ]
    encoded = base64.b64encode(gzip.compress(bytes(blob))).decode("ascii")
    return encoded, horses


def test_dailies_helpers_match_icarus_42_behavior():
    assert TEAM_TRIAL_CAP == 8
    assert DAILY_RACE_CAP == 3
    assert best_running_style({}) == 1
    assert best_running_style(
        {
            "proper_running_style_nige": 1,
            "proper_running_style_senko": 2,
            "proper_running_style_sashi": 4,
            "proper_running_style_oikomi": 7,
        }
    ) == 4
    assert _fmt_get_list_time(0) == "1970/01/01 0:00:00"
    assert _fmt_get_list_time(1783958400) == "2026/07/13 16:00:00"


def test_parse_race_result_array_matches_icarus_42_binary_layout():
    scenario, horses = synthetic_race_scenario()

    assert parse_race_result_array(scenario, horses) == [
        {
            "viewer_id": 101,
            "finish_order": 3,
            "finish_time": 123456,
            "finish_time_raw": 125000,
            "bashin_diff_from_behind": 0,
        },
        {
            "viewer_id": 202,
            "finish_order": 1,
            "finish_time": 101111,
            "finish_time_raw": 102500,
            "bashin_diff_from_behind": 88500,
        },
        {
            "viewer_id": 303,
            "finish_order": 2,
            "finish_time": 112222,
            "finish_time_raw": 115000,
            "bashin_diff_from_behind": 70800,
        },
    ]


class TeamTrialsClient:
    def __init__(self):
        self.selected = []
        self.replay_rounds = []
        self.ends = 0

    def team_stadium_index(self):
        return {"data": {"rp_info": {"current_rp": 2}}}

    def team_stadium_opponent_list(self):
        return {
            "data": {
                "opponent_info_array": [
                    {"strength": 1, "marker": "strong"},
                    {"strength": 2, "marker": "middle"},
                    {"strength": 3, "marker": "weak"},
                ]
            }
        }

    def team_stadium_decide_frame_order(self, opponent):
        self.selected.append(opponent["marker"])
        return {"data": {}}

    def team_stadium_start(self, item_id_array=None):
        assert item_id_array == []
        return {"data": {}}

    def team_stadium_replay_check(self, round=5):
        self.replay_rounds.append(round)
        return {"data": {}}

    def team_stadium_all_race_end(self):
        self.ends += 1
        return {
            "data": {
                "result": {
                    "rp_info": {"current_rp": max(0, 2 - self.ends)},
                    "final_win_type": self.ends,
                    "ranking_rank": 10 + self.ends,
                }
            }
        }


def test_team_trials_selects_requested_strength_and_stops_when_rp_is_zero(tmp_path):
    runner = DailiesRunner(tmp_path)
    client = TeamTrialsClient()

    result = runner._team_trials(client, 2)

    assert result == {"races": 2}
    assert client.selected == ["middle", "middle"]
    assert client.replay_rounds == [5, 5]


class RaceClient:
    def __init__(self, scenario):
        self.scenario = scenario
        self.daily_entries = []
        self.legend_entries = []
        self.replay_arrays = []

    def trained_chara_load(self):
        return {
            "data": {
                "trained_chara_array": [
                    {
                        "trained_chara_id": 900001,
                        "proper_running_style_nige": 1,
                        "proper_running_style_senko": 2,
                        "proper_running_style_sashi": 4,
                        "proper_running_style_oikomi": 7,
                    }
                ]
            }
        }

    def daily_race_index(self):
        return {"data": {"daily_race_record_array": [{"daily_race_id": 12001}]}}

    def daily_race_race_entry(self, race_id, trained_chara_id):
        self.daily_entries.append((race_id, trained_chara_id))
        return {
            "data": {
                "race_horse_data_array": [
                    {"frame_order": 1, "viewer_id": 101},
                    {"frame_order": 2, "viewer_id": 202},
                    {"frame_order": 3, "viewer_id": 303},
                ]
            }
        }

    def daily_race_reflect_item_effect(self, item_id_array=None):
        assert item_id_array == []
        return {"data": {}}

    def daily_race_race_start(self, running_style, is_short=0):
        assert running_style == 4
        assert is_short == 0
        return {"data": {"race_scenario": self.scenario}}

    def daily_race_replay_check(self, race_result_array):
        self.replay_arrays.append(race_result_array)
        return {"data": {"rank": 1}}

    def daily_legend_race_race_entry(self, race_id, trained_chara_id):
        self.legend_entries.append((race_id, trained_chara_id))
        return {"data": {}}

    def daily_legend_race_reflect_item_effect(self, item_id_array=None):
        assert item_id_array == []
        return {"data": {}}

    def daily_legend_race_race_start(self, running_style, is_short=0):
        assert running_style == 4
        return {"data": {}}

    def daily_legend_race_replay_check(self):
        return {"data": {"rank": 2}}


def test_daily_races_run_to_cap_and_legend_runs_selected_boss_once(tmp_path):
    scenario, _ = synthetic_race_scenario()
    runner = DailiesRunner(tmp_path)
    client = RaceClient(scenario)

    daily = runner._daily_races(client, 900001)
    legend = runner._legend_races(client, 900001, 15021)

    assert daily == {
        "completed": [
            {"id": 12001, "rank": 1},
            {"id": 12001, "rank": 1},
            {"id": 12001, "rank": 1},
        ]
    }
    assert client.daily_entries == [(12001, 900001)] * 3
    assert len(client.replay_arrays) == 3
    assert legend == {"completed": [{"id": 15021, "rank": 2}]}
    assert client.legend_entries == [(15021, 900001)]


class ShopClient:
    def __init__(self):
        self.item_map = {59: 250, 75: 9999}
        self.purchase = None

    def item_show_exchange(self):
        return {
            "data_headers": {"servertime": 1783958400},
            "data": {
                "disabled_id_array": [],
                "limited_goods_info_array": [
                    {"reward_id": 501, "exchange_count": 0, "open_count": 2},
                    {"reward_id": 502, "exchange_count": 0, "open_count": 3},
                    {"reward_id": 503, "exchange_count": 0, "open_count": 1},
                ],
            },
        }

    def item_exchange_multi(self, exchange_items, balances, get_list_time):
        self.purchase = (exchange_items, balances, get_list_time)
        return {"data": {"reward_summary_info": {"add_item_list": [{"item_id": 91}]}}}


def test_daily_shop_skips_goods_already_exchanged(tmp_path):
    runner = DailiesRunner(tmp_path)
    runner._load_shop_catalog = lambda: (
        {501: 7001, 502: 7002},
        {
            7001: {
                "pay_item": 59,
                "pay_num": 100,
                "limit": 1,
                "reward_item": 91,
                "reward_num": 1,
            },
            7002: {
                "pay_item": 59,
                "pay_num": 50,
                "limit": 1,
                "reward_item": 92,
                "reward_num": 1,
            },
        },
    )

    class PartiallyClearedShopClient:
        def __init__(self):
            self.item_map = {59: 250}
            self.purchase = None

        def item_show_exchange(self):
            return {
                "data_headers": {"servertime": 1783958400},
                "data": {
                    "disabled_id_array": [],
                    "limited_goods_info_array": [
                        {"reward_id": 501, "exchange_count": 1, "open_count": 1},
                        {"reward_id": 502, "exchange_count": 0, "open_count": 1},
                    ],
                },
            }

        def item_exchange_multi(self, exchange_items, balances, get_list_time):
            self.purchase = exchange_items
            return {"data": {"reward_summary_info": {"add_item_list": []}}}

    client = PartiallyClearedShopClient()

    result = runner._daily_shop(client)

    assert result["bought"] == [7002]
    assert client.purchase == [
        {"exchange_id": 7002, "count": 1, "ex_param": {"open_count": 1}}
    ]


def test_daily_shop_keeps_same_exchange_id_for_each_open_count(tmp_path):
    runner = DailiesRunner(tmp_path)
    runner._load_shop_catalog = lambda: (
        {117: 10220, 118: 10221},
        {
            10220: {
                "pay_item": 59,
                "pay_num": 2000,
                "limit": 1,
                "reward_item": 95,
                "reward_num": 1,
            },
            10221: {
                "pay_item": 59,
                "pay_num": 5000,
                "limit": 1,
                "reward_item": 116,
                "reward_num": 1,
            },
        },
    )

    class MultiOpenCountClient:
        def __init__(self):
            self.item_map = {59: 999999}
            self.purchase = None

        def item_show_exchange(self):
            return {
                "data_headers": {"servertime": 1783961044},
                "data": {
                    "disabled_id_array": [],
                    "limited_goods_info_array": [
                        {"open_count": 1, "reward_id": 117, "exchange_count": 0, "disp_order": 3},
                        {"open_count": 1, "reward_id": 118, "exchange_count": 0, "disp_order": 4},
                        {"open_count": 2, "reward_id": 117, "exchange_count": 0, "disp_order": 3},
                        {"open_count": 2, "reward_id": 118, "exchange_count": 0, "disp_order": 4},
                        {"open_count": 3, "reward_id": 117, "exchange_count": 0, "disp_order": 3},
                        {"open_count": 3, "reward_id": 118, "exchange_count": 0, "disp_order": 4},
                    ],
                },
            }

        def item_exchange_multi(self, exchange_items, balances, get_list_time):
            self.purchase = exchange_items
            return {"data": {"reward_summary_info": {"add_item_list": []}}}

    client = MultiOpenCountClient()

    result = runner._daily_shop(client)

    assert result["bought"] == [10220, 10220, 10220, 10221, 10221, 10221]
    assert client.purchase == [
        {"exchange_id": 10220, "count": 1, "ex_param": {"open_count": 3}},
        {"exchange_id": 10220, "count": 1, "ex_param": {"open_count": 2}},
        {"exchange_id": 10220, "count": 1, "ex_param": {"open_count": 1}},
        {"exchange_id": 10221, "count": 1, "ex_param": {"open_count": 3}},
        {"exchange_id": 10221, "count": 1, "ex_param": {"open_count": 2}},
        {"exchange_id": 10221, "count": 1, "ex_param": {"open_count": 1}},
    ]


def test_daily_shop_buys_only_gold_goods_cheapest_first_within_balance(tmp_path):
    runner = DailiesRunner(tmp_path)
    runner._load_shop_catalog = lambda: (
        {501: 7001, 502: 7002, 503: 7003},
        {
            7001: {
                "pay_item": 59,
                "pay_num": 100,
                "limit": 1,
                "reward_item": 91,
                "reward_num": 1,
            },
            7002: {
                "pay_item": 59,
                "pay_num": 50,
                "limit": 1,
                "reward_item": 92,
                "reward_num": 1,
            },
            7003: {
                "pay_item": 75,
                "pay_num": 1,
                "limit": 1,
                "reward_item": 93,
                "reward_num": 1,
            },
        },
    )
    client = ShopClient()

    result = runner._daily_shop(client)

    assert result == {"bought": [7002, 7001], "spend": {59: 150}, "rewards": 1}
    assert client.purchase == (
        [
            {"exchange_id": 7002, "count": 1, "ex_param": {"open_count": 3}},
            {"exchange_id": 7001, "count": 1, "ex_param": {"open_count": 2}},
        ],
        [{"item_id": 59, "number": 250}],
        "2026/07/13 16:00:00",
    )
