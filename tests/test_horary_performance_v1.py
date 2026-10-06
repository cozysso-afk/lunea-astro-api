from __future__ import annotations

from datetime import datetime, timezone
import unittest

import horary_topic_routes_v3  # noqa: F401 - install full production Horary chain
import horary_engine_v6 as v6
import horary_performance_v1 as perf
import astro_jobs_v1 as jobs


class _FakeExecutor:
    def __init__(self):
        self.submissions = []

    def submit(self, fn, *args, **kwargs):
        self.submissions.append((fn, args, kwargs))
        return None


class HoraryPerformanceV1Tests(unittest.TestCase):
    def tearDown(self):
        perf.clear_caches()
        with jobs._lock:
            jobs._jobs.clear()

    def test_identical_station_scan_is_cached_and_result_is_isolated(self):
        original = perf._ORIGINAL_NEXT_STATION
        calls = {"count": 0}

        def fake(body, row, dt_utc, horizon_days=180.0):
            calls["count"] += 1
            return {
                "type": "station",
                "body": body,
                "utc": dt_utc.isoformat(),
                "horizon_days": float(horizon_days),
                "days_from_question": 12.0,
                "speed": float(row.get("speed_deg_per_day") or 0.0),
            }

        perf._ORIGINAL_NEXT_STATION = fake
        perf._cached_next_station.cache_clear()
        try:
            moment = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
            row = {"longitude": 123.456789, "speed_deg_per_day": 0.42}
            first = v6._next_station("Mercury", row, moment, horizon_days=30.0)
            first["body"] = "MUTATED"
            second = v6._next_station("Mercury", row, moment, horizon_days=30.0)

            self.assertEqual(calls["count"], 1)
            self.assertEqual(second["body"], "Mercury")
            self.assertIsNot(first, second)
            self.assertGreaterEqual(perf._cached_next_station.cache_info().hits, 1)
        finally:
            perf._ORIGINAL_NEXT_STATION = original
            perf._cached_next_station.cache_clear()

    def test_shorter_station_horizons_reuse_canonical_first_event(self):
        original = perf._ORIGINAL_NEXT_STATION
        calls = {"count": 0}

        def fake(body, row, dt_utc, horizon_days=180.0):
            calls["count"] += 1
            return {
                "type": "station",
                "body": body,
                "utc": dt_utc.isoformat(),
                "days_from_question": 20.0,
            }

        perf._ORIGINAL_NEXT_STATION = fake
        perf._cached_next_station.cache_clear()
        try:
            moment = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
            row = {"longitude": 123.456789, "speed_deg_per_day": 0.42}

            within = v6._next_station("Mercury", row, moment, horizon_days=30.0)
            too_short = v6._next_station("Mercury", row, moment, horizon_days=10.0)
            within_again = v6._next_station("Mercury", row, moment, horizon_days=60.0)

            self.assertEqual(calls["count"], 1)
            self.assertIsNotNone(within)
            self.assertIsNone(too_short)
            self.assertIsNotNone(within_again)
        finally:
            perf._ORIGINAL_NEXT_STATION = original
            perf._cached_next_station.cache_clear()

    def test_shorter_ingress_horizons_reuse_canonical_first_event(self):
        original = perf._ORIGINAL_NEXT_SIGN_INGRESS
        calls = {"count": 0}

        def fake(body, row, dt_utc, horizon_days=180.0):
            calls["count"] += 1
            return {
                "type": "sign_ingress",
                "body": body,
                "utc": dt_utc.isoformat(),
                "days_from_question": 7.0,
            }

        perf._ORIGINAL_NEXT_SIGN_INGRESS = fake
        perf._cached_next_sign_ingress.cache_clear()
        try:
            moment = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
            row = {"longitude": 123.456789, "speed_deg_per_day": 0.42}

            within = v6._next_sign_ingress("Mercury", row, moment, horizon_days=10.0)
            too_short = v6._next_sign_ingress("Mercury", row, moment, horizon_days=3.0)
            within_again = v6._next_sign_ingress("Mercury", row, moment, horizon_days=30.0)

            self.assertEqual(calls["count"], 1)
            self.assertIsNotNone(within)
            self.assertIsNone(too_short)
            self.assertIsNotNone(within_again)
        finally:
            perf._ORIGINAL_NEXT_SIGN_INGRESS = original
            perf._cached_next_sign_ingress.cache_clear()

    def test_identical_speed_probe_is_cached(self):
        original = perf._ORIGINAL_SPEED_AT
        calls = {"count": 0}

        def fake(body, dt_utc):
            calls["count"] += 1
            return 1.2345

        perf._ORIGINAL_SPEED_AT = fake
        perf._cached_speed_at.cache_clear()
        try:
            moment = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
            self.assertEqual(v6._speed_at("Mars", moment), 1.2345)
            self.assertEqual(v6._speed_at("Mars", moment), 1.2345)
            self.assertEqual(calls["count"], 1)
        finally:
            perf._ORIGINAL_SPEED_AT = original
            perf._cached_speed_at.cache_clear()

    def test_active_identical_horary_job_reuses_existing_job_id(self):
        old_executor = jobs._horary_executor
        fake_executor = _FakeExecutor()
        jobs._horary_executor = fake_executor
        payload = {
            "question_text": "이 계약은 성사될까요?",
            "question_iso": "2026-10-04T21:00:00+09:00",
            "topic": "contract",
            "timezone": "Asia/Seoul",
            "lat": 34.7594,
            "lon": 127.6530,
        }
        try:
            first = jobs.create_astro_job(jobs.AstroJobRequest(kind="horary", payload=payload))
            second = jobs.create_astro_job(jobs.AstroJobRequest(kind="horary", payload=dict(payload)))

            self.assertEqual(first["job_id"], second["job_id"])
            self.assertEqual(len(fake_executor.submissions), 1)

            changed = dict(payload)
            changed["question_text"] = "이 계약은 다음 달에 성사될까요?"
            third = jobs.create_astro_job(jobs.AstroJobRequest(kind="horary", payload=changed))
            self.assertNotEqual(first["job_id"], third["job_id"])
            self.assertEqual(len(fake_executor.submissions), 2)
        finally:
            jobs._horary_executor = old_executor

    def test_finished_job_does_not_block_intentional_recalculation(self):
        old_executor = jobs._horary_executor
        fake_executor = _FakeExecutor()
        jobs._horary_executor = fake_executor
        payload = {
            "question_text": "연락이 올까요?",
            "question_iso": "2026-10-04T21:05:00+09:00",
            "topic": "contact",
            "timezone": "Asia/Seoul",
        }
        try:
            first = jobs.create_astro_job(jobs.AstroJobRequest(kind="horary", payload=payload))
            with jobs._lock:
                jobs._jobs[first["job_id"]]["status"] = "done"
            second = jobs.create_astro_job(jobs.AstroJobRequest(kind="horary", payload=payload))

            self.assertNotEqual(first["job_id"], second["job_id"])
            self.assertEqual(len(fake_executor.submissions), 2)
        finally:
            jobs._horary_executor = old_executor


if __name__ == "__main__":
    unittest.main()
