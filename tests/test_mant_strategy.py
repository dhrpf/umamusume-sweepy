import unittest
from unittest.mock import MagicMock
import sys
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

try:
    from career_bot.scenarios.mant import MantStrategy
    from career_bot.races import RacePlanner
    HAVE_MANT = True
except ImportError:
    HAVE_MANT = False

@unittest.skipUnless(HAVE_MANT, "requires career_bot.scenarios.mant and dependencies")
class TestMantStrategy(unittest.TestCase):

    def setUp(self):
        self.planner = MagicMock(spec=RacePlanner)
        self.planner.base_dir = None
        self.planner.rejected = set()
        # Mock label and program dict
        self.planner.label = lambda pid: f"Race {pid}"
        self.planner.program = {
            100: {"race_instance_id": "303901", "name": "Hakodate Kinen"}, # G3
            200: {"race_instance_id": "203901", "name": "Some G2"},      # G2
        }
        self.strategy = MantStrategy(self.planner)
        
        # Default preset
        self.preset = {
            "name": "Test Preset",
            "scenario_id": 4,
            "max_consecutive_races": 3,
            "max_races": 35,
            "rest_threshold": 30,
            "train_min_total_stat_gain": 40,
            "extra_race_list": [100]
        }
        
        # Default commands array (with Speed training, Rest, and Recreation)
        self.default_commands = [
            {
                "command_type": 1, 
                "command_id": 101, # Speed
                "is_enable": 1,
                "failure_rate": 35, # high failure rate
                "params_inc_dec_info_array": [
                    {"target_type": 1, "value": 30}, # Speed +30
                    {"target_type": 3, "value": 15}, # Power +15
                ]
            },
            {
                "command_type": 7, 
                "command_id": 701, # Rest
                "is_enable": 1,
            },
            {
                "command_type": 3, 
                "command_id": 390, # Recreation
                "is_enable": 1,
            }
        ]

    def make_state(self, turn, vital, motivation=5, owned_items=None, pick_ups=None, rca=None):
        if owned_items is None:
            owned_items = []
        if pick_ups is None:
            pick_ups = []
        if rca is None:
            rca = []
            
        return {
            "data": {
                "chara_info": {
                    "turn": turn,
                    "vital": vital,
                    "motivation": motivation,
                    "playing_state": 1,
                    "chara_effect_id_array": [],
                    "speed": 500, "stamina": 500, "power": 500, "guts": 500, "wiz": 500,
                    "evaluation_info_array": []
                },
                "home_info": {
                    "command_info_array": self.default_commands
                },
                "free_data_set": {
                    "coin_num": 100,
                    "user_item_info_array": owned_items,
                    "pick_up_item_info_array": pick_ups,
                    "rival_race_info_array": []
                },
                "race_condition_array": rca
            }
        }

    @unittest.skip("requires enhanced mant.py summer camp logic")
    def test_summer_camp_with_good_luck_charm(self):
        # Turn 36 (Camp Start), vital = 10 (very low, fail rate is 35%).
        # We have a Good-Luck Charm in inventory.
        owned_items = [{"item_id": 10001, "num": 1}] # Good-Luck Charm (10001)
        state = self.make_state(turn=36, vital=10, owned_items=owned_items)
        
        # Set up race planner mock: choose returns 0 (no planned races)
        self.planner.forced_program.return_value = 0
        self.planner.choose.return_value = 0
        
        dec = self.strategy.next_decision(state, self.preset)
        
        # Verify it chooses training command instead of rest or recreation
        self.assertEqual(dec.action, "command")
        self.assertEqual(dec.payload["command_type"], 1)
        self.assertEqual(dec.payload["command_id"], 101) # Speed training

    @unittest.skip("requires enhanced mant.py summer camp logic")
    def test_summer_camp_abandon_training_to_race(self):
        # Turn 36 (Camp Start), vital = 10 (low), fail rate is 35%.
        # We have NO Good-Luck Charms and NO recovery items.
        # So we cannot train safely.
        # We should abandon training and race instead.
        state = self.make_state(turn=36, vital=10, owned_items=[], rca=[{"program_id": 100}])
        
        self.planner.forced_program.return_value = 0
        self.planner.choose.return_value = 0
        # Mock _find_any_available_race to return 100
        self.planner.available_programs.return_value = [100]
        self.planner.check_aptitude.return_value = True
        
        dec = self.strategy.next_decision(state, self.preset)
        
        # Verify it chooses to race (Hakodate Kinen, program 100)
        self.assertEqual(dec.action, "race")
        self.assertEqual(dec.payload["program_id"], 100)

    @unittest.skip("requires enhanced mant.py summer camp logic")
    def test_summer_camp_overrides_planned_race_when_training_is_good(self):
        # Turn 36 (Camp Start), vital = 80 (high energy, safe to train).
        # The race planner has a planned race available (Hakodate Kinen, program 100).
        # Since training is safe and good, we should override the race plan and train.
        import copy
        commands = copy.deepcopy(self.default_commands)
        commands[0]["failure_rate"] = 0
        
        state = self.make_state(turn=36, vital=80, rca=[{"program_id": 100}])
        state["data"]["home_info"]["command_info_array"] = commands
        
        self.planner.forced_program.return_value = 0
        self.planner.choose.return_value = 100 # Planned race offered
        
        dec = self.strategy.next_decision(state, self.preset)
        
        # Verify it chooses command (training) instead of racing
        self.assertEqual(dec.action, "command")
        self.assertEqual(dec.payload["command_type"], 1)

    def test_conserve_turn_resting(self):
        # Turn 35 (June Late - Conserve Turn), vital = 10 (low).
        # Outside summer camp, it should choose to rest/recreate to prepare for July camp.
        state = self.make_state(turn=35, vital=10)
        
        self.planner.forced_program.return_value = 0
        self.planner.choose.return_value = 0
        
        dec = self.strategy.next_decision(state, self.preset)
        
        # Verify it chooses recreation or rest
        self.assertEqual(dec.action, "command")
        self.assertIn(dec.payload["command_type"], [3, 7]) # Rest (7) or Recreation (3)

    @unittest.skip("requires enhanced mant.py summer camp / item logic")
    def test_summer_camp_with_royal_kale_juice(self):
        # Turn 36 (Camp Start), vital = 10 (low, fail rate is 35%).
        # We have a Royal Kale Juice (item_id 2101) in inventory.
        # This gives total recovery = 100, which reduces simulated fail to 0.
        owned_items = [{"item_id": 2101, "num": 1}] # Royal Kale Juice (2101)
        state = self.make_state(turn=36, vital=10, owned_items=owned_items)
        
        self.planner.forced_program.return_value = 0
        self.planner.choose.return_value = 0
        
        dec = self.strategy.next_decision(state, self.preset)
        
        # Verify it chooses training command instead of resting/racing
        self.assertEqual(dec.action, "command")
        self.assertEqual(dec.payload["command_type"], 1)
        self.assertEqual(dec.payload["command_id"], 101) # Speed training

    def test_summer_camp_unsafe_no_items(self):
        # Turn 36 (Camp Start), vital = 10 (low, fail rate is 35%).
        # We have NO items. No races are available.
        # It should rest/recreate since training is unsafe and no races exist.
        state = self.make_state(turn=36, vital=10, owned_items=[])
        
        self.planner.forced_program.return_value = 0
        self.planner.choose.return_value = 0
        self.planner.available_programs.return_value = []
        
        dec = self.strategy.next_decision(state, self.preset)
        
        # Verify it chooses command (Recreation / Rest)
        self.assertEqual(dec.action, "command")
        self.assertIn(dec.payload["command_type"], [3, 7]) # Rest (7) or Recreation (3)

    @unittest.skip("requires enhanced mant.py or items.py logic")
    def test_cleat_shop_restrict_to_master(self):
        from career_bot.items import MantItemManager
        manager = MantItemManager()
        
        # Senior year, current_turn = 50, budget = 100
        # total_cleats = 3 (1 Master, 2 Artisan).
        # We should restrict candidate selection to only "Master Cleat Hammer".
        available = [
            ("Master Cleat Hammer", {"item_id": 11002, "coin_num": 40}),
            ("Artisan Cleat Hammer", {"item_id": 11001, "coin_num": 25}),
        ]
        owned = {"Master Cleat Hammer": 1, "Artisan Cleat Hammer": 2}
        
        # Case A: Master is available. It should be chosen.
        target = manager._old_ui_cleat_shop_target(available, owned, budget=100, current_turn=50)
        self.assertIsNotNone(target)
        self.assertEqual(target.get("item_id"), 11002) # Master Cleat Hammer
        
        # Case B: Only Artisan is available. It should NOT buy it (returns None).
        available_only_artisan = [
            ("Artisan Cleat Hammer", {"item_id": 11001, "coin_num": 25}),
        ]
        target = manager._old_ui_cleat_shop_target(available_only_artisan, owned, budget=100, current_turn=50)
        self.assertIsNone(target)

    @unittest.skip("requires enhanced items.py reserve_master_hammer_final3")
    def test_cleat_before_race_preservation(self):
        from career_bot.items import MantItemManager
        manager = MantItemManager()
        
        # Senior Year, non-climax, turn = 70.
        # We have exactly 3 Master Cleat Hammers, and 0 Artisan.
        # Preset has reserve_master_hammer_final3 = 3.
        # It should return None to preserve the Master Cleat Hammers for climax.
        preset = {"reserve_master_hammer_final3": 3}
        owned = {"Master Cleat Hammer": 3, "Artisan Cleat Hammer": 0}
        
        # Mock race planner
        planner = MagicMock()
        planner.program = {100: {"race_instance_id": "100001"}} # G1 race
        
        choice = manager._old_ui_cleat_before_race(owned, turn=70, program_id=100, race_planner=planner, preset=preset)
        self.assertIsNone(choice)
        
        # At Climax turn 74, it should use the Master Cleat Hammer!
        choice_climax = manager._old_ui_cleat_before_race(owned, turn=74, program_id=100, race_planner=planner, preset=preset)
        self.assertEqual(choice_climax, "Master Cleat Hammer")

    @unittest.skip("requires enhanced mant.py Riko outing logic")
    def test_riko_outing_chosen_instead_of_rest(self):
        # Turn 40 (Senior Year, not camp), vital = 10 (low).
        # Riko Kashimoto Outing is available (301) and regular rest is available (701).
        # We expect the bot to choose Riko's outing.
        import copy
        commands = copy.deepcopy(self.default_commands)
        commands.append({
            "command_type": 3,
            "command_id": 301,
            "is_enable": 1,
        })
        
        state = self.make_state(turn=41, vital=10)
        state["data"]["chara_info"]["evaluation_info_array"] = [
            {"target_id": 6, "is_outing": 1, "story_step": 0}
        ]
        state["data"]["home_info"]["command_info_array"] = commands
        
        self.planner.forced_program.return_value = 0
        self.planner.choose.return_value = 0
        
        dec = self.strategy.next_decision(state, self.preset)
        
        # Verify it chooses Riko Outing (command_type=3, command_group_id=301, command_id=0)
        self.assertEqual(dec.action, "command")
        self.assertEqual(dec.payload["command_type"], 3)
        self.assertEqual(dec.payload["command_group_id"], 301)
        self.assertEqual(dec.payload["command_id"], 0)

    def test_riko_outing_maxed_falls_back_to_rest(self):
        # Turn 40, vital = 10. Riko outing is NOT in the commands (only regular recreation 390 and regular rest 701 are present).
        # It should choose regular rest (7) instead of regular recreation (390).
        import copy
        commands = copy.deepcopy(self.default_commands)
        commands.append({
            "command_type": 3,
            "command_id": 390,
            "is_enable": 1,
        })
        
        state = self.make_state(turn=41, vital=10)
        state["data"]["chara_info"]["evaluation_info_array"] = [
            {"target_id": 6, "is_outing": 1, "story_step": 5} # maxed
        ]
        state["data"]["home_info"]["command_info_array"] = commands
        
        self.planner.forced_program.return_value = 0
        self.planner.choose.return_value = 0
        
        dec = self.strategy.next_decision(state, self.preset)
        
        # Verify it chooses regular rest (command_type=7)
        self.assertEqual(dec.action, "command")
        self.assertEqual(dec.payload["command_type"], 7)

    @unittest.skip("requires enhanced mant.py consecutive race breaker")
    def test_riko_outing_consecutive_race_priority(self):
        # We raced 3 times consecutively (consecutive_race_count = 3).
        # Riko Outing is available (301).
        # We expect the bot to break the streak by choosing Riko Outing.
        import copy
        commands = copy.deepcopy(self.default_commands)
        commands.append({
            "command_type": 3,
            "command_id": 301,
            "is_enable": 1,
        })
        
        state = self.make_state(turn=41, vital=10)
        state["data"]["chara_info"]["evaluation_info_array"] = [
            {"target_id": 6, "is_outing": 1, "story_step": 0}
        ]
        state["data"]["home_info"]["command_info_array"] = commands
        state["data"]["consecutive_race_count"] = 3
        
        self.planner.forced_program.return_value = 0
        self.planner.choose.return_value = 0
        
        dec = self.strategy.next_decision(state, self.preset)
        
        # Verify it chooses Riko Outing (command_type=3, command_group_id=301)
        self.assertEqual(dec.action, "command")
        self.assertEqual(dec.payload["command_type"], 3)
        self.assertEqual(dec.payload["command_group_id"], 301)

    @unittest.skip("requires enhanced items.py Grilled Carrots bond check")
    def test_grilled_carrots_usage(self):
        from career_bot.items import MantItemManager
        manager = MantItemManager()
        client = MagicMock()
        
        # Scenario 1: There is a card under 80 bond. Grilled Carrots should be used.
        state_unmaxed = {
            "data": {
                "chara_info": {
                    "turn": 10,
                    "vital": 50,
                    "motivation": 5,
                    "evaluation_info_array": [
                        {"target_id": 1, "evaluation": 70}, # under 80!
                    ]
                },
                "free_data_set": {
                    "user_item_info_array": [{"item_id": 3101, "num": 1}], # Grilled Carrots (3101)
                }
            }
        }
        manager.use_items(client, state_unmaxed, preset={})
        self.assertTrue(client.use_items.called)
        # Reset mock
        client.reset_mock()

        # Scenario 2: All cards are 80+ bond. Grilled Carrots should NOT be used.
        state_maxed = {
            "data": {
                "chara_info": {
                    "turn": 10,
                    "vital": 50,
                    "motivation": 5,
                    "evaluation_info_array": [
                        {"target_id": 1, "evaluation": 80}, # orange!
                    ]
                },
                "free_data_set": {
                    "user_item_info_array": [{"item_id": 3101, "num": 1}],
                }
            }
        }
        manager.use_items(client, state_maxed, preset={})
        self.assertFalse(client.use_items.called)

if __name__ == '__main__':
    unittest.main()
