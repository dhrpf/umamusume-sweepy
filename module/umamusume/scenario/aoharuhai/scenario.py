import cv2
import numpy as np

from module.umamusume.scenario.ura_scenario import URAScenario
from module.umamusume.scenario.registry import register
from module.umamusume.asset import *
from module.umamusume.define import ScenarioType, SupportCardFavorLevel, SupportCardType
from module.umamusume.types import SupportCardInfo
from bot.recog.image_matcher import image_match, compare_color_equal
from module.umamusume.asset.template import (
    REF_SUPPORT_CARD_TYPE_SPEED, REF_SUPPORT_CARD_TYPE_STAMINA,
    REF_SUPPORT_CARD_TYPE_POWER, REF_SUPPORT_CARD_TYPE_WILL,
    REF_SUPPORT_CARD_TYPE_INTELLIGENCE, REF_SUPPORT_CARD_TYPE_FRIEND,
)
from bot.recog.training_stat_scanner import parse_training_result_template
from .handlers import get_aoharuhai_ui_handlers
from .hooks import aoharuhai_after_hook
from .scoring import compute_aoharu_bonuses

import bot.base.log as logger
log = logger.get_logger(__name__)

STAT_AREAS_AOHARUHAI = {
    "speed": (31, 798, 132, 831),
    "stamina": (114, 798, 246, 831),
    "power": (256, 798, 359, 831),
    "guts": (369, 798, 471, 831),
    "wits": (482, 798, 585, 831),
    "sp": (595, 798, 698, 831),
}

CARD_TYPE_MAP = (
    (REF_SUPPORT_CARD_TYPE_SPEED, SupportCardType.SUPPORT_CARD_TYPE_SPEED),
    (REF_SUPPORT_CARD_TYPE_STAMINA, SupportCardType.SUPPORT_CARD_TYPE_STAMINA),
    (REF_SUPPORT_CARD_TYPE_POWER, SupportCardType.SUPPORT_CARD_TYPE_POWER),
    (REF_SUPPORT_CARD_TYPE_WILL, SupportCardType.SUPPORT_CARD_TYPE_WILL),
    (REF_SUPPORT_CARD_TYPE_INTELLIGENCE, SupportCardType.SUPPORT_CARD_TYPE_INTELLIGENCE),
    (REF_SUPPORT_CARD_TYPE_FRIEND, SupportCardType.SUPPORT_CARD_TYPE_FRIEND),
)

CARD_TYPE_NAMES = {
    SupportCardType.SUPPORT_CARD_TYPE_SPEED: "support_card_type_speed",
    SupportCardType.SUPPORT_CARD_TYPE_STAMINA: "support_card_type_stamina",
    SupportCardType.SUPPORT_CARD_TYPE_POWER: "support_card_type_power",
    SupportCardType.SUPPORT_CARD_TYPE_WILL: "support_card_type_will",
    SupportCardType.SUPPORT_CARD_TYPE_INTELLIGENCE: "support_card_type_intelligence",
    SupportCardType.SUPPORT_CARD_TYPE_FRIEND: "support_card_type_friend",
}

ORANGE_LO = np.array([5, 60, 80], dtype=np.uint8)
ORANGE_HI = np.array([25, 255, 255], dtype=np.uint8)
ORANGE_STRICT_LO = np.array([5, 150, 150], dtype=np.uint8)
ORANGE_STRICT_HI = np.array([25, 255, 255], dtype=np.uint8)
TEAL_LO = np.array([75, 60, 80], dtype=np.uint8)
TEAL_HI = np.array([110, 255, 255], dtype=np.uint8)
TEAL_STRICT_LO = np.array([80, 170, 170], dtype=np.uint8)
TEAL_STRICT_HI = np.array([105, 255, 255], dtype=np.uint8)
MIN_STRICT_COUNT = 80
ORANGE_RATIO_THRESHOLD = 0.50
TEAL_RATIO_THRESHOLD = 0.65


@register(ScenarioType.SCENARIO_TYPE_AOHARUHAI)
class AoharuHaiScenario(URAScenario):
    def __init__(self):
        super().__init__()

    def scenario_type(self) -> ScenarioType:
        return ScenarioType.SCENARIO_TYPE_AOHARUHAI

    def scenario_name(self) -> str:
        return "青春杯"

    def get_date_img(self, img):
        return img[40:70, 160:370]

    def get_turn_to_race_img(self, img):
        return img[70:120, 30:90]

    def get_stat_areas(self) -> dict:
        return STAT_AREAS_AOHARUHAI

    def parse_training_result(self, img) -> list[int]:
        return parse_training_result_template(img, scenario="aoharuhai")

    def get_ui_handlers(self) -> dict:
        return get_aoharuhai_ui_handlers()

    def after_hook(self, ctx, img):
        return aoharuhai_after_hook(ctx, img)

    def compute_scenario_bonuses(self, ctx, idx, support_card_info_list, date, period_idx, current_energy):
        return compute_aoharu_bonuses(ctx, idx, support_card_info_list, date, period_idx, current_energy)

    def get_support_card_slot_config(self):
        return {
            'base_x': 550, 'base_y': 177, 'inc': 115,
            'width': 145, 'height': 115, 'num_slots': 5,
            'circle_cx': 92, 'circle_cy': 62, 'circle_r': 46,
        }

    def parse_training_support_card(self, img) -> list[SupportCardInfo]:
        if img is None or getattr(img, 'size', 0) == 0:
            return []
        base_x = 550
        base_y = 177
        inc = 115
        support_card_list_info_result: list[SupportCardInfo] = []

        for i in range(5):
            roi = img[base_y:base_y + inc, base_x: base_x + 145]
            if roi is None or getattr(roi, 'size', 0) == 0:
                base_y += inc
                continue

            roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            arrow_bgr = roi[0:37, 116:141]
            arrow_hsv = cv2.cvtColor(arrow_bgr, cv2.COLOR_BGR2HSV)

            ol = int(np.count_nonzero(cv2.inRange(arrow_hsv, ORANGE_LO, ORANGE_HI)))
            oh = int(np.count_nonzero(cv2.inRange(arrow_hsv, ORANGE_STRICT_LO, ORANGE_STRICT_HI)))
            can_incr_special_training = oh >= MIN_STRICT_COUNT and (oh / max(ol, 1)) >= ORANGE_RATIO_THRESHOLD

            spirit_explosion = False
            if not can_incr_special_training:
                tl = int(np.count_nonzero(cv2.inRange(arrow_hsv, TEAL_LO, TEAL_HI)))
                th = int(np.count_nonzero(cv2.inRange(arrow_hsv, TEAL_STRICT_LO, TEAL_STRICT_HI)))
                spirit_explosion = th >= MIN_STRICT_COUNT and (th / max(tl, 1)) >= TEAL_RATIO_THRESHOLD

            favor_process_check_list = [roi[106, 56], roi[106, 60]]
            support_card_favor_process = SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_UNKNOWN
            for pix in favor_process_check_list:
                if compare_color_equal(pix, [120, 235, 255]):
                    support_card_favor_process = SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_4
                elif compare_color_equal(pix, [30, 173, 255]):
                    support_card_favor_process = SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_3
                elif compare_color_equal(pix, [30, 230, 162]):
                    support_card_favor_process = SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_2
                elif (compare_color_equal(pix, [255, 192, 42]) or compare_color_equal(pix, [117, 108, 109])):
                    support_card_favor_process = SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_1
                if support_card_favor_process != SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_UNKNOWN:
                    break

            support_card_type = SupportCardType.SUPPORT_CARD_TYPE_UNKNOWN
            match_center = None
            for ref, t in CARD_TYPE_MAP:
                r = image_match(roi_gray, ref)
                if r.find_match:
                    support_card_type = t
                    match_center = r.center_point
                    break

            if support_card_type == SupportCardType.SUPPORT_CARD_TYPE_UNKNOWN and support_card_favor_process != SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_UNKNOWN:
                support_card_type = SupportCardType.SUPPORT_CARD_TYPE_NPC

            h_local, w_local = roi.shape[:2]
            cx = base_x + (w_local // 2)
            cy = base_y + (h_local // 2)
            if isinstance(match_center, (tuple, list)) and len(match_center) >= 2:
                cx = base_x + int(match_center[0])
                cy = base_y + int(match_center[1])

            info = SupportCardInfo(
                name=CARD_TYPE_NAMES.get(support_card_type, "support_card"),
                card_type=support_card_type,
                favor=support_card_favor_process,
                can_incr_special_training=can_incr_special_training,
                spirit_explosion=spirit_explosion
            )
            info.center = (cx, cy)
            support_card_list_info_result.append(info)

            base_y += inc

        unknown_count = sum(1 for sc in support_card_list_info_result if sc.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_UNKNOWN)
        if unknown_count == len(support_card_list_info_result) and len(support_card_list_info_result) > 0:
            return []
        return support_card_list_info_result