from __future__ import annotations

import cProfile
import pstats
import time

import astro_core as core
import horary_topic_routes_v3  # noqa: F401 - install production Horary chain
import horary_balance_v31 as v31
import horary_performance_v1 as perf


LAT = 34.7594
LON = 127.6530


def run_one():
    return v31.compute_horary(
        question_text="A는 2026년 10월 31일까지 나에게 먼저 사적인 연락을 해올까요?",
        question_iso="2026-10-05T18:25:23+09:00",
        topic="contact",
        timezone_name="Asia/Seoul",
        place="현재 위치",
        lat=LAT,
        lon=LON,
    )


def main() -> None:
    # Exclude one-time network/download startup from the calculation profile.
    core.load_ephemeris()
    perf.clear_caches()

    profiler = cProfile.Profile()
    started = time.perf_counter()
    profiler.enable()
    data = run_one()
    profiler.disable()
    elapsed = time.perf_counter() - started

    assert data.get("schema") == "LUNEA_HORARY_V1"
    support = data.get("judgment_support") or {}
    assert support.get("horary_v2")

    print(f"HORARY_PROFILE_TOTAL_SECONDS={elapsed:.6f}")
    print("HORARY_PROFILE_TOP_CUMULATIVE")
    stats = pstats.Stats(profiler).strip_dirs().sort_stats("cumulative")
    stats.print_stats(80)

    rows = []
    for (filename, lineno, funcname), values in stats.stats.items():
        cc, nc, tt, ct, callers = values
        if not (
            filename.startswith("horary_")
            or filename == "astro_core.py"
            or "/horary_" in filename
            or filename.endswith("/astro_core.py")
        ):
            continue
        rows.append((ct, tt, nc, filename, lineno, funcname))

    print("HORARY_PROFILE_PROJECT_TOP")
    for ct, tt, nc, filename, lineno, funcname in sorted(rows, reverse=True)[:50]:
        print(
            f"cum={ct:.6f}s self={tt:.6f}s calls={nc} "
            f"{filename}:{lineno} {funcname}"
        )


if __name__ == "__main__":
    main()
