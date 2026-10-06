from __future__ import annotations

import unittest

import horary_topic_routes_v3  # noqa: F401  # production installs V4 -> V5 only
import horary_balance_v31 as v31
import horary_engine_v8  # noqa: F401  # advanced QA explicitly activates V6 -> V7 -> V8
import horary_future_window_v2 as fw2
import horary_future_window_v21 as fw21  # noqa: F401


LAT = 34.7592
LON = 127.6530
QUESTION = "10/1~10/2 보유주식 수익실현 가능한가요?"
QUESTION_ISO = "2026-09-30T22:18:00+09:00"


def calc(fn):
    return fn(
        question_text=QUESTION,
        question_iso=QUESTION_ISO,
        topic="stock",
        timezone_name="Asia/Seoul",
        place="현재 위치",
        lat=LAT,
        lon=LON,
    )


class HoraryFutureWindowV2Tests(unittest.TestCase):
    def test_range_parser_examples(self):
        base = fw2.v6._parse_utc("2026-09-30T13:18:00+00:00")
        cases = {
            "10/1~10/2": ("2026-10-01", "2026-10-02"),
            "10/1-10/2": ("2026-10-01", "2026-10-02"),
            "10월 1일~2일": ("2026-10-01", "2026-10-02"),
            "10월 1일부터 2일까지": ("2026-10-01", "2026-10-02"),
            "내일~모레": ("2026-10-01", "2026-10-02"),
            "이번 주 목~금": ("2026-10-01", "2026-10-02"),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                row = fw2.parse_target_window(text, base, "Asia/Seoul")
                self.assertIsNotNone(row)
                self.assertEqual(row["start_date"].isoformat(), expected[0])
                self.assertEqual(row["end_date"].isoformat(), expected[1])

    def test_requested_stock_range_tracks_full_window_without_mutating_current_judgment(self):
        before = calc(fw2._ORIGINAL_COMPUTE_HORARY)
        after = calc(v31.compute_horary)

        before_j = before["judgment_support"]
        after_j = after["judgment_support"]
        fw = after_j["future_window_v1"]

        self.assertEqual(fw["version"], fw2.VERSION)
        self.assertEqual(fw["hardeningVersion"], fw21.VERSION)
        self.assertTrue(fw["active"])
        self.assertEqual(fw["targetWindow"]["start"], "2026-10-01T00:00:00+09:00")
        self.assertEqual(fw["targetWindow"]["end"], "2026-10-02T23:59:59+09:00")
        self.assertEqual(fw["sourceText"], "10/1~10/2")
        self.assertEqual([x["date"] for x in fw["dailySummaries"]], ["2026-10-01", "2026-10-02"])

        moon_flow = fw["moonFutureFlow"]
        moon_ingress = moon_flow["ingress"]
        self.assertIsNotNone(moon_ingress)
        self.assertEqual(moon_ingress["from_sign_en"], "Taurus")
        self.assertEqual(moon_ingress["to_sign_en"], "Gemini")
        self.assertTrue(moon_ingress["time_local"].startswith("2026-10-01T02:"))
        self.assertTrue(fw["moon_voc_scope_ends_before_target_end"])
        self.assertTrue(moon_flow["target_window_scan_complete"])
        self.assertEqual(moon_flow["scan_policy"], "every_target_intersecting_moon_sign_segment_until_sign_exit")

        # Regression: the 10/2 Moon-Jupiter sextile must not disappear merely
        # because the old Future Window scan was anchored on ingress handling.
        moon_jupiter = [
            row for row in moon_flow["target_window_aspects"]
            if row.get("body") == "Jupiter" and row.get("aspect") == "sextile"
        ]
        self.assertTrue(moon_jupiter, "Moon-Jupiter sextile must be present in target-window Moon flow")
        self.assertTrue(moon_jupiter[0]["exact_local"].startswith("2026-10-02T11:"))
        self.assertEqual(moon_jupiter[0]["sign_en"], "Gemini")

        gemini = next(row for row in moon_flow["sign_segments"] if row.get("sign_en") == "Gemini")
        last = gemini["lastMajorAspectBeforeSignExit"]
        self.assertIsNotNone(last)
        self.assertEqual(last["body"], "Jupiter")
        self.assertEqual(last["aspect"], "sextile")
        self.assertEqual(gemini["vocAfterLastExactAt"], last["exact_local"])
        self.assertTrue(gemini["vocUntilSignExitAt"] > last["exact_local"])

        day2 = next(row for row in fw["dailySummaries"] if row["date"] == "2026-10-02")
        self.assertTrue(any(
            row.get("body") == "Jupiter" and row.get("aspect") == "sextile"
            for row in day2["moon_major_aspects"]
        ))
        self.assertTrue(day2["moon_voc_transitions"])

        for row in moon_flow["target_window_aspects"]:
            self.assertIn("eventAxisRelation", row)
            self.assertIn("direct_event_axis", row)
            self.assertIn("supportive_only", row)

        pair = next(
            x for x in fw["futureAspectDevelopment"]
            if {x.get("a"), x.get("b")} == {"Mercury", "Venus"}
        )
        self.assertEqual(pair["aspect"], "conjunction")
        self.assertFalse(pair["question_time"]["within_orb"])
        self.assertFalse(pair["currentWithinOrb"])
        self.assertEqual(pair["question_time"]["motion"], "applying")
        self.assertTrue(pair["targetWindowWithinOrb"])
        self.assertTrue(pair["futureDevelopmentOnly"])
        self.assertTrue(pair["targetWindowOrbEntryAt"].startswith("2026-10-01T22:"))
        self.assertFalse(pair["targetWindowEvidence"]["mayBePromotedToCurrentPerfection"])
        self.assertTrue(pair["currentPerfectionUnchanged"])
        self.assertEqual(len([x for x in pair["samples"] if x["label"] == "market_open_reference"]), 2)
        self.assertEqual(len([x for x in pair["samples"] if x["label"] == "market_close_reference"]), 2)
        open_close = [x for x in pair["samples"] if x["label"] in {"market_open_reference", "market_close_reference"}]
        self.assertLess(open_close[-1]["distance_to_exact_deg"], open_close[0]["distance_to_exact_deg"])

        exact = pair["exact_perfection_reference"]
        self.assertIsNotNone(exact)
        self.assertEqual(exact["scope"], "after_target_window")
        self.assertTrue(exact["time_local"].startswith("2026-10-07T09:"))
        self.assertGreater(exact["time_local"], "2026-10-02T23:59:59+09:00")
        stations = [row for row in exact.get("interruption_events_before_exact", []) if row.get("type") == "station"]
        venus_station = next(row for row in stations if row.get("body") == "Venus")
        self.assertEqual(venus_station["stationKind"], "retrograde_station")
        self.assertTrue(venus_station["time_local"].startswith("2026-10-03T16:"))

        # Future evidence is explicitly separated from the radical/current result.
        self.assertTrue(fw["currentJudgmentUnchanged"])
        self.assertFalse(fw["currentPerfection"]["perfects"])
        self.assertEqual(before_j["perfection"], after_j["perfection"])
        self.assertEqual(before_j["reception"], after_j["reception"])
        self.assertEqual(before_j["moon_course"], after_j["moon_course"])
        self.assertEqual(before_j["essential_dignities_v7"], after_j["essential_dignities_v7"])
        self.assertEqual(
            before_j["judgment_hierarchy_v8"]["qualified_evidence_grade_v8"],
            after_j["judgment_hierarchy_v8"]["qualified_evidence_grade_v8"],
        )


if __name__ == "__main__":
    unittest.main()
