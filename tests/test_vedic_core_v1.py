import unittest

from vedic_core import compute_vedic_profile


class VedicCoreV1Tests(unittest.TestCase):
    def test_sidereal_lahiri_profile_contract(self):
        result = compute_vedic_profile(
            birth_date="1991-03-21",
            birth_time="07:26",
            timezone_name="Asia/Seoul",
            place="여수",
        )

        self.assertEqual(result["schema"], "LUNEA_VEDIC_PROFILE_V1")
        self.assertEqual(result["zodiac"], "sidereal")
        self.assertEqual(result["ayanamsha"]["mode"], "Lahiri")
        self.assertGreater(result["ayanamsha"]["degree"], 20.0)
        self.assertLess(result["ayanamsha"]["degree"], 27.0)

        d1 = result["d1_rashi"]
        self.assertIn(d1["lagna"]["rashi"], [
            "Mesha", "Vrishabha", "Mithuna", "Karka", "Simha", "Kanya",
            "Tula", "Vrishchika", "Dhanu", "Makara", "Kumbha", "Meena",
        ])
        self.assertEqual(len(d1["whole_sign_houses"]), 12)
        self.assertEqual(
            {"Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Rahu", "Ketu"},
            set(d1["planets"]),
        )
        for planet in d1["planets"].values():
            self.assertGreaterEqual(planet["whole_sign_house"], 1)
            self.assertLessEqual(planet["whole_sign_house"], 12)
            self.assertGreaterEqual(planet["nakshatra"]["pada"], 1)
            self.assertLessEqual(planet["nakshatra"]["pada"], 4)

        panchanga = result["panchanga"]
        self.assertGreaterEqual(panchanga["tithi"]["index"], 1)
        self.assertLessEqual(panchanga["tithi"]["index"], 30)
        self.assertGreaterEqual(panchanga["nakshatra"]["index"], 1)
        self.assertLessEqual(panchanga["nakshatra"]["index"], 27)
        self.assertGreaterEqual(panchanga["yoga"]["index"], 1)
        self.assertLessEqual(panchanga["yoga"]["index"], 27)

        provenance = result["provenance"]
        self.assertTrue(provenance["sidereal"])
        self.assertEqual(provenance["ayanamsha"], "Lahiri")
        self.assertEqual(provenance["node_policy"], "true_node")
        self.assertFalse(provenance["d9_navamsa"])
        self.assertFalse(provenance["vimshottari_dasha"])
        self.assertFalse(provenance["interpretation_generated"])

    def test_unknown_place_requires_coordinates(self):
        with self.assertRaisesRegex(ValueError, "출생지"):
            compute_vedic_profile(
                birth_date="1991-03-21",
                birth_time="07:26",
                timezone_name="Asia/Seoul",
                place="Atlantis",
            )


if __name__ == "__main__":
    unittest.main()
