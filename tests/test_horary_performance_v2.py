from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import horary_topic_routes_v3  # noqa: F401 - install full production chain
import astro_core as core
import horary_engine_v5 as v5
import horary_engine_v6 as v6
import horary_performance_v1 as perf1
import horary_performance_v2 as perf2


class _FakeTime:
    def __init__(self, tt):
        self.tt = tt


class HoraryPerformanceV2Tests(unittest.TestCase):
    def setUp(self):
        perf2.clear_caches()
        perf1.clear_caches()

    def test_import_does_not_activate_future_window(self):
        self.assertNotIn("horary_future_window_v2", sys.modules)

    def test_shared_v5_request_cache_is_scoped_to_wrapper(self):
        original = perf2._ORIGINAL_COMPUTE_HORARY
        seen = {}

        def fake(*args, **kwargs):
            seen["lon_cache"] = v5._REQUEST_LON_CACHE.get()
            seen["prepared_cache"] = v5._PREPARED_GRID_CACHE.get()
            return {"ok": True}

        perf2._ORIGINAL_COMPUTE_HORARY = fake
        try:
            self.assertIsNone(v5._REQUEST_LON_CACHE.get())
            self.assertIsNone(v5._PREPARED_GRID_CACHE.get())
            result = perf2._compute_horary_with_shared_v5_cache()
            self.assertEqual(result, {"ok": True})
            self.assertIsInstance(seen["lon_cache"], dict)
            self.assertIsInstance(seen["prepared_cache"], dict)
            self.assertIsNone(v5._REQUEST_LON_CACHE.get())
            self.assertIsNone(v5._PREPARED_GRID_CACHE.get())
        finally:
            perf2._ORIGINAL_COMPUTE_HORARY = original

    def test_ingress_refinement_cache_is_request_local(self):
        calls = {"count": 0}
        start = datetime(2026, 10, 5, 9, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(minutes=30)

        def fake_refine(body, left, right, start_sign):
            calls["count"] += 1
            return right

        original_compute = perf2._ORIGINAL_COMPUTE_HORARY
        original_refine = perf2._ORIGINAL_REFINE_SIGN_INGRESS

        def fake_compute(*args, **kwargs):
            self.assertIsInstance(perf2._REFINE_INGRESS_CACHE.get(), dict)
            first = perf2._refine_sign_ingress_cached("Moon", start, end, 4)
            second = perf2._refine_sign_ingress_cached("Moon", start, end, 4)
            return first, second

        perf2._ORIGINAL_COMPUTE_HORARY = fake_compute
        perf2._ORIGINAL_REFINE_SIGN_INGRESS = fake_refine
        try:
            self.assertIsNone(perf2._REFINE_INGRESS_CACHE.get())
            first, second = perf2._compute_horary_with_shared_v5_cache()
            self.assertEqual(first, end)
            self.assertEqual(second, end)
            self.assertEqual(calls["count"], 1)
            self.assertIsNone(perf2._REFINE_INGRESS_CACHE.get())

            # Outside the advanced request wrapper, the optimization is off.
            perf2._refine_sign_ingress_cached("Moon", start, end, 4)
            self.assertEqual(calls["count"], 2)
        finally:
            perf2._ORIGINAL_COMPUTE_HORARY = original_compute
            perf2._ORIGINAL_REFINE_SIGN_INGRESS = original_refine

    def test_identical_scalar_longitude_is_reused_exactly(self):
        calls = {"count": 0}

        def fake(body, time_obj):
            calls["count"] += 1
            return 123.456789

        with patch.object(perf2, "_ORIGINAL_CORE_LON", side_effect=fake):
            first = perf2._cached_core_lon("Mercury", _FakeTime(2460000.125))
            second = perf2._cached_core_lon("Mercury", _FakeTime(2460000.125))

        self.assertEqual(first, second)
        self.assertEqual(calls["count"], 1)
        info = perf2.cache_info()["longitude"]
        self.assertEqual(info["misses"], 1)
        self.assertEqual(info["hits"], 1)

    def test_next_ingress_vector_keeps_original_event_contract(self):
        moment = datetime(2026, 10, 5, 9, 25, 23, tzinfo=timezone.utc)
        lon, speed, _ = core.planet_motion("Mercury", moment)
        row = {"longitude": float(lon), "speed_deg_per_day": float(speed)}

        scalar = perf2._ORIGINAL_NEXT_SIGN_INGRESS(
            "Mercury", row, moment, horizon_days=60.0
        )
        perf1.clear_caches()
        perf2.clear_caches()
        vector = perf2._next_sign_ingress_vector(
            "Mercury", row, moment, horizon_days=60.0
        )
        self.assertEqual(scalar, vector)

    def test_previous_ingress_vector_keeps_original_event_contract(self):
        moment = datetime(2026, 10, 5, 9, 25, 23, tzinfo=timezone.utc)
        lon, speed, _ = core.planet_motion("Mercury", moment)
        row = {"longitude": float(lon), "speed_deg_per_day": float(speed)}

        scalar = perf2._ORIGINAL_PREVIOUS_SIGN_INGRESS(
            "Mercury", row, moment, horizon_days=5.0
        )
        perf1.clear_caches()
        perf2.clear_caches()
        vector = perf2._previous_sign_ingress_vector(
            "Mercury", row, moment, horizon_days=5.0
        )
        self.assertEqual(scalar, vector)

    def test_station_vector_keeps_original_event_contract(self):
        moment = datetime(2026, 10, 5, 9, 25, 23, tzinfo=timezone.utc)
        lon, speed, _ = core.planet_motion("Mercury", moment)
        row = {"longitude": float(lon), "speed_deg_per_day": float(speed)}

        scalar = perf2._ORIGINAL_NEXT_STATION(
            "Mercury", row, moment, horizon_days=60.0
        )
        perf1.clear_caches()
        vector = perf2._next_station_vector(
            "Mercury", row, moment, horizon_days=60.0
        )
        self.assertEqual(scalar, vector)

    def test_moon_exact_events_prepared_keeps_original_contract(self):
        start = datetime(2026, 10, 5, 9, 25, 23, tzinfo=timezone.utc)
        end = start + timedelta(days=2)

        scalar = perf2._ORIGINAL_EXACT_EVENTS_BETWEEN(
            "Moon", "Venus", start, end
        )
        perf2.clear_caches()
        prepared = perf2._exact_events_between_moon_cached(
            "Moon", "Venus", start, end
        )
        self.assertEqual(scalar, prepared)

    def test_motion_probe_vector_matches_scalar_contract(self):
        moment = datetime(2026, 10, 5, 9, 25, 23, tzinfo=timezone.utc)
        a_lon, a_speed, _ = core.planet_motion("Mercury", moment)
        b_lon, b_speed, _ = core.planet_motion("Venus", moment)
        row_a = {"longitude": float(a_lon), "speed_deg_per_day": float(a_speed)}
        row_b = {"longitude": float(b_lon), "speed_deg_per_day": float(b_speed)}
        angle = 0.0
        current_orb = abs(core.angular_separation(float(a_lon), float(b_lon)) - angle)

        token = v6._CONTEXT_DT_UTC.set(moment)
        try:
            scalar = perf2._ORIGINAL_ACTUAL_OR_FALLBACK_MOTION(
                "Mercury", row_a, "Venus", row_b, angle, current_orb
            )
            vector = perf2._actual_or_fallback_motion_vector(
                "Mercury", row_a, "Venus", row_b, angle, current_orb
            )
        finally:
            v6._CONTEXT_DT_UTC.reset(token)

        self.assertEqual(scalar[2:], vector[2:])
        self.assertAlmostEqual(scalar[0], vector[0], places=12)
        self.assertAlmostEqual(scalar[1], vector[1], places=12)

    def test_orb_entry_vector_matches_scalar_search_and_refinement(self):
        import horary_future_window_v2 as fw2

        perf2.install_future_window()
        self.assertIsNotNone(perf2._ORIGINAL_FIND_ORB_ENTRY)
        self.assertIs(fw2._find_orb_entry, perf2._find_orb_entry_vector)

        start = datetime(2026, 10, 5, 9, 25, 23, tzinfo=timezone.utc)
        end = start + timedelta(days=30)
        args = ("Moon", "Venus", 0.0, 8.0, start, end)

        scalar = perf2._ORIGINAL_FIND_ORB_ENTRY(*args)
        perf2.clear_caches()
        vector = perf2._find_orb_entry_vector(*args)
        self.assertEqual(scalar, vector)


if __name__ == "__main__":
    unittest.main()
