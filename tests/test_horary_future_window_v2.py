from __future__ import annotations

import unittest

import horary_topic_routes_v3  # noqa: F401
import horary_balance_v31 as v31
import horary_future_window_v2 as fw2


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
        self.assertTrue(fw["active"])
        self.assertEqual(fw["targetWindow"]["start"], "2026-10-01T00:00:00+09:00")
        self.assertEqual(fw["targetWindow"]["end"], "2026-10-02T23:59:59+09:00")
        self.assertEqual(fw["sourceText"], "10/1~10/2")
        self.assertEqual([x["date"] for x in fw["dailySummaries"]], ["2026-10-01", "2026-10-02"])

        moon_ingress = fw["moonFutureFlow"]["ingress"]
        self.assertIsNotNone(moon_ingress)
        self.assertEqual(moon_ingress["from_sign_en"], "Taurus")
        self.assertEqual(moon_ingress["to_sign_en"], "Gemini")
        self.assertTrue(moon_ingress["time_local"].startswith("2026-10-01T02:"))
        self.assertTrue(fw["moon_voc_scope_ends_before_target_end"])
        self.assertTrue(fw["moonFutureFlow"]["aspects_after_ingress"])
        for row in fw["moonFutureFlow"]["aspects_after_ingress"]:
            self.assertIn("direct_event_axis", row)
            self.assertIn("supportive_only", row)

        pair = next(
            x for x in fw["futureAspectDevelopment"]
            if {x.get("a"), x.get("b")} == {"Mercury", "Venus"}
        )
        self.assertEqual(pair["aspect"], "conjunction")
        self.assertFalse(pair["question_time"]["within_orb"])
        self.assertEqual(pair["question_time"]["motion"], "applying")
        self.assertTrue(pair["currentPerfectionUnchanged"])
        self.assertEqual(len([x for x in pair["samples"] if x["label"] == "market_open_reference"]), 2)
        self.assertEqual(len([x for x in pair["samples"] if x["label"] == "market_close_reference"]), 2)
        open_close = [x for x in pair["samples"] if x["label"] in {"market_open_reference", "market_close_reference"}]
        self.assertLess(open_close[-1]["distance_to_exact_deg"], open_close[0]["distance_to_exact_deg"])

        exact = pair["exact_perfection_reference"]
        self.assertIsNotNone(exact)
        self.assertEqual(exact["scope"], "after_target_window")
        self.assertGreater(exact["time_local"], "2026-10-02T23:59:59+09:00")

        self.assertTrue(fw["currentJudgmentUnchanged"])
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
