from __future__ import annotations

import sys
import unittest

import horary_topic_routes_v3  # noqa: F401 - installs production V4 -> V5
import horary_balance_v31 as v31

from horary_canary_v6 import compute_horary_v6_canary, shutdown_horary_v6_canary_worker


class HoraryV6CanaryIsolationTests(unittest.TestCase):
    def test_child_v6_does_not_mutate_parent_v5_route(self):
        payload = {
            "question_text": "이 일은 실제로 성사될까요?",
            "question_iso": "2026-09-04T15:00:00+09:00",
            "topic": "general",
            "timezone_name": "Asia/Seoul",
            "place": "현재 위치",
            "lat": 34.7594,
            "lon": 127.6530,
        }

        parent_compute = v31.compute_horary
        self.assertNotIn("horary_engine_v6", sys.modules)
        self.assertNotIn("horary_performance_v2", sys.modules)

        first = compute_horary_v6_canary(payload, timeout_seconds=90.0)
        second = compute_horary_v6_canary(payload, timeout_seconds=90.0)
        child = second["result"]

        self.assertTrue(first["worker_started"])
        self.assertFalse(second["worker_started"])
        self.assertGreater(first["worker_compute_seconds"], 0.0)
        self.assertGreater(second["worker_compute_seconds"], 0.0)
        self.assertEqual(child["schema"], "LUNEA_HORARY_V1")
        self.assertEqual(
            child["meta"]["horary_engine"],
            "LUNEA_HORARY_ENGINE_V6_STRICT_TRADITIONAL_CORE",
        )

        # V6/performance modules existed only in the child interpreter.
        self.assertIs(v31.compute_horary, parent_compute)
        self.assertNotIn("horary_engine_v6", sys.modules)
        self.assertNotIn("horary_performance_v2", sys.modules)

        parent = v31.compute_horary(**payload)
        self.assertEqual(
            parent["meta"]["horary_engine"],
            "LUNEA_HORARY_ENGINE_V5_MOIETY_SECT",
        )
        shutdown_horary_v6_canary_worker()


if __name__ == "__main__":
    unittest.main()
