from __future__ import annotations

import unittest

import astro_core as core
import horary_topic_routes_v3  # noqa: F401  # activates V4 -> V5 -> V6 -> V7
import horary_balance_v31 as v31
import horary_engine_v6 as v6
import horary_engine_v7 as v7


LAT = 34.7594
LON = 127.6530


def compute(question_iso: str, *, topic: str = "general", question: str = "이 일은 성사될까요?"):
    return v31.compute_horary(
        question_text=question,
        question_iso=question_iso,
        topic=topic,
        timezone_name="Asia/Seoul",
        place="현재 위치",
        lat=LAT,
        lon=LON,
    )


class HoraryEngineV7Tests(unittest.TestCase):
    def test_minor_dignity_prevents_false_peregrine_display(self):
        # Sagittarius is Fire; in a day chart Sun is the active triplicity ruler.
        row = {
            "longitude": 250.0,
            "sign_index": 8,
            "dignity": "peregrine",
            "dignity_ko": "무권위·페레그린",
        }
        profile = v7._essential_profile("Sun", row, True)
        self.assertIn("triplicity", profile["held_dignities"])
        self.assertEqual(profile["classification"], "minor_dignity")
        self.assertIn("트리플리시티", profile["label_ko"])
        self.assertGreater(profile["score"], 0)

    def test_moon_movement_is_not_automatically_question_support(self):
        base = {
            "significators": {
                "querent": {"ruler": "Saturn"},
                "quesited": {"ruler": "Sun"},
                "event": {"ruler": "Mars"},
            },
            "judgment_support": {
                "moon_course": {
                    "void_of_course": False,
                    "next_major_applying_aspect": {
                        "body": "Venus", "body_ko": "금성", "aspect": "trine", "aspect_ko": "삼분위"
                    },
                }
            },
        }
        row = v7._moon_relevance(base)
        self.assertTrue(row["movement_present"])
        self.assertFalse(row["question_relevant"])
        self.assertEqual(row["status"], "movement_only")

        base["judgment_support"]["moon_course"]["next_major_applying_aspect"] = {
            "body": "Sun", "body_ko": "태양", "aspect": "square", "aspect_ko": "사분위"
        }
        row = v7._moon_relevance(base)
        self.assertTrue(row["question_relevant"])
        self.assertEqual(row["status"], "relevant_frictional")
        self.assertEqual(row["tone"], "frictional")

    def test_direct_perfection_with_confirmed_obstruction_stays_two_facts(self):
        data = {
            "judgment_support": {
                "perfection": {"perfects": True},
                "primary_connection": {"traditional_valid_aspect": "sextile", "aspect": "sextile"},
                "traditional_core_v6": {
                    "evidence_grade": "A",
                    "evidence_grade_ko": "A등급 · 주 시그니피케이터 직접 적용 성사",
                    "direct_axis": {
                        "perfection": {"perfects": True},
                        "aspect_state": {"traditional_valid_aspect": "sextile", "aspect": "sextile"},
                    },
                    "interventions": {
                        "prohibition_or_frustration": [
                            {"type": "prohibition", "classification": "confirmed_pattern"}
                        ],
                        "refranation": None,
                    },
                    "staged_judgment": {"direct_perfection": "있음", "overall_ko": "직접 성사"},
                },
            }
        }
        core_v6 = v7._qualify_core(data, {"label_ko": "질문축 적용각 있음"})
        self.assertEqual(core_v6["qualified_evidence_grade_v7"], "A_WITH_CONFIRMED_OBSTRUCTION")
        self.assertEqual(core_v6["confirmed_obstruction_count_v7"], 1)
        self.assertIn("단순 YES", core_v6["staged_judgment"]["overall_ko"])
        self.assertIn("확인된 선행 방해", core_v6["staged_judgment"]["direct_perfection"])

    def test_moiety_boundary_is_inclusive_then_outside(self):
        # Saturn moiety 4.5 + Sun moiety 7.5 = 12.0 degrees.
        saturn = {"longitude": 0.0, "speed_deg_per_day": 0.0, "sign_index": 0}
        exact_limit = {"longitude": 132.0, "speed_deg_per_day": -1.0, "sign_index": 4}
        outside = {"longitude": 132.001, "speed_deg_per_day": -1.0, "sign_index": 4}

        at_limit = v6._strict_aspect_state("Saturn", saturn, "Sun", exact_limit)
        self.assertEqual(at_limit["closest_geometric_aspect"]["aspect"], "trine")
        self.assertAlmostEqual(at_limit["max_orb"], 12.0, places=6)
        self.assertTrue(at_limit["within_orb"])
        self.assertEqual(at_limit["traditional_valid_aspect"], "trine")

        beyond = v6._strict_aspect_state("Saturn", saturn, "Sun", outside)
        self.assertFalse(beyond["within_orb"])
        self.assertIsNone(beyond["traditional_valid_aspect"])
        self.assertTrue(beyond["traditional_state"].startswith("out_of_orb_"))

    def test_topic_route_contracts_are_valid_and_match_real_payloads(self):
        # Static contract: every configured route must resolve to legal houses.
        for topic, spec in core.HORARY_TOPIC_SPECS.items():
            with self.subTest(topic=topic):
                self.assertIn(int(spec["quesited_house"]), range(1, 13))
                if spec.get("event_house") is not None:
                    self.assertIn(int(spec["event_house"]), range(1, 13))

        expected = {
            "contact": (7, 9),
            "lost_object": (2, None),
            "friend": (11, None),
            "travel": (9, None),
            "contract": (7, 3),
            "pet": (6, None),
            "children": (5, None),
            "shared_money": (8, None),
            "hidden": (12, None),
        }
        for topic, (qhouse, ehouse) in expected.items():
            with self.subTest(topic=topic):
                data = compute("2026-09-05T18:11:00+09:00", topic=topic, question=f"{topic} 라우팅 검산")
                route = data["judgment_support"]["route_contract_v7"]
                self.assertTrue(route["matches_spec"])
                self.assertEqual(route["quesited_house_actual"], qhouse)
                self.assertEqual(route["event_house_actual"], ehouse)

    def test_positive_negative_and_separating_states_are_all_reachable(self):
        soft = compute("2026-09-04T15:00:00+09:00")
        hard = compute("2026-09-06T15:00:00+09:00", question="어려움이 있어도 이 일은 성사될까요?")
        negative = compute(
            "2026-09-05T18:11:00+09:00",
            topic="contact",
            question="A는 2026년 9월 30일까지 나에게 먼저 사적인 연락을 해올까요?",
        )
        separating = compute("2026-09-05T01:00:00+09:00")

        self.assertTrue(soft["judgment_support"]["perfection"]["perfects"])
        self.assertTrue(hard["judgment_support"]["perfection"]["perfects"])
        self.assertFalse(negative["judgment_support"]["perfection"]["perfects"])
        self.assertFalse(separating["judgment_support"]["perfection"]["perfects"])
        self.assertEqual(separating["judgment_support"]["primary_connection"]["traditional_state"], "valid_separating")

        soft_grade = soft["judgment_support"]["traditional_core_v7"]["qualified_evidence_grade_v7"]
        hard_grade = hard["judgment_support"]["traditional_core_v7"]["qualified_evidence_grade_v7"]
        self.assertTrue(str(soft_grade).startswith("A"))
        self.assertTrue(str(hard_grade).startswith("A"))
        self.assertEqual(hard["judgment_support"]["traditional_core_v7"]["direct_aspect_tone_v7"], "frictional")
        self.assertNotEqual(negative["judgment_support"]["traditional_core_v7"]["qualified_evidence_grade_v7"], "A_CLEAR")

    def test_real_payload_exposes_v7_dignity_moon_route_and_bias_contracts(self):
        data = compute("2026-09-04T15:00:00+09:00")
        j = data["judgment_support"]
        self.assertEqual(data["meta"]["horary_engine"], v7.VERSION)
        self.assertEqual(j["traditional_core_v7"]["version"], v7.VERSION)
        self.assertEqual(set(j["essential_dignities_v7"]), set(core.HORARY_PLANETS))
        self.assertIn("moon_relevance_v7", j)
        self.assertIn("route_contract_v7", j)
        self.assertTrue(j["route_contract_v7"]["matches_spec"])
        self.assertTrue(j["bias_guard_v7"]["hard_aspect_is_not_automatic_no"])
        self.assertTrue(j["bias_guard_v7"]["moon_movement_is_not_automatically_question_support"])


if __name__ == "__main__":
    unittest.main()
