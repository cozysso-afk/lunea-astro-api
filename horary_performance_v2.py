from __future__ import annotations

"""Hotspot-only Horary performance layer V2.

The calculation contract is intentionally unchanged. This module only:
1) reuses identical scalar tropical-longitude evaluations,
2) evaluates the existing V6 station coarse grid as a vector batch, and
3) evaluates the existing Future Window orb-entry coarse grid as a vector batch.

Search horizons, sample spacing, thresholds, and refinement iteration counts are
left untouched. Scalar refinement still uses the existing engine functions.
"""

from collections import OrderedDict
from datetime import timedelta
from threading import RLock

import numpy as np

import astro_core as core
import horary_engine_v6 as v6
import horary_future_window_v2 as fw2


VERSION = "LUNEA_HORARY_PERFORMANCE_V2_HOTSPOT_BATCH"

_ORIGINAL_CORE_LON = core.get_tropical_ecliptic_lon
_ORIGINAL_NEXT_STATION = v6._next_station
_ORIGINAL_FIND_ORB_ENTRY = fw2._find_orb_entry

_LON_CACHE_MAXSIZE = 65536
_lon_cache: OrderedDict[tuple[str, float], float] = OrderedDict()
_lon_lock = RLock()
_lon_hits = 0
_lon_misses = 0


def _scalar_tt(time_obj) -> float:
    value = np.asarray(getattr(time_obj, "tt"))
    if value.shape != ():
        raise TypeError("non-scalar Skyfield Time")
    return float(value)


def _cached_core_lon(body_name, time_obj):
    """Return the exact first scalar evaluation for an identical body/TT key."""
    global _lon_hits, _lon_misses
    try:
        key = (str(body_name), _scalar_tt(time_obj))
    except Exception:
        return _ORIGINAL_CORE_LON(body_name, time_obj)

    with _lon_lock:
        cached = _lon_cache.get(key)
        if cached is not None:
            _lon_hits += 1
            _lon_cache.move_to_end(key)
            return cached

    value = float(_ORIGINAL_CORE_LON(body_name, time_obj))
    with _lon_lock:
        _lon_misses += 1
        _lon_cache[key] = value
        _lon_cache.move_to_end(key)
        while len(_lon_cache) > _LON_CACHE_MAXSIZE:
            _lon_cache.popitem(last=False)
    return value


def _motion_window_hours(body: str) -> float:
    if body == "Moon":
        return 0.25
    if body in {"Sun", "Mercury", "Venus", "Mars"}:
        return 1.0
    return 6.0


def _batch_speeds(body: str, times):
    """Same central-difference speed formula as astro_core.planet_motion."""
    if not times:
        return np.asarray([], dtype=float)
    h = _motion_window_hours(body)
    past = [dt - timedelta(hours=h) for dt in times]
    future = [dt + timedelta(hours=h) for dt in times]
    values = np.ravel(core.get_tropical_ecliptic_lons(body, past + future))
    n = len(times)
    if values.size != n * 2:
        raise ValueError(f"station vector size mismatch: body={body} values={values.size} n={n}")
    past_lons = values[:n]
    future_lons = values[n:]
    delta = (future_lons - past_lons + 180.0) % 360.0 - 180.0
    return np.ravel(delta / ((2.0 * h) / 24.0))


def _next_station_vector(body: str, row, dt_utc, horizon_days: float = 180.0):
    """V6 station search with the exact same coarse timestamps, batched."""
    step_hours = 3.0 if body in {"Moon", "Mercury", "Venus", "Mars"} else 8.0
    end = dt_utc + timedelta(days=float(horizon_days))
    times = [dt_utc]
    left = dt_utc
    while left < end:
        right = min(end, left + timedelta(hours=step_hours))
        times.append(right)
        left = right

    try:
        speeds = _batch_speeds(body, times)
    except Exception:
        return _ORIGINAL_NEXT_STATION(body, row, dt_utc, horizon_days=horizon_days)

    for index in range(1, len(times)):
        prev_speed = float(speeds[index - 1])
        speed = float(speeds[index])
        if (
            v6._motion_sign(prev_speed) == 0
            or v6._motion_sign(speed) == 0
            or v6._motion_sign(prev_speed) != v6._motion_sign(speed)
        ):
            exact = v6._refine_station(body, times[index - 1], times[index])
            return {
                "type": "station",
                "body": body,
                "body_ko": core.PLANET_KO.get(body, body),
                "utc": exact.isoformat(),
                "days_from_question": round((exact - dt_utc).total_seconds() / 86400.0, 6),
                "speed_before": round(v6._speed_at(body, exact - timedelta(hours=1)), 6),
                "speed_after": round(v6._speed_at(body, exact + timedelta(hours=1)), 6),
            }
    return None


def _aspect_errors_vector(body_a: str, body_b: str, angle: float, times):
    if not times:
        return np.asarray([], dtype=float)
    a_lons = np.asarray(core.get_tropical_ecliptic_lons(body_a, times), dtype=float)
    b_lons = np.asarray(core.get_tropical_ecliptic_lons(body_b, times), dtype=float)
    seps = np.abs((a_lons - b_lons + 180.0) % 360.0 - 180.0)
    return np.abs(seps - float(angle))


def _find_orb_entry_vector(body_a: str, body_b: str, angle: float, limit: float, start, end):
    """Future Window orb-entry search with unchanged grid/refinement semantics."""
    if end <= start:
        return None

    step = timedelta(minutes=30 if "Moon" in {body_a, body_b} else 60)
    times = [start]
    left = start
    while left < end:
        right = min(end, left + step)
        times.append(right)
        left = right

    try:
        errors = _aspect_errors_vector(body_a, body_b, angle, times)
    except Exception:
        return _ORIGINAL_FIND_ORB_ENTRY(body_a, body_b, angle, limit, start, end)

    if not len(errors):
        return None
    if float(errors[0]) <= float(limit) + 1e-9:
        return start

    crossing = None
    for index in range(1, len(times)):
        if float(errors[index - 1]) > float(limit) and float(errors[index]) <= float(limit):
            crossing = index
            break
    if crossing is None:
        return None

    lo, hi = times[crossing - 1], times[crossing]
    # Preserve the original 28-step scalar bisection exactly.
    for _ in range(28):
        mid = lo + (hi - lo) / 2
        if fw2._aspect_error(body_a, body_b, angle, mid) <= limit:
            hi = mid
        else:
            lo = mid
    return hi


def clear_caches() -> None:
    global _lon_hits, _lon_misses
    with _lon_lock:
        _lon_cache.clear()
        _lon_hits = 0
        _lon_misses = 0


def cache_info() -> dict:
    with _lon_lock:
        return {
            "longitude": {
                "size": len(_lon_cache),
                "maxsize": _LON_CACHE_MAXSIZE,
                "hits": _lon_hits,
                "misses": _lon_misses,
            }
        }


def install() -> bool:
    if getattr(core.get_tropical_ecliptic_lon, "_lunea_horary_perf_v2", False):
        return False

    _cached_core_lon._lunea_horary_perf_v2 = True
    _next_station_vector._lunea_horary_perf_v2 = True
    _find_orb_entry_vector._lunea_horary_perf_v2 = True

    core.get_tropical_ecliptic_lon = _cached_core_lon
    v6._next_station = _next_station_vector
    fw2._find_orb_entry = _find_orb_entry_vector
    return True


install()
