from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import astro_core as core
import horary_balance_v31 as v31


def planet(lon, speed=1.0, house=1):
    return {
        "longitude": float(lon),
        "sign_index": int(float(lon) // 30),
        "speed_deg_per_day": float(speed),
        "house": int(house),
    }


def pattern_data(primary=None, connection=None):
    q = planet(45.0, 1.2, 1)   # Venus
    t = planet(135.0, 0.7, 7)  # Mars
    return {
        "moment": {"utc_iso": "2026-09-02T00:00:00+00:00"},
        "planets": {
            "Sun": planet(165.0, 0.98, 9),
            "Venus": q,
            "Mars": t,
            "Moon": planet(210.0, 13.0, 2),
            "Mercury": planet(170.0, 1.5, 9),
            "Jupiter": planet(120.0, 0.08, 6),
            "Saturn": planet(10.0, 0.04, 12),
        },
        "significators": {
            "querent": {"ruler": "Venus", "planet": q},
            "quesited": {"ruler": "Mars", "planet": t},
            "event": None,
        },
        "judgment_support": {
            "perfection": primary or {
                "perfects": False,
                "indeterminate": True,
                "reason": "extended_horizon_no_perfection",
                "aspect": {"aspect": "trine"},
            },
            "primary_connection": connection or {
                "phase": "out_of_orb",
                "orb": 20.0,
                "relative_speed_deg_per_day": 0.5,
            },
            "reception": {
                "same_significator": False,
                "mutual_reception": False,
                "has_reception": False,
            },
            "moon_course": {"void_of_course": False, "next_aspects": []},
            "potential_prohibition": [],
            "balance_v3": {
                "version": "LUNEA_HORARY_BALANCE_V3",
                "tier": "open_indeterminate",
                "headline_ko": "직접 판정이 유보됨",
                "supporting_evidence_ko": [],
                "movement_evidence_ko": [],
                "constraints_ko": [],
                "support_score": 0.0,
                "constraint_score": 0.45,
                "reception_grade": {"grade": "none", "weight": 0.0},
                "primary_aspect_tone": "supportive",
            },
        },
    }


class HoraryBalanceV31Tests(unittest.TestCase):
    def test_triplicity_term_face_are_detected_without_promoting_to_major(self):
        trip = v31._reception_side("Venus", planet(250.0), "Sun", True)  # Sagittarius, day-fire ruler Sun
        self.assertIn("triplicity", trip["dignities"])
        self.assertNotIn("domicile", trip["dignities"])
        self.assertNotIn("exaltation", trip["dignities"])
        self.assertEqual(trip["strongest"], 3)

        term = v31._reception_side("Venus", planet(14.0), "Mercury", True)  # Aries 14° Egyptian Mercury term
        self.assertIn("term", term["dignities"])
        self.assertEqual(term["strongest"], 2)

        face = v31._reception_side("Sun", planet(35.0), "Mercury", True)  # Taurus first face Mercury
        self.assertIn("face", face["dignities"])
        self.assertEqual(face["strongest"], 1)

    def test_translation_of_light_requires_separation_then_application(self):
        data = pattern_data()
        moon = data["planets"]["Moon"]
        venus = data["planets"]["Venus"]
        mars = data["planets"]["Mars"]

        def state(a, _ar, b, _br):
            pair = {a, b}
            if pair == {"Moon", "Venus"}:
                return {"phase": "separating", "aspect": "sextile", "within_orb": True}
            if pair == {"Moon", "Mars"}:
                return {"phase": "applying", "aspect": "trine", "within_orb": True}
            return {"phase": "out_of_orb", "aspect": "square", "within_orb": False}

        def perfection(a, _ar, b, _br, *_args):
            if {a, b} == {"Moon", "Mars"}:
                return {
                    "perfects": True,
                    "days_from_question": 1.2,
                    "started_within_orb": True,
                    "aspect": {"aspect": "trine"},
                }
            return {"perfects": False}

        with patch.object(core, "_horary_aspect_state", side_effect=state), \
             patch.object(v31.v3, "_balanced_perfection_candidate", side_effect=perfection):
            rows = v31._translation_candidates(data, "Asia/Seoul")

        self.assertTrue(rows)
        self.assertEqual(rows[0]["translator"], "Moon")
        self.assertEqual(rows[0]["from"], "Venus")
        self.assertEqual(rows[0]["to"], "Mars")
        self.assertFalse(rows[0]["frictional"])

    def test_collection_of_light_requires_slower_collector_and_two_applications(self):
        data = pattern_data()

        def state(*_args):
            return {"phase": "applying", "aspect": "sextile", "within_orb": True}

        def perfection(a, _ar, b, _br, *_args):
            if "Saturn" in {a, b} and "Venus" in {a, b}:
                return {
                    "perfects": True,
                    "days_from_question": 2.0,
                    "started_within_orb": True,
                    "aspect": {"aspect": "sextile"},
                }
            if "Saturn" in {a, b} and "Mars" in {a, b}:
                return {
                    "perfects": True,
                    "days_from_question": 3.0,
                    "started_within_orb": True,
                    "aspect": {"aspect": "trine"},
                }
            return {"perfects": False}

        # Limit planet set so Saturn is the only possible collector.
        data["planets"] = {
            "Sun": data["planets"]["Sun"],
            "Venus": data["planets"]["Venus"],
            "Mars": data["planets"]["Mars"],
            "Saturn": data["planets"]["Saturn"],
        }
        with patch.object(core, "_horary_aspect_state", side_effect=state), \
             patch.object(v31.v3, "_balanced_perfection_candidate", side_effect=perfection):
            rows = v31._collection_candidates(data, "Asia/Seoul")

        self.assertTrue(rows)
        self.assertEqual(rows[0]["collector"], "Saturn")
        self.assertEqual(rows[0]["span_days"], 1.0)
        self.assertFalse(rows[0]["frictional"])

    def test_prohibition_and_frustration_are_separated_from_potential_only(self):
        primary = {
            "perfects": True,
            "days_from_question": 5.0,
            "reason": "perfects",
            "aspect": {"aspect": "trine"},
        }
        data = pattern_data(primary=primary)

        def state(*_args):
            return {"phase": "applying", "aspect": "sextile", "within_orb": True}

        def perfection(a, _ar, b, _br, *_args):
            if "Moon" in {a, b} and "Mars" in {a, b}:
                return {
                    "perfects": True,
                    "days_from_question": 1.0,
                    "started_within_orb": True,
                    "aspect": {"aspect": "sextile"},
                }
            return {"perfects": False}

        data["planets"] = {
            "Sun": data["planets"]["Sun"],
            "Venus": data["planets"]["Venus"],
            "Mars": data["planets"]["Mars"],
            "Moon": data["planets"]["Moon"],
        }
        with patch.object(core, "_horary_aspect_state", side_effect=state), \
             patch.object(v31.v3, "_balanced_perfection_candidate", side_effect=perfection):
            rows = v31._confirmed_interventions(data, "Asia/Seoul")

        self.assertTrue(rows)
        self.assertEqual(rows[0]["type"], "prohibition")
        self.assertEqual(rows[0]["classification"], "confirmed_pattern")

        # A slow third body lets the main target reach it first: frustration.
        data["planets"]["Saturn"] = planet(10.0, 0.04, 12)
        data["planets"].pop("Moon")

        def perfection_frustration(a, _ar, b, _br, *_args):
            if "Saturn" in {a, b} and "Mars" in {a, b}:
                return {
                    "perfects": True,
                    "days_from_question": 1.0,
                    "started_within_orb": True,
                    "aspect": {"aspect": "sextile"},
                }
            return {"perfects": False}

        with patch.object(core, "_horary_aspect_state", side_effect=state), \
             patch.object(v31.v3, "_balanced_perfection_candidate", side_effect=perfection_frustration):
            rows = v31._confirmed_interventions(data, "Asia/Seoul")

        self.assertTrue(rows)
        self.assertEqual(rows[0]["type"], "frustration")

    def test_refranation_requires_applying_flow_and_actual_direction_change(self):
        primary = {
            "perfects": False,
            "indeterminate": True,
            "reason": "extended_horizon_no_perfection",
            "aspect": {"aspect": "trine"},
        }
        connection = {
            "phase": "applying",
            "aspect": "trine",
            "orb": 2.0,
            "relative_speed_deg_per_day": 0.5,
        }
        data = pattern_data(primary=primary, connection=connection)

        def motion(body, dt):
            if body == "Venus":
                return 0.0, -0.1, "역행"
            return 0.0, 0.7, "순행"

        with patch.object(core, "planet_motion", side_effect=motion):
            row = v31._refranation_pattern(data)

        self.assertIsNotNone(row)
        self.assertEqual(row["type"], "refranation")
        self.assertEqual(row["body"], "Venus")

    def test_indirect_perfection_can_create_support_without_direct_aspect(self):
        data = pattern_data()
        translation = [{
            "type": "translation_of_light",
            "translator": "Moon",
            "frictional": False,
        }]
        with patch.object(v31, "_translation_candidates", return_value=translation), \
             patch.object(v31, "_collection_candidates", return_value=[]), \
             patch.object(v31, "_confirmed_interventions", return_value=[]), \
             patch.object(v31, "_refranation_pattern", return_value=None):
            balance = v31._build_balance_v31(data, "Asia/Seoul")

        self.assertEqual(balance["tier"], "indirect_support")
        self.assertGreater(balance["support_score"], 0.0)
        self.assertEqual(balance["version"], v31.VERSION)

    def test_real_ephemeris_smoke(self):
        started = time.perf_counter()
        result = v31.compute_horary(
            question_text="그 사람과 다시 대화를 시작하고 관계를 회복할 수 있을까요?",
            question_iso="2026-09-02T12:00",
            topic="reconciliation",
            timezone_name="Asia/Seoul",
            lat=37.5665,
            lon=126.9780,
        )
        elapsed = time.perf_counter() - started
        self.assertEqual(result["schema"], "LUNEA_HORARY_V1")
        self.assertEqual(result["meta"]["horary_balance"], v31.VERSION)
        self.assertEqual(result["judgment_support"]["balance_v31"]["version"], v31.VERSION)
        self.assertIn("balance_v3", result["judgment_support"])
        self.assertIn("reception_v31", result["judgment_support"]["balance_v31"])
        self.assertIn("indirect_perfection", result["judgment_support"]["balance_v31"])
        self.assertIn("confirmed_obstructions", result["judgment_support"]["balance_v31"])
        print(
            "real Horary V3.1 smoke: "
            f"{elapsed:.3f}s · tier={result['judgment_support']['balance_v31']['tier']}"
        )


if __name__ == "__main__":
    unittest.main()
