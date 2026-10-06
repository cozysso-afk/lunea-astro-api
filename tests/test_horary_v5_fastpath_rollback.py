from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import astro_core as core
import horary_topic_routes_v3  # noqa: F401 - installs production V4 -> V5 chain
import horary_balance_v31 as v31


QUESTION = "A는 2026년 10월 31일까지 나에게 먼저 사적인 연락을 해올까요?"
QUESTION_ISO = "2026-10-05T18:25:23+09:00"


def main() -> None:
    core.load_ephemeris()
    started = time.perf_counter()
    data = v31.compute_horary(
        question_text=QUESTION,
        question_iso=QUESTION_ISO,
        topic="contact",
        timezone_name="Asia/Seoul",
        place="현재 위치",
        lat=34.7594,
        lon=127.6530,
    )
    elapsed = time.perf_counter() - started

    assert data.get("schema") == "LUNEA_HORARY_V1"
    assert (data.get("meta") or {}).get("horary_engine") == "LUNEA_HORARY_ENGINE_V5_MOIETY_SECT"

    judgment_support = data.get("judgment_support") or {}
    assert "traditional_core_v6" not in judgment_support
    assert "traditional_core_v7" not in judgment_support
    assert "traditional_core_v8" not in judgment_support
    assert "future_window_v2" not in judgment_support
    assert "horary_v2" not in judgment_support

    print(f"HORARY_V5_ROLLBACK_SECONDS={elapsed:.6f}")
    print(f"HORARY_V5_ROLLBACK_ENGINE={(data.get('meta') or {}).get('horary_engine')}")
    assert elapsed < 5.0, f"V5 rollback fast path regressed to {elapsed:.3f}s"


if __name__ == "__main__":
    main()
