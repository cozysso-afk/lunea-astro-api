from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

import numpy as np

import astro_core as core
import horary_engine_v6 as v6
import horary_performance_v2 as perf


class HoraryPerformanceV2Test(unittest.TestCase):
    def test_motion_batch_matches_scalar_planet_motion(self):
        start = datetime(2026, 10, 5, 9, 25, tzinfo=timezone.utc)
        samples = [start + timedelta(hours=h) for h in (0, 3, 12, 24, 72)]
        for body in ("Moon", "Mercury", "Jupiter"):
            batched = perf._motion_speeds_batched(body, samples)
            scalar = np.asarray([core.planet_motion(body, dt)[1] for dt in samples], dtype=float)
            np.testing.assert_allclose(batched, scalar, rtol=0.0, atol=1e-9)

    def test_moon_next_ingress_matches_scalar_search(self):
        moment = datetime(2026, 10, 5, 9, 25, tzinfo=timezone.utc)
        lon, speed, _ = core.planet_motion("Moon", moment)
        row = {"longitude": lon, "speed_deg_per_day": speed}
        scalar = perf._ORIGINAL_NEXT_SIGN_INGRESS("Moon", row, moment, horizon_days=4.0)
        vector = perf._next_sign_ingress("Moon", row, moment, horizon_days=4.0)
        self.assertIsNotNone(scalar)
        self.assertIsNotNone(vector)
        self.assertEqual(vector["type"], scalar["type"])
        self.assertEqual(vector["body"], scalar["body"])
        self.assertEqual(vector["from_sign_index"], scalar["from_sign_index"])
        self.assertEqual(vector["to_sign_index"], scalar["to_sign_index"])
        self.assertEqual(vector["utc"], scalar["utc"])
        self.assertEqual(vector["days_from_question"], scalar["days_from_question"])

    def test_moon_previous_ingress_matches_scalar_search(self):
        moment = datetime(2026, 10, 5, 9, 25, tzinfo=timezone.utc)
        lon, speed, _ = core.planet_motion("Moon", moment)
        row = {"longitude": lon, "speed_deg_per_day": speed}
        scalar = perf._ORIGINAL_PREVIOUS_SIGN_INGRESS("Moon", row, moment, horizon_days=4.0)
        vector = perf._previous_sign_ingress("Moon", row, moment, horizon_days=4.0)
        self.assertEqual(vector, scalar)

    def test_station_coarse_scan_uses_one_vector_ephemeris_call(self):
        moment = datetime(2026, 10, 5, 9, 25, tzinfo=timezone.utc)
        row = {"longitude": 100.0, "speed_deg_per_day": 1.0}
        calls = []

        def fake_lons(body, times):
            times = list(times)
            calls.append((body, len(times)))
            return np.asarray([
                (100.0 + (dt - moment).total_seconds() / 86400.0) % 360.0
                for dt in times
            ], dtype=float)

        with patch.object(core, "get_tropical_ecliptic_lons", side_effect=fake_lons):
            result = perf._next_station("Mercury", row, moment, horizon_days=2.0)

        self.assertIsNone(result)
        self.assertEqual(len(calls), 1, "coarse station scan must be one vector ephemeris batch")
        self.assertGreater(calls[0][1], 3, "batch should contain the full preserved search grid")

    def test_install_preserves_v6_threshold_constants(self):
        self.assertEqual(v6.ASPECT_EXACT_TOL, 0.15)
        self.assertEqual(v6.ASPECT_MOTION_EPS, 0.0025)
        self.assertEqual(v6.STATION_SPEED_EPS, 0.003)
        self.assertEqual(perf.VERSION, "LUNEA_HORARY_PERFORMANCE_V2_VECTOR_SCAN")


if __name__ == "__main__":
    unittest.main()
