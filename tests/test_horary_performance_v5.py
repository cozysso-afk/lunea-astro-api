from __future__ import annotations

import time
import unittest

import horary_topic_routes_v3  # noqa: F401 - installs production V4 -> V5 chain
import horary_balance_v31 as v31
import horary_performance_v5 as perf


CASES = [
    {
        "question_text": "운영 Horary V5 performance equality general",
        "question_iso": "2026-10-06T18:35:00+09:00",
        "topic": "general",
        "timezone_name": "Asia/Seoul",
        "place": "여수",
    },
    {
        "question_text": "A는 이번 달 안에 먼저 연락할까?",
        "question_iso": "2026-10-05T18:25:23+09:00",
        "topic": "contact",
        "timezone_name": "Asia/Seoul",
        "place": "현재 위치",
        "lat": 34.7594,
        "lon": 127.6530,
    },
]


class HoraryPerformanceV5Tests(unittest.TestCase):
    def _compute(self, case):
        return v31.compute_horary(**case)

    def test_optimized_output_is_exactly_equal_to_unoptimized_v5(self):
        for case in CASES:
            with self.subTest(topic=case["topic"]):
                perf.uninstall()
                perf.clear_caches()
                baseline = self._compute(case)

                perf.install()
                perf.clear_caches()
                optimized = self._compute(case)

                self.assertEqual(optimized, baseline)
                self.assertEqual(
                    (optimized.get("meta") or {}).get("horary_engine"),
                    "LUNEA_HORARY_ENGINE_V5_MOIETY_SECT",
                )
                judgment = optimized.get("judgment_support") or {}
                self.assertNotIn("traditional_core_v6", judgment)
                self.assertNotIn("traditional_core_v7", judgment)
                self.assertNotIn("traditional_core_v8", judgment)
                self.assertNotIn("future_window_v2", judgment)
                self.assertNotIn("horary_v2", judgment)

        perf.install()

    def test_performance_layer_records_reuse_without_policy_modules(self):
        perf.install()
        perf.clear_caches()

        started = time.perf_counter()
        first = self._compute(CASES[0])
        first_elapsed = time.perf_counter() - started

        started = time.perf_counter()
        second = self._compute(CASES[0])
        second_elapsed = time.perf_counter() - started

        self.assertEqual(first, second)
        info = perf.cache_info()
        self.assertEqual(info["version"], "LUNEA_HORARY_PERFORMANCE_V5_SAFE_CACHE_BATCH")
        self.assertGreater(info["balanced_perfection"]["hits"], 0)
        self.assertGreater(info["vector_longitude"]["hits"], 0)

        print(f"HORARY_V5_PERF_FIRST_SECONDS={first_elapsed:.6f}")
        print(f"HORARY_V5_PERF_SECOND_SECONDS={second_elapsed:.6f}")
        print(f"HORARY_V5_PERF_CACHE={info}")


if __name__ == "__main__":
    unittest.main()
