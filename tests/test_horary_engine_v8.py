from __future__ import annotations

import unittest

import horary_topic_routes_v3  # noqa: F401  # activates V4 -> V5 -> V6 -> V7 -> V8
import horary_engine_v8 as v8


class HoraryEngineV8Tests(unittest.TestCase):
    def base_data(self, topic="contact", moon_body="Venus", moon_status="relevant_supportive", moon_tone="supportive"):
        return {
            "schema": "LUNEA_HORARY_V1",
            "question": {"topic": topic},
            "significators": {
                "querent": {"ruler": "Mercury", "house": 1},
                "quesited": {"ruler": "Venus", "house": 7},
                "event": {"ruler": "Mars", "house": 9 if topic == "contact" else 5},
            },
            "judgment_support": {
                "moon_relevance_v7": {
                    "status": moon_status,
                    "question_relevant": moon_status.startswith("relevant_"),
                    "tone": moon_tone,
                    "label_ko": "fixture",
                    "next_aspect": {"body": moon_body, "aspect": "trine"},
                }
            },
        }

    def base_core(self, grade="D", reception_grade="mutual_major"):
        return {
            "qualified_evidence_grade_v7": grade,
            "qualified_evidence_grade_ko_v7": grade,
            "direct_axis": {
                "perfection": {"perfects": grade.startswith("A")},
                "reception": {
                    "grade": reception_grade,
                    "weight": 2.4 if reception_grade == "mutual_major" else 0.0,
                },
            },
            "derived_event_axes": {},
            "indirect_perfection": {
                "translation_of_light": [],
                "collection_of_light": [],
            },
            "confirmed_obstruction_count_v7": 0,
        }

    def test_moon_to_quesited_is_narrow_c_level_event_testimony(self):
        data = self.base_data(topic="contact", moon_body="Venus")
        core = self.base_core(grade="D")
        result = v8._judgment_v8(data, core)
        self.assertEqual(result["grade_band_v8"], "C")
        self.assertEqual(result["qualified_evidence_grade_v8"], "C_MOON_TARGET_CLEAR")
        self.assertEqual(result["grade_source_v8"], "moon_co_significator_event_testimony")
        self.assertEqual(result["action_state_v8"]["state"], "lunar_contact_testimony")

    def test_moon_to_event_ruler_is_c_level_event_testimony(self):
        data = self.base_data(topic="reconciliation", moon_body="Mars")
        core = self.base_core(grade="D")
        result = v8._judgment_v8(data, core)
        self.assertEqual(result["qualified_evidence_grade_v8"], "C_MOON_EVENT_CLEAR")
        self.assertEqual(result["action_state_v8"]["state"], "lunar_reconciliation_testimony")

    def test_moon_to_querent_only_does_not_promote_reception_only_chart(self):
        data = self.base_data(topic="contact", moon_body="Mercury")
        core = self.base_core(grade="D")
        result = v8._judgment_v8(data, core)
        self.assertEqual(result["grade_band_v8"], "D")
        self.assertEqual(result["qualified_evidence_grade_v8"], "D")
        self.assertFalse(result["moon_event_testimony_v8"]["confirmed"])
        self.assertEqual(result["moon_event_testimony_v8"]["reason"], "moon_applies_to_querent_only")
        self.assertEqual(result["overall_state_v8"], "receptive_but_unperfected")

    def test_irrelevant_moon_does_not_promote(self):
        data = self.base_data(topic="contact", moon_body="Saturn", moon_status="movement_only")
        core = self.base_core(grade="D")
        result = v8._judgment_v8(data, core)
        self.assertEqual(result["grade_band_v8"], "D")
        self.assertFalse(result["moon_event_testimony_v8"]["confirmed"])

    def test_direct_a_is_never_downgraded_or_replaced(self):
        data = self.base_data(topic="reconciliation", moon_body="Mars")
        core = self.base_core(grade="A_CLEAR")
        result = v8._judgment_v8(data, core)
        self.assertEqual(result["qualified_evidence_grade_v8"], "A_CLEAR")
        self.assertEqual(result["grade_source_v8"], "v7_preserved")
        self.assertEqual(result["action_state_v8"]["state"], "direct_perfection")

    def test_existing_derived_event_c_is_preserved(self):
        data = self.base_data(topic="contact", moon_body="Saturn", moon_status="movement_only")
        core = self.base_core(grade="C")
        core["derived_event_axes"] = {
            "quesited_to_event": {"perfection": {"perfects": True}, "reception": {"grade": "none"}}
        }
        result = v8._judgment_v8(data, core)
        self.assertEqual(result["qualified_evidence_grade_v8"], "C")
        self.assertEqual(result["action_state_v8"]["state"], "contact_event_perfection")

    def test_reception_only_remains_unperfected_not_automatic_no(self):
        data = self.base_data(topic="reconciliation", moon_body="Saturn", moon_status="movement_only")
        core = self.base_core(grade="D", reception_grade="mutual_major")
        result = v8._judgment_v8(data, core)
        self.assertEqual(result["grade_band_v8"], "D")
        self.assertEqual(result["overall_state_v8"], "receptive_but_unperfected")
        self.assertTrue(result["interpretation_contract_v8"]["d_is_not_automatic_no"])
        self.assertEqual(result["action_state_v8"]["state"], "not_perfected")

    def test_confirmed_obstruction_remains_separate_fact(self):
        data = self.base_data(topic="contact", moon_body="Venus")
        core = self.base_core(grade="D")
        core["confirmed_obstruction_count_v7"] = 1
        result = v8._judgment_v8(data, core)
        self.assertEqual(result["grade_band_v8"], "C")
        self.assertEqual(result["overall_state_v8"], "event_supported_with_obstruction")


if __name__ == "__main__":
    unittest.main()
