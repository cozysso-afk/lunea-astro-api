from __future__ import annotations

import unittest
from datetime import datetime, timezone

import swisseph as swe

import astro_core as core
import horary_topic_routes_v3  # noqa: F401  # activates V4 + V5 + strict V6 chain
import horary_balance_v31 as v31


UTC = timezone.utc
SWEPH_PLANETS = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mercury": swe.MERCURY,
    "Venus": swe.VENUS,
    "Mars": swe.MARS,
    "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN,
}


def angular_error(a, b):
    return abs((float(a) - float(b) + 180.0) % 360.0 - 180.0)


def swiss_lon_speed(body, dt_utc):
    jd = core.to_jd_ut(dt_utc)
    values, _ = swe.calc_ut(jd, SWEPH_PLANETS[body], swe.FLG_SWIEPH | swe.FLG_SPEED)
    return float(values[0] % 360.0), float(values[3])


class HoraryEngineV5Tests(unittest.TestCase):
    def test_planetary_moiety_orbs_replace_aspect_type_limits(self):
        # V5 owns the Lilly-style moiety policy even though production output is
        # wrapped by V6. Pair limit is the sum of the two planetary moieties.
        self.assertAlmostEqual(core._horary_aspect_limit("Sun", "Moon", "square"), 13.75, places=6)
        self.assertAlmostEqual(core._horary_aspect_limit("Mercury", "Venus", "sextile"), 7.0, places=6)
        self.assertAlmostEqual(core._horary_aspect_limit("Mars", "Saturn", "opposition"), 8.25, places=6)
        self.assertAlmostEqual(
            core._horary_aspect_limit("Moon", "Saturn", "trine"),
            core._horary_aspect_limit("Moon", "Saturn", "conjunction"),
            places=6,
        )

    def test_kst_question_moment_golden_anchor_prevents_nine_hour_shift(self):
        result = v31.compute_horary(
            question_text="현재 쿨픽스가 집 안에 있다면 어느 수납 범주가 가장 강한가?",
            question_iso="2026-09-05T07:07",
            topic="lost_object",
            timezone_name="Asia/Seoul",
            place="여수",
        )

        self.assertEqual(result["moment"]["utc_iso"], "2026-09-04T22:07:00+00:00")
        self.assertAlmostEqual(result["angles"]["ASC"]["longitude"], 174.515708, places=3)
        self.assertAlmostEqual(result["angles"]["MC"]["longitude"], 83.989000, places=3)
        self.assertAlmostEqual(result["cusps"][0], 174.515708, places=3)
        self.assertAlmostEqual(result["cusps"][9], 83.989000, places=3)

        self.assertLess(angular_error(result["planets"]["Sun"]["longitude"], 162.390095), 0.12)
        self.assertLess(angular_error(result["planets"]["Moon"]["longitude"], 80.259002), 0.12)

        # Production is now V6, while V5's moiety/sect policies remain visible
        # in metadata and must survive the wrapper chain.
        self.assertEqual(result["meta"]["horary_engine"], "LUNEA_HORARY_ENGINE_V6_STRICT_TRADITIONAL_CORE")
        self.assertEqual(result["meta"]["aspect_orb_policy"]["method"], "planetary_moiety_sum")
        self.assertFalse(result["meta"]["sect"]["fallback"])

    def test_sect_uses_actual_solar_altitude_and_drives_fortune_formula(self):
        day = v31.compute_horary(
            question_text="오늘 오전 상황은 어떤가?",
            question_iso="2026-09-05T10:00",
            topic="general",
            timezone_name="Asia/Seoul",
            place="여수",
        )
        night = v31.compute_horary(
            question_text="오늘 새벽 상황은 어떤가?",
            question_iso="2026-09-05T02:00",
            topic="general",
            timezone_name="Asia/Seoul",
            place="여수",
        )

        self.assertTrue(day["meta"]["sect"]["day_chart"])
        self.assertGreater(day["meta"]["sect"]["sun_altitude_deg"], 0.0)
        self.assertTrue(day["points"]["PartOfFortune"]["formula"].startswith("day:"))

        self.assertFalse(night["meta"]["sect"]["day_chart"])
        self.assertLess(night["meta"]["sect"]["sun_altitude_deg"], 0.0)
        self.assertTrue(night["points"]["PartOfFortune"]["formula"].startswith("night:"))
        self.assertEqual(
            night["points"]["PartOfFortune"]["sect_source"],
            "topocentric_sun_altitude_geometric_horizon",
        )

    def test_skyfield_vs_swiss_ephemeris_golden_grid(self):
        # Independent ephemeris cross-check over multiple seasons/years.
        epochs = [
            datetime(2025, 1, 15, 0, 0, tzinfo=UTC),
            datetime(2025, 4, 2, 6, 30, tzinfo=UTC),
            datetime(2025, 7, 19, 12, 45, tzinfo=UTC),
            datetime(2025, 10, 28, 18, 15, tzinfo=UTC),
            datetime(2026, 2, 7, 3, 20, tzinfo=UTC),
            datetime(2026, 5, 23, 9, 10, tzinfo=UTC),
            datetime(2026, 9, 4, 22, 7, tzinfo=UTC),
            datetime(2026, 12, 16, 15, 55, tzinfo=UTC),
        ]

        for dt in epochs:
            for body in core.HORARY_PLANETS:
                with self.subTest(epoch=dt.isoformat(), body=body):
                    sky_lon, sky_speed, sky_direction = core.planet_motion(body, dt)
                    swiss_lon, swiss_speed = swiss_lon_speed(body, dt)
                    self.assertLess(
                        angular_error(sky_lon, swiss_lon),
                        0.12,
                        f"{body} longitude mismatch at {dt.isoformat()}",
                    )
                    speed_tol = 0.20 if body == "Moon" else 0.08
                    self.assertLess(
                        abs(float(sky_speed) - swiss_speed),
                        speed_tol,
                        f"{body} speed mismatch at {dt.isoformat()}",
                    )
                    if abs(swiss_speed) >= 0.03:
                        expected = "순행" if swiss_speed > 0 else "역행"
                        self.assertEqual(sky_direction, expected)


if __name__ == "__main__":
    unittest.main()
