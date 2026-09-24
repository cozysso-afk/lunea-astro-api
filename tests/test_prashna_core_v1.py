import unittest

from prashna_core import compute_prashna


class PrashnaCoreV1Tests(unittest.TestCase):
    def test_contact_question_uses_independent_sidereal_chart_and_sunrise_vara(self):
        result = compute_prashna(
            question_text="그에게서 이번 추석 연휴기간 내에 먼저 연락이 올까?",
            question_iso="2026-09-24T15:09:00",
            topic="contact",
            timezone_name="Asia/Seoul",
            place="여수",
        )

        self.assertEqual(result["schema"], "LUNEA_PRASHNA_V1")
        self.assertEqual(result["zodiac"], "sidereal")
        self.assertEqual(result["ayanamsha"]["mode"], "Lahiri")
        self.assertTrue(result["provenance"]["independent_from_tropical_horary"])
        self.assertFalse(result["provenance"]["western_tropical_positions_reused"])

        # 2026-09-24 15:09 KST is Thursday and is well after local sunrise.
        vara = result["panchanga"]["vara"]
        self.assertEqual(vara["name"], "Guruvara")
        self.assertEqual(vara["label_ko"], "목요일")
        self.assertEqual(vara["boundary"], "local_sunrise")
        self.assertEqual(vara["vedic_day_date"], "2026-09-24")
        self.assertFalse(vara["query_before_today_sunrise"])
        self.assertIsNotNone(vara["today_sunrise_local"])

        # Tropical Sun is just inside Libra on this date; Lahiri sidereal must not reuse it.
        self.assertEqual(result["d1_rashi"]["planets"]["Sun"]["rashi"], "Kanya")

        judgment = result["judgment_support"]
        self.assertEqual(judgment["rule_set"], "LUNEA_PRASHNA_RULESET_V1")
        self.assertEqual(judgment["route"]["subject_house"], 7)
        self.assertEqual(judgment["route"]["event_house"], 9)
        self.assertIn(judgment["support_band"], {"strong", "mixed", "weak"})
        self.assertFalse(judgment["binary_outcome_generated"])

    def test_pre_sunrise_question_keeps_previous_vedic_weekday(self):
        result = compute_prashna(
            question_text="새벽 질문 테스트",
            question_iso="2026-09-24T03:00:00",
            topic="general",
            timezone_name="Asia/Seoul",
            place="여수",
        )
        vara = result["panchanga"]["vara"]
        self.assertTrue(vara["query_before_today_sunrise"])
        self.assertEqual(vara["vedic_day_date"], "2026-09-23")
        self.assertEqual(vara["name"], "Budhavara")
        self.assertEqual(vara["label_ko"], "수요일")

    def test_unknown_place_requires_coordinates(self):
        with self.assertRaisesRegex(ValueError, "출생지"):
            compute_prashna(
                question_text="테스트",
                question_iso="2026-09-24T15:09:00",
                topic="general",
                timezone_name="Asia/Seoul",
                place="Atlantis",
            )


if __name__ == "__main__":
    unittest.main()
