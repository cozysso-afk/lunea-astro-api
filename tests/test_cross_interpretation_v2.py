from __future__ import annotations

import json
import unittest

from cross_interpretation_v2 import SCHEMA, build_cross_interpretation


def horary_fixture(
    band="A",
    grade=None,
    reception="none",
    obstruction=0,
    moon=False,
):
    grade = grade or ({"A": "A_CLEAR", "B": "B_TRANSLATION", "C": "C", "D": "D"}.get(band, "NONE"))
    event_perfection = band == "C"
    action_state = {
        "A": ("direct_perfection", "주 시그니피케이터 직접 성사 근거 있음"),
        "B": ("indirect_perfection", "Translation/Collection 간접 성사 근거 있음"),
        "C": ("contact_event_perfection", "연락 파생 사건축의 실제 성사 근거 있음"),
        "D": ("not_perfected", "확인된 사건 성사각 없음"),
    }.get(band, ("not_perfected", "확인된 사건 성사각 없음"))
    return {
        "schema": "LUNEA_HORARY_V1",
        "judgment_support": {
            "judgment_hierarchy_v8": {
                "version": "LUNEA_HORARY_ENGINE_V8_JUDGMENT_HIERARCHY",
                "qualified_evidence_grade_v8": grade,
                "grade_band_v8": band,
                "grade_source_v8": "fixture_preserved",
                "overall_state_v8": "event_supported" if band in {"A", "B", "C"} else "insufficient_event_evidence",
                "overall_ko_v8": "사건 성사 쪽 근거 있음" if band in {"A", "B", "C"} else "사건 성사 근거 부족",
                "action_state_v8": {"state": action_state[0], "label_ko": action_state[1]},
                "intention_reception_v8": {"state": reception, "label_ko": "상호 수용성 강함" if reception != "none" else "유의미한 리셉션 없음"},
                "event_axes_v8": {"has_perfection": event_perfection, "perfected_axes": ["quesited_to_event"] if event_perfection else []},
                "indirect_v8": {"present": band == "B"},
                "moon_event_testimony_v8": {"confirmed": moon, "label_ko": "Moon 사건축 적용" if moon else "Moon 사건축 연결 없음"},
                "confirmed_obstruction_count_v8": obstruction,
            }
        },
    }


def prashna_fixture(*factors, band="mixed"):
    score = sum(row[1] for row in factors)
    return {
        "schema": "LUNEA_PRASHNA_V1",
        "judgment_support": {
            "rule_set": "LUNEA_PRASHNA_RULESET_V1",
            "support_score": score,
            "support_band": band,
            "support_band_ko": {"strong": "강", "mixed": "중", "weak": "약"}[band],
            "binary_outcome_generated": False,
            "route": {"subject_house": 7, "event_house": 9},
            "factors": [
                {"code": code, "score": value, "label_ko": code, "detail_ko": detail}
                for code, value, detail in factors
            ],
            "confidence_flags": [],
        },
    }


class CrossInterpretationV2GoldenTests(unittest.TestCase):
    def test_a_both_event_systems_agree(self):
        result = build_cross_interpretation(
            horary_fixture("A"),
            prashna_fixture(("mutual_graha_drishti", 2, "두 주인행성 상호 연결"), band="strong"),
        )
        self.assertEqual(result["schema"], SCHEMA)
        self.assertEqual(result["cross"]["relationship"], "agreement")
        self.assertEqual(result["horary"]["conclusion"]["grade"], "A_CLEAR")

    def test_b_disposition_agreement_does_not_promote_event(self):
        result = build_cross_interpretation(
            horary_fixture("D", reception="mutual_strong"),
            prashna_fixture(("subject_lord_dignity", 2, "대상 주인행성 존귀")),
        )
        self.assertEqual(result["cross"]["relationship"], "partial_agreement")
        self.assertEqual(result["horary"]["conclusion"]["band"], "D")
        self.assertFalse(result["horary"]["event_perfection_evidence"])
        self.assertTrue(any("실제 사건 성사" in row for row in result["cross"]["uncertainty"]))

    def test_c_event_support_and_strong_obstruction_conflict(self):
        result = build_cross_interpretation(
            horary_fixture("A"),
            prashna_fixture(
                ("mars_malefic_event_aspect", -1, "Mars가 사건 하우스를 압박"),
                ("event_lord_dusthana", -1, "사건 주인행성이 8H"),
                band="weak",
            ),
        )
        self.assertEqual(result["cross"]["relationship"], "conflict")
        self.assertTrue(result["cross"]["conflicts"])

    def test_d_horary_d_stays_d_with_positive_prashna(self):
        source = horary_fixture("D")
        result = build_cross_interpretation(
            source,
            prashna_fixture(("mutual_graha_drishti", 2, "상호 연결"), band="strong"),
        )
        self.assertEqual(result["horary"]["conclusion"]["grade"], "D")
        self.assertEqual(source["judgment_support"]["judgment_hierarchy_v8"]["qualified_evidence_grade_v8"], "D")
        self.assertTrue(any("승격하지" in row for row in result["cross"]["uncertainty"]))

    def test_e_horary_a_stays_a_with_weak_prashna(self):
        result = build_cross_interpretation(horary_fixture("A"), prashna_fixture(band="weak"))
        self.assertEqual(result["horary"]["conclusion"]["grade"], "A_CLEAR")
        self.assertIn(result["cross"]["relationship"], {"partial_agreement", "insufficient"})
        self.assertTrue(any("낮추지" in row for row in result["cross"]["uncertainty"]))

    def test_f_horary_only_is_preserved(self):
        result = build_cross_interpretation(horary_fixture("B"), None)
        self.assertEqual(result["cross"]["relationship"], "insufficient")
        self.assertEqual(result["horary"]["conclusion"]["band"], "B")
        self.assertIsNone(result["prashna"])

    def test_g_prashna_only_is_preserved(self):
        result = build_cross_interpretation(None, prashna_fixture(("moon_in_event_house", 1, "Moon 사건 하우스")))
        self.assertEqual(result["cross"]["relationship"], "insufficient")
        self.assertIsNone(result["horary"])
        self.assertEqual(result["prashna"]["conclusion"]["support_band"], "mixed")

    def test_h_hallucination_guard_contract_and_fact_provenance(self):
        result = build_cross_interpretation(
            horary_fixture("D", reception="mutual_strong"),
            prashna_fixture(("subject_lord_dignity", 2, "대상 주인행성 존귀")),
        )
        encoded = json.dumps(result, ensure_ascii=False)
        self.assertIn("invented_aspect", result["ai_contract"]["forbidden"])
        self.assertIn("invented_house", result["ai_contract"]["forbidden"])
        self.assertIn("invented_reception", result["ai_contract"]["forbidden"])
        self.assertIn("probability", result["ai_contract"]["forbidden"])
        self.assertIn("exact_timing", result["ai_contract"]["forbidden"])
        self.assertNotIn("82%", encoded)
        self.assertTrue(all(row["source"] == "horary_v8" for row in result["horary"]["intention_disposition"]))
        self.assertTrue(all(row["source"] == "prashna_v1" for row in result["prashna"]["supporting_evidence"]))

    def test_inputs_are_not_mutated_and_scores_are_not_combined(self):
        horary = horary_fixture("A")
        prashna = prashna_fixture(("mutual_graha_drishti", 2, "상호 연결"))
        before = json.dumps([horary, prashna], sort_keys=True)
        result = build_cross_interpretation(horary, prashna)
        self.assertEqual(before, json.dumps([horary, prashna], sort_keys=True))
        self.assertFalse(result["independence_contract"]["score_combination_performed"])
        self.assertFalse(result["independence_contract"]["weighted_average_performed"])


if __name__ == "__main__":
    unittest.main()
