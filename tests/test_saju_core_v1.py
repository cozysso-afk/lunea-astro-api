import unittest

from saju_core import compute_four_pillars


class SajuCoreV1Tests(unittest.TestCase):
    def test_known_korean_birth_has_expected_year_and_solar_term_month(self):
        result = compute_four_pillars(
            birth_date="1991-03-21",
            birth_time="07:26",
            timezone_name="Asia/Seoul",
            place="여수",
        )

        self.assertEqual(result["engine"], "LUNEA_SAJU_FOUR_PILLARS_V1")
        self.assertEqual(result["pillars"]["year"]["hanja"], "辛未")
        self.assertEqual(result["pillars"]["year"]["hangul"], "신미")
        self.assertEqual(result["pillars"]["month"]["hanja"], "辛卯")
        self.assertEqual(result["pillars"]["month"]["hangul"], "신묘")
        self.assertEqual(sum(result["visible_elements"].values()), 8)
        self.assertEqual(result["pillars"]["day"]["ten_god_stem"], "일간")

        provenance = result["provenance"]
        self.assertEqual(provenance["timezone"], "Asia/Seoul")
        self.assertEqual(provenance["place_label"], "여수")
        self.assertTrue(provenance["solar_term_month_boundary"])
        self.assertFalse(provenance["true_solar_time_correction"])
        self.assertTrue(provenance["manual_override_supported"])

    def test_invalid_timezone_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone"):
            compute_four_pillars(
                birth_date="1991-03-21",
                birth_time="07:26",
                timezone_name="Mars/Olympus",
            )


if __name__ == "__main__":
    unittest.main()
