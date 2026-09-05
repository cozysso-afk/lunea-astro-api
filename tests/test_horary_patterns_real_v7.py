from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import unittest

import astro_core as core
import horary_topic_routes_v3  # noqa: F401  # installs V4 -> V5 -> V6 -> V7
import horary_balance_v31 as v31
import horary_engine_v6 as v6


LAT = 34.7594
LON = 127.6530
TZ = "Asia/Seoul"


def base_chart(local_iso: str):
    return v31.compute_horary(
        question_text="전통 패턴 골든 검산",
        question_iso=local_iso,
        topic="general",
        timezone_name=TZ,
        place="현재 위치",
        lat=LAT,
        lon=LON,
    )


def remap_pair(data: dict, querent: str, quesited: str) -> dict:
    row = deepcopy(data)
    qrow = row["planets"][querent]
    trow = row["planets"][quesited]
    row["significators"]["querent"] = {"ruler": querent, "planet": qrow, "house": 1}
    row["significators"]["quesited"] = {"ruler": quesited, "planet": trow, "house": 7}
    row["significators"]["event"] = None
    dt_utc = datetime.fromisoformat(row["moment"]["utc_iso"].replace("Z", "+00:00"))
    row["judgment_support"]["primary_connection"] = v6._strict_aspect_state(querent, qrow, quesited, trow)
    row["judgment_support"]["perfection"] = v6._strict_perfection_candidate(
        querent, qrow, quesited, trow, dt_utc, TZ
    )
    return row


class HoraryRealPatternGoldensV7(unittest.TestCase):
    def test_real_translation_of_light_golden(self):
        data = remap_pair(base_chart("2026-01-03T00:00:00+09:00"), "Sun", "Saturn")
        rows = v31._translation_candidates(data, TZ)
        self.assertTrue(rows)
        first = rows[0]
        self.assertEqual(first["type"], "translation_of_light")
        self.assertEqual(first["translator"], "Moon")
        self.assertEqual(first["from"], "Saturn")
        self.assertEqual(first["to"], "Sun")
        self.assertEqual(first["classification"], "confirmed_pattern")
        self.assertTrue(first["separating_aspect"]["within_orb"])
        self.assertEqual(first["separating_aspect"]["phase"], "separating")
        self.assertTrue(first["applying_perfection"]["perfects"])

    def test_real_collection_of_light_golden(self):
        data = remap_pair(base_chart("2026-01-01T12:00:00+09:00"), "Sun", "Venus")
        rows = v31._collection_candidates(data, TZ)
        self.assertTrue(rows)
        mars = next((row for row in rows if row.get("collector") == "Mars"), None)
        self.assertIsNotNone(mars)
        self.assertEqual(mars["classification"], "confirmed_pattern")
        self.assertTrue(mars["querent_perfection"]["perfects"])
        self.assertTrue(mars["quesited_perfection"]["perfects"])
        self.assertLessEqual(max(mars["days_to_querent_contact"], mars["days_to_quesited_contact"]), 60.0)

    def test_real_prohibition_golden(self):
        data = remap_pair(base_chart("2026-01-01T12:00:00+09:00"), "Sun", "Mars")
        self.assertTrue(data["judgment_support"]["perfection"]["perfects"])
        rows = v31._confirmed_interventions(data, TZ)
        prohibition = next((row for row in rows if row.get("type") == "prohibition"), None)
        self.assertIsNotNone(prohibition)
        self.assertEqual(prohibition["intervening"], "Venus")
        self.assertEqual(prohibition["classification"], "confirmed_pattern")
        self.assertGreater(prohibition["days_before_main"], 0.0)

    def test_real_frustration_golden(self):
        data = remap_pair(base_chart("2026-01-10T00:00:00+09:00"), "Sun", "Moon")
        self.assertTrue(data["judgment_support"]["perfection"]["perfects"])
        rows = v31._confirmed_interventions(data, TZ)
        frustration = next((row for row in rows if row.get("type") == "frustration"), None)
        self.assertIsNotNone(frustration)
        self.assertEqual(frustration["intervening"], "Jupiter")
        self.assertEqual(frustration["classification"], "confirmed_pattern")
        self.assertGreater(frustration["days_before_main"], 0.0)

    def test_real_sign_ingress_interruption_is_not_refranation(self):
        # 2026-01-02 12:00 KST. Moon/Mercury are within-moiety applying
        # opposition, but Moon changes sign before exact perfection. This must
        # be an ingress interruption, not a station-based Refranation.
        data = base_chart("2026-01-02T12:00:00+09:00")
        dt_utc = datetime.fromisoformat(data["moment"]["utc_iso"].replace("Z", "+00:00"))
        moon = data["planets"]["Moon"]
        mercury = data["planets"]["Mercury"]
        state = v6._strict_aspect_state("Moon", moon, "Mercury", mercury)
        self.assertTrue(state["within_orb"])
        self.assertEqual(state["traditional_valid_aspect"], "opposition")
        self.assertEqual(state["phase"], "applying")

        p = v6._strict_perfection_candidate("Moon", moon, "Mercury", mercury, dt_utc, TZ)
        self.assertFalse(p["perfects"])
        self.assertEqual(p["reason"], "sign_change_before_perfection")
        self.assertEqual(p["interruption_type"], "sign_ingress")
        self.assertFalse(p["is_refranation"])

    def test_real_station_refranation_golden(self):
        data = base_chart("2026-10-23T04:12:48+09:00")
        dt_utc = datetime.fromisoformat(data["moment"]["utc_iso"].replace("Z", "+00:00"))
        mercury = data["planets"]["Mercury"]
        jupiter = data["planets"]["Jupiter"]
        state = v6._strict_aspect_state("Mercury", mercury, "Jupiter", jupiter)
        self.assertTrue(state["within_orb"])
        self.assertEqual(state["traditional_valid_aspect"], "square")
        self.assertEqual(state["phase"], "applying")

        p = v6._strict_perfection_candidate("Mercury", mercury, "Jupiter", jupiter, dt_utc, TZ)
        self.assertFalse(p["perfects"])
        self.assertEqual(p["reason"], "refranation_station_before_perfection")
        self.assertTrue(p["is_refranation"])
        self.assertEqual(p["interruption_type"], "station")
        self.assertEqual((p.get("station") or {}).get("body"), "Mercury")


if __name__ == "__main__":
    unittest.main()
