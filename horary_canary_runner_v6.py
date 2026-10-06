from __future__ import annotations

"""Child-process entry point for the isolated Horary V6 canary."""

import json
import sys


_ALLOWED_KEYS = {
    "question_text",
    "question_iso",
    "topic",
    "timezone_name",
    "place",
    "lat",
    "lon",
}


def main() -> int:
    raw = sys.stdin.read()
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise ValueError("canary payload must be an object")

    unknown = sorted(set(payload) - _ALLOWED_KEYS)
    if unknown:
        raise ValueError(f"unsupported canary fields: {unknown}")

    # Production routing first establishes the V5 base. V6 and the performance
    # layers then patch only this child interpreter.
    import horary_topic_routes_v3  # noqa: F401
    import horary_engine_v6 as v6
    import horary_balance_v31 as v31
    import horary_performance_v2 as perf2
    import horary_performance_v1 as perf1

    perf2.clear_caches()
    perf1.clear_caches()

    result = v31.compute_horary(**payload)
    engine = ((result.get("meta") or {}).get("horary_engine"))
    if engine != v6.VERSION:
        raise RuntimeError(f"unexpected canary engine: {engine!r}")

    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
