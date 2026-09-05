from __future__ import annotations

import unittest
from datetime import datetime, timezone

import astro_core as core
import horary_topic_routes_v3  # noqa: F401  # installs V4 -> V5 -> V6 -> V7 chain
import horary_balance_v31 as v31
import horary_engine_v6 as v6


QUESTION = "A는 2026년 9월 30일까지 나에게 먼저 사적인 연락을 해올까요?"
LAT = 34.7594
LON = 127.6530


def compute(question_iso: str, topic: str = "contact", question: str = QUESTION):
    return v31.compute_horary(
        question_text=question,
        question_iso=question_iso,
        topic=topic,
        timezone_name="Asia/Seoul",
        place="현재 위치",
        lat=LAT,
        lon=LON,
    )


class HoraryEngineV6Tests(unittest.TestCase):
    def test_out_of_orb_geometric_aspect_never_enters_perfection(self):
        saturn = {"longitude": 0.0, "speed_deg_per_day": 0.1, "sign_index": 0}
        sun = {"longitude": 149.4144, "speed_deg_per_day": 1.0, "sign_index": 4}
        state = v6._strict_aspect_state("Saturn", saturn, "Sun", sun)
        self.assertEqual(state["closest_geometric_aspect"]["aspect"], "trine")
        self.assertAlmostEqual(state["closest_geometric_aspect"]["orb"], 29.4144, places=3)
        self.assertFalse(state["within_orb"])
        self.assertIsNone(state["traditional_valid_aspect"])
        self.assertTrue(state["traditional_state"].startswith("out_of_orb_"))

        result = v6._strict_perfection_candidate(
            "Saturn", saturn, "Sun", sun,
            datetime(2026, 9, 5, 9, 11, tzinfo=timezone.utc),
            "Asia/Seoul",
        )
        self.assertFalse(result["perfects"])
        self.assertEqual(result["reason"], "out_of_orb_no_active_perfection")
        self.assertFalse(result["perfection_check_started"])
        self.assertFalse(result["refranation_applicable"])

    def test_within_orb_motion_state_is_separate_from_geometric_label(self):
        a = {"longitude": 0.0, "speed_deg_per_day": 0.0, "sign_index": 0}
        b = {"longitude": 125.0, "speed_deg_per_day": -1.0, "sign_index": 4}
        state = v6._strict_aspect_state("Saturn", a, "Sun", b)
        self.assertEqual(state["closest_geometric_aspect"]["aspect"], "trine")
        self.assertTrue(state["within_orb"])
        self.assertEqual(state["traditional_valid_aspect"], "trine")
        self.assertEqual(state["traditional_state"], "valid_applying")
        self.assertEqual(state["phase"], "applying")

    def test_regiomontanus_fixture_is_reproducible(self):
        dt_utc = datetime(2026, 9, 5, 9, 11, tzinfo=timezone.utc)
        houses = core.compute_regiomontanus_houses(dt_utc, LAT, LON)
        self.assertAlmostEqual(houses["asc"], 329.59002342674495, places=5)
        self.assertAlmostEqual(houses["mc"], 251.43868360169552, places=5)
        expected = [
            329.59002342674495, 14.49791908365267, 48.58110687553263,
            71.43868360169552, 91.14563161134907, 114.48924531192904,
            149.59002342674495, 194.49791908365268, 228.58110687553264,
            251.43868360169552, 271.1456316113491, 294.48924531192904,
        ]
        for got, want in zip(houses["cusps"], expected):
            self.assertAlmostEqual(got, want, places=5)

    def test_contact_fixture_strict_traditional_contract(self):
        data = compute("2026-09-05T18:11:00+09:00")
        self.assertEqual(data["meta"]["horary_engine"], "LUNEA_HORARY_ENGINE_V7_BALANCE_GUARDS")
        self.assertEqual(data["judgment_support"]["traditional_core_v6"]["version"], v6.VERSION)
        self.assertEqual(data["house_system"], "regiomontanus")
        self.assertEqual(data["meta"]["aspect_orb_policy"]["method"], "planetary_moiety_sum")
        self.assertEqual(data["moment"]["local_iso"], "2026-09-05T18:11:00+09:00")
        self.assertTrue(data["moment"]["utc_iso"].startswith("2026-09-05T09:11:00"))

        self.assertEqual(data["angles"]["ASC"]["sign_en"], "Aquarius")
        self.assertAlmostEqual(data["angles"]["ASC"]["degree"], 29.590023, places=4)
        self.assertAlmostEqual(data["angles"]["MC"]["degree"], 11.438684, places=4)

        sig = data["significators"]
        self.assertEqual(sig["querent"]["ruler"], "Saturn")
        self.assertEqual(sig["quesited"]["ruler"], "Sun")
        self.assertEqual(sig["event"]["house"], 9)
        self.assertEqual(sig["event"]["ruler"], "Mars")

        j = data["judgment_support"]
        connection = j["primary_connection"]
        self.assertEqual(connection["closest_geometric_aspect"]["aspect"], "trine")
        self.assertGreater(connection["closest_geometric_aspect"]["orb"], 20.0)
        self.assertIsNone(connection["traditional_valid_aspect"])
        self.assertFalse(j["perfection"]["perfects"])
        self.assertEqual(j["perfection"]["reason"], "out_of_orb_no_active_perfection")
        self.assertFalse(j["perfection"]["perfection_check_started"])

        moon = j["moon_course"]
        self.assertTrue(moon["void_of_course"])
        self.assertIsNone(moon["next_major_applying_aspect"])
        self.assertFalse(moon["next_applying_before_sign_change"])
        self.assertEqual(moon["policy"], "traditional_7_planets_ptolemaic_aspects_before_moon_sign_ingress")
        self.assertFalse(moon["outer_planets_included"])

        warning_codes = {row["code"] for row in j["warnings"]}
        self.assertIn("late_asc", warning_codes)
        self.assertIn("void_moon", warning_codes)
        for row in j["warnings"]:
            self.assertFalse(row.get("invalidates_chart", False))

        strict = j["traditional_core_v6"]
        self.assertFalse(strict["chart_invalid"])
        self.assertEqual(strict["derived_house_policy"]["target_person_house"], 7)
        self.assertEqual(strict["derived_house_policy"]["target_message_house"], 9)
        self.assertEqual(strict["derived_house_policy"]["derivation"], "3rd from 7th = radical 9H")
        self.assertIn("quesited_to_event", strict["derived_event_axes"])
        self.assertIn("event_to_querent", strict["derived_event_axes"])
        self.assertEqual(strict["reception_role"], "support_only_not_perfection_substitute")
        self.assertNotEqual(strict["evidence_grade"], "A")

        modern = j["modern_supplemental_v6"]
        self.assertFalse(modern["used_in_traditional_core"])
        self.assertTrue(modern["excluded_from_voc_perfection_translation_collection_reception"])

    def test_real_soft_applying_perfection_reaches_positive_A_grade(self):
        data = compute(
            "2026-09-04T15:00:00+09:00", topic="general",
            question="이 일은 실제로 성사될까요?",
        )
        j = data["judgment_support"]
        p = j["perfection"]
        self.assertTrue(p["perfects"])
        self.assertTrue(p["perfection_check_started"])
        self.assertTrue(p["started_within_orb"])
        self.assertEqual((p.get("aspect") or {}).get("traditional_valid_aspect"), "sextile")
        self.assertEqual((p.get("aspect") or {}).get("traditional_state"), "valid_applying")
        self.assertEqual(j["traditional_core_v6"]["evidence_grade"], "A")

    def test_real_hard_applying_perfection_is_not_automatic_no(self):
        data = compute(
            "2026-09-06T15:00:00+09:00", topic="general",
            question="어려움이 있어도 이 일은 성사될까요?",
        )
        j = data["judgment_support"]
        p = j["perfection"]
        self.assertTrue(p["perfects"])
        self.assertEqual((p.get("aspect") or {}).get("traditional_valid_aspect"), "square")
        self.assertEqual((p.get("aspect") or {}).get("traditional_state"), "valid_applying")
        self.assertEqual(j["traditional_core_v6"]["evidence_grade"], "A")

    def test_real_within_orb_separating_aspect_does_not_become_perfection(self):
        data = compute(
            "2026-09-05T01:00:00+09:00", topic="general",
            question="이미 지나간 흐름이 다시 성사각으로 잡히나요?",
        )
        j = data["judgment_support"]
        state = j["primary_connection"]
        self.assertTrue(state["within_orb"])
        self.assertEqual(state["traditional_state"], "valid_separating")
        self.assertFalse(j["perfection"]["perfects"])
        self.assertEqual(j["perfection"]["reason"], "no_valid_applying_aspect")
        self.assertNotEqual(j["traditional_core_v6"]["evidence_grade"], "A")


if __name__ == "__main__":
    unittest.main()
