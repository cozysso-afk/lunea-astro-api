from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import horary_topic_routes_v3  # noqa: F401 - install full production chain
import astro_core as core
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
