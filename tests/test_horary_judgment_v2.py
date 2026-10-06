from __future__ import annotations

import json
import unittest

import horary_topic_routes_v3  # noqa: F401  # installs production V4 -> V5 fast path
import horary_balance_v31 as v31
import horary_judgment_v2 as hv2


LAT = 34.7592
LON = 127.6530
TZ = "Asia/Seoul"


def calc(fn, question, moment):
    return fn(
        question_text=question,
        question_iso=moment,
        topic="stock",
        timezone_name=TZ,
        place="현재 위치",
        lat=LAT,
        lon=LON,
    )


class HoraryJudgmentV2Tests(unittest.TestCase):
    def assert_legacy_judgment_unchanged(self, before, after):
        bj = before["judgment_support"]
        aj = after["judgment_support"]
        self.assertEqual(bj["perfection"], aj["perfection"])
        self.assertEqual(bj["reception"], aj["reception"])
        self.assertEqual(bj["moon_course"], aj["moon_course"])
        self.assertEqual(bj.get("traditional_core_v6"), aj.get("traditional_core_v6"))

        # V7/V8 are optional layers outside the production V5 rollback chain.
        # Judgment V2 must preserve them when installed, but their absence is
        # valid when the caller starts from the rollback chain.
        for key in ("essential_dignities_v7", "judgment_hierarchy_v8"):
            if key in bj or key in aj:
                self.assertEqual(bj.get(key), aj.get(key))

    def test_case_a_current_voc_is_sign_bound_not_whole_target_day(self):
        question = "10/1 내 보유주식 수익실현이 가능할까?"
        moment = "2026-09-30T15:53:00+09:00"
        before = calc(hv2._ORIGINAL_COMPUTE_HORARY, question, moment)
        after = calc(v31.compute_horary, question, moment)
        self.assert_legacy_judgment_unchanged(before, after)

        v2 = after["judgment_support"]["horary_v2"]
        self.assertEqual(v2["horaryRuleset"]["id"], "HORARY_V2_TRADITIONAL")
        self.assertTrue(v2["separationContract"]["currentJudgmentSeparateFromFutureDevelopment"])
        self.assertTrue(v2["voc"]["isVoid"])
        self.assertEqual(v2["voc"]["scope"], "current_sign_only")
        self.assertTrue(v2["voc"]["signExitAt"].startswith("2026-10-01T02:"))
        self.assertEqual(v2["futureDevelopment"]["start"], "2026-10-01T00:00:00+09:00")
        self.assertEqual(v2["futureDevelopment"]["end"], "2026-10-01T23:59:59+09:00")
        self.assertTrue(v2["futureDevelopment"]["currentJudgmentUnchanged"])
        self.assertTrue(v2["moonFlow"]["signIngressAt"].startswith("2026-10-01T02:"))
        self.assertIsNotNone(v2["moonFlow"]["firstAspectAfterIngress"])

    def test_case_b_range_aspect_progression_and_radical_future_separation(self):
        question = "10/1~10/2 보유주식 수익실현 가능한가요?"
        moment = "2026-09-30T22:18:00+09:00"
        before = calc(hv2._ORIGINAL_COMPUTE_HORARY, question, moment)
        after = calc(v31.compute_horary, question, moment)
        self.assert_legacy_judgment_unchanged(before, after)

        v2 = after["judgment_support"]["horary_v2"]
        self.assertEqual(v2["questionIntent"]["id"], "realised_profit_event")
        self.assertEqual(v2["judgmentAxis"]["querent"]["house"], 1)
        self.assertEqual(v2["judgmentAxis"]["quesited"]["house"], 5)
        self.assertEqual(v2["judgmentAxis"]["event"]["house"], 2)
        self.assertTrue(v2["judgmentAxis"]["routingUnchanged"])

        fw = v2["futureDevelopment"]
        self.assertEqual(fw["start"], "2026-10-01T00:00:00+09:00")
        self.assertEqual(fw["end"], "2026-10-02T23:59:59+09:00")
        self.assertEqual(len(fw["dailySnapshots"]), 2)

        pair = next(
            row for row in v2["aspectApplications"]
            if set(row.get("pair") or []) == {"Mercury", "Venus"}
        )
        self.assertEqual(pair["aspectType"], "conjunction")
        self.assertFalse(pair["currentlyWithinOrb"])
        self.assertTrue(pair["applying"])
        self.assertIsNotNone(pair["orbEntryAt"])
        self.assertIsNotNone(pair["exactPerfectionAt"])
        self.assertGreater(pair["exactPerfectionAt"], "2026-10-02T23:59:59+09:00")
        self.assertTrue(pair["currentPerfectionUnchanged"])

        self.assertTrue(v2["voc"]["signExitAt"].startswith("2026-10-01T02:"))
        self.assertTrue(v2["moonFlow"]["events"])
        for event in v2["moonFlow"]["events"]:
            self.assertIn(event["eventAxisRelation"], {
                "direct_querent", "direct_quesited", "direct_money",
                "direct_event", "supportive", "unrelated", "none",
            })

        self.assertEqual(v2["currentJudgment"], v2["radicalJudgment"])
        self.assertTrue(v2["perfection"]["currentJudgmentUnchanged"])
        self.assertFalse(v2["reception"]["modifiesPerfection"])
        self.assertIsNone(v2["confidence"]["probabilityPercent"])
        self.assertTrue(v2["aiInterpretationGuardrails"]["evidencePathRequired"])

        print("HORARY_V2_CASE_B_JSON=" + json.dumps({
            "horaryRuleset": v2["horaryRuleset"],
            "questionIntent": v2["questionIntent"],
            "judgmentAxis": v2["judgmentAxis"],
            "currentJudgment": v2["currentJudgment"],
            "mercuryVenus": pair,
            "voc": v2["voc"],
            "moonFlow": v2["moonFlow"],
            "futureDevelopment": {
                "start": fw["start"],
                "end": fw["end"],
                "dailySnapshots": fw["dailySnapshots"],
            },
            "perfection": v2["perfection"],
            "reception": v2["reception"],
            "confidence": v2["confidence"],
        }, ensure_ascii=False, default=str))

    def test_ruleset_preserves_existing_orb_policy_and_excludes_modern_bodies(self):
        data = calc(v31.compute_horary, "10/1 내 보유주식 수익실현이 가능할까?", "2026-09-30T15:53:00+09:00")
        rules = data["judgment_support"]["horary_v2"]["horaryRuleset"]
        self.assertEqual(rules["orbPolicy"]["method"], "planetary_moiety_sum")
        self.assertFalse(rules["orbPolicy"]["changedByV2"])
        self.assertEqual(rules["houseSystem"], "regiomontanus")
        self.assertEqual(rules["traditionalBodies"], list(__import__("astro_core").HORARY_PLANETS))
        self.assertIn("excluded", rules["modernBodiesPolicy"])


if __name__ == "__main__":
    unittest.main()
