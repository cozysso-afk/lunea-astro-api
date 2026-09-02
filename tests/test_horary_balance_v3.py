from __future__ import annotations

import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import numpy as np

import astro_core as core
import horary_topic_routes_v3  # noqa: F401
import horary_balance_v3 as v3


UTC = timezone.utc


def planet(lon, speed=1.0):
    return {
        "longitude": float(lon),
        "sign_index": int(float(lon) // 30),
        "speed_deg_per_day": float(speed),
    }


def base_data(primary, reception=None, *, primary_connection=None, moon=None, event=None, prohibitions=None):
    return {
        "moment": {"utc_iso": "2026-09-02T00:00:00+00:00"},
        "significators": {
            "querent": {"ruler": "Venus", "planet": planet(12.0, 1.2)},
            "quesited": {"ruler": "Mars", "planet": planet(102.0, 0.7)},
            "event": event,
        },
        "judgment_support": {
            "perfection": primary,
            "reception": reception or {
                "same_significator": False,
                "mutual_reception": False,
                "has_reception": False,
            },
            "primary_connection": primary_connection or {},
            "moon_course": moon or {"void_of_course": False, "next_aspects": []},
            "potential_prohibition": prohibitions or [],
        },
    }


class HoraryBalanceV3Tests(unittest.TestCase):
    def test_out_of_orb_future_perfection_is_detected(self):
        dt = datetime(2026, 9, 2, tzinfo=UTC)
        row_a = planet(0.0, 1.0)
        row_b = planet(80.0, 0.2)
        times = [dt, dt + timedelta(days=1), dt + timedelta(days=2)]
        a_lons = np.asarray([0.0, 1.0, 2.0])
        b_lons = np.asarray([80.0, 70.0, 62.0])

        initial = {
            "phase": "out_of_orb",
            "aspect": "sextile",
            "aspect_ko": "육십분위",
            "angle": 60.0,
            "orb": 20.0,
            "within_orb": False,
        }

        def exact_lon(body, _):
            return 2.0 if body == "Venus" else 62.0

        with patch.object(core, "_horary_aspect_state", return_value=initial), \
             patch.object(v3, "_sample_until_first_sign_change", return_value=(times, a_lons, b_lons, None)), \
             patch.object(core, "_horary_refine_pair", return_value=(times[-1], 0.0)), \
             patch.object(core, "get_tropical_ecliptic_lon", side_effect=exact_lon):
            result = v3._balanced_perfection_candidate(
                "Venus", row_a, "Mars", row_b, dt, "Asia/Seoul"
            )

        self.assertTrue(result["perfects"])
        self.assertEqual(result["reason"], "future_perfection_from_out_of_orb")
        self.assertTrue(result["before_sign_change"])
        self.assertEqual(result["aspect"]["aspect"], "sextile")

    def test_hard_perfection_with_mutual_reception_is_not_negative(self):
        primary = {
            "perfects": True,
            "reason": "perfects",
            "aspect": {"aspect": "square", "aspect_ko": "사분위"},
        }
        reception = {
            "same_significator": False,
            "mutual_reception": True,
            "has_reception": True,
        }
        data = base_data(primary, reception)
        balance = v3._build_balance(data, "Asia/Seoul")

        self.assertEqual(balance["tier"], "direct_friction_supported")
        self.assertIn("성사", balance["headline_ko"])
        self.assertGreater(balance["support_score"], balance["constraint_score"])

    def test_sign_change_without_support_remains_blocked(self):
        primary = {
            "perfects": False,
            "indeterminate": False,
            "reason": "sign_change_before_perfection",
            "aspect": {"aspect": "trine", "aspect_ko": "삼분위"},
        }
        data = base_data(primary)
        balance = v3._build_balance(data, "Asia/Seoul")

        self.assertEqual(balance["tier"], "blocked_direct")
        self.assertGreaterEqual(balance["constraint_score"], 3.0)
        self.assertEqual(balance["support_score"], 0.0)

    def test_potential_prohibition_does_not_overturn_direct_perfection(self):
        primary = {
            "perfects": True,
            "reason": "perfects",
            "aspect": {"aspect": "trine", "aspect_ko": "삼분위"},
        }
        data = base_data(
            primary,
            prohibitions=[{"classification": "potential_only", "intervening": "Mercury"}],
        )
        balance = v3._build_balance(data, "Asia/Seoul")

        self.assertIn(balance["tier"], {"direct_support", "strong_support"})
        self.assertGreater(balance["support_score"], balance["constraint_score"])
        self.assertTrue(any("확정 prohibition 아님" in x for x in balance["constraints_ko"]))

    def test_new_topic_routes_do_not_fall_through_to_general_seventh_house(self):
        self.assertEqual(core.HORARY_TOPIC_SPECS["friend"]["quesited_house"], 11)
        self.assertEqual(core.HORARY_TOPIC_SPECS["travel"]["quesited_house"], 9)
        self.assertEqual(core.HORARY_TOPIC_SPECS["purchase"]["quesited_house"], 2)
        self.assertEqual(core.HORARY_TOPIC_SPECS["communication"]["quesited_house"], 3)
        self.assertEqual(core.HORARY_TOPIC_SPECS["contract"]["event_house"], 3)
        self.assertEqual(core.HORARY_TOPIC_SPECS["reconciliation"]["event_house"], 5)

    def test_real_ephemeris_smoke(self):
        started = time.perf_counter()
        result = v3.compute_horary(
            question_text="그 사람과 다시 대화를 시작하고 관계를 회복할 수 있을까요?",
            question_iso="2026-09-02T08:30",
            topic="reconciliation",
            timezone_name="Asia/Seoul",
            lat=37.5665,
            lon=126.9780,
        )
        elapsed = time.perf_counter() - started
        self.assertEqual(result["schema"], "LUNEA_HORARY_V1")
        self.assertEqual(result["meta"]["horary_balance"], "LUNEA_HORARY_BALANCE_V3")
        self.assertEqual(result["judgment_support"]["balance_v3"]["version"], "LUNEA_HORARY_BALANCE_V3")
        self.assertEqual(result["significators"]["event"]["house"], 5)
        self.assertIn(result["judgment_support"]["balance_v3"]["tier"], {
            "direct_friction_supported", "direct_with_friction", "strong_support", "direct_support",
            "secondary_support", "shared_ruler_open", "mixed_support", "open_indeterminate",
            "blocked_direct", "weak_evidence",
        })
        print(f"real Horary V3 smoke: {elapsed:.3f}s · tier={result['judgment_support']['balance_v3']['tier']}")


if __name__ == "__main__":
    unittest.main()
