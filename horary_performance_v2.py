from __future__ import annotations

"""Hotspot-only Horary performance layer V2.

The calculation contract is intentionally unchanged. This module only:
1) reuses identical scalar tropical-longitude evaluations,
2) evaluates the existing V6 sign-ingress/station coarse grids as vector batches, and
3) evaluates the existing Future Window orb-entry coarse grid as a vector batch.

Search horizons, sample spacing, thresholds, and refinement iteration counts are
left untouched. Scalar refinement still uses the existing engine functions.
"""

from collections import OrderedDict
from datetime import timedelta
import importlib
import sys
from threading import RLock

import numpy as np

import astro_core as core
import horary_engine_v6 as v6


VERSION = "LUNEA_HORARY_PERFORMANCE_V2_HOTSPOT_BATCH"

_ORIGINAL_CORE_LON = core.get_tropical_ecliptic_lon
_ORIGINAL_NEXT_SIGN_INGRESS = v6._next_sign_ingress
_ORIGINAL_PREVIOUS_SIGN_INGRESS = v6._previous_sign_ingress
_ORIGINAL_NEXT_STATION = v6._next_station
_ORIGINAL_FIND_ORB_ENTRY = None

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



def _forward_grid(dt_utc, horizon_days: float, step_hours: float):
    end = dt_utc + timedelta(days=float(horizon_days))
    out = [dt_utc]
    left = dt_utc
    step = timedelta(hours=float(step_hours))
    while left < end:
        right = min(end, left + step)
        out.append(right)
        left = right
    return out


def _backward_grid(dt_utc, horizon_days: float, step_hours: float):
    earliest = dt_utc - timedelta(days=float(horizon_days))
    out = [dt_utc]
    right = dt_utc
    step = timedelta(hours=float(step_hours))
    while right > earliest:
        left = max(earliest, right - step)
        out.append(left)
        right = left
    return out


def _next_sign_ingress_vector(body: str, row, dt_utc, horizon_days: float = 180.0):
    """V6 next-ingress search with identical timestamps, batched."""
    start_sign = int(float(row["longitude"]) // 30.0)
    speed = abs(float(row.get("speed_deg_per_day") or 0.0))
    step_hours = 0.5 if body == "Moon" else 2.0 if speed >= 0.5 else 6.0 if speed >= 0.08 else 12.0
    grid = _forward_grid(dt_utc, horizon_days, step_hours)
    if len(grid) < 2:
        return None

    try:
        lons = np.ravel(core.get_tropical_ecliptic_lons(body, grid[1:]))
        if lons.size != len(grid) - 1:
            raise ValueError("ingress vector size mismatch")
    except Exception:
        return _ORIGINAL_NEXT_SIGN_INGRESS(body, row, dt_utc, horizon_days=horizon_days)

    for index, lon in enumerate(lons, start=1):
        if int(float(lon) // 30.0) != start_sign:
            left, right = grid[index - 1], grid[index]
            exact = v6._refine_sign_ingress(body, left, right, start_sign)
            return {
                "type": "sign_ingress",
                "body": body,
                "body_ko": core.PLANET_KO.get(body, body),
                "utc": exact.isoformat(),
                "days_from_question": round((exact - dt_utc).total_seconds() / 86400.0, 6),
                "from_sign_index": start_sign,
                "to_sign_index": v6._sign_index_at(body, exact + timedelta(seconds=2)),
            }
    return None


def _previous_sign_ingress_vector(body: str, row, dt_utc, horizon_days: float = 5.0):
    """V6 previous-ingress search with identical timestamps, batched."""
    start_sign = int(float(row["longitude"]) // 30.0)
    speed = abs(float(row.get("speed_deg_per_day") or 0.0))
    step_hours = 0.5 if body == "Moon" else 3.0 if speed >= 0.5 else 8.0
    grid = _backward_grid(dt_utc, horizon_days, step_hours)
    if len(grid) < 2:
        return dt_utc - timedelta(days=float(horizon_days))

    try:
        lons = np.ravel(core.get_tropical_ecliptic_lons(body, grid[1:]))
        if lons.size != len(grid) - 1:
            raise ValueError("previous ingress vector size mismatch")
    except Exception:
        return _ORIGINAL_PREVIOUS_SIGN_INGRESS(body, row, dt_utc, horizon_days=horizon_days)

    for index, lon in enumerate(lons, start=1):
        if int(float(lon) // 30.0) != start_sign:
            lo, hi = grid[index], grid[index - 1]
            for _ in range(28):
                mid = lo + (hi - lo) / 2
                if v6._sign_index_at(body, mid) == start_sign:
                    hi = mid
                else:
                    lo = mid
            return hi
    return dt_utc - timedelta(days=float(horizon_days))

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


def _loaded_future_window_module():
    """Return Future Window only when another caller already installed it."""
    return sys.modules.get("horary_future_window_v2")


def _future_window_module():
    """Load Future Window only for code paths that explicitly need it."""
    module = _loaded_future_window_module()
    if module is None:
        module = importlib.import_module("horary_future_window_v2")
    return module


def _capture_original_find_orb_entry(module):
    global _ORIGINAL_FIND_ORB_ENTRY
    if _ORIGINAL_FIND_ORB_ENTRY is None:
        current = module._find_orb_entry
        if getattr(current, "_lunea_horary_perf_v2", False):
            raise RuntimeError("Future Window orb-entry original was not captured before patching")
        _ORIGINAL_FIND_ORB_ENTRY = current
    return _ORIGINAL_FIND_ORB_ENTRY


def _aspect_errors_vector(body_a: str, body_b: str, angle: float, times):
    if not times:
        return np.asarray([], dtype=float)
    a_lons = np.asarray(core.get_tropical_ecliptic_lons(body_a, times), dtype=float)
    b_lons = np.asarray(core.get_tropical_ecliptic_lons(body_b, times), dtype=float)
    seps = np.abs((a_lons - b_lons + 180.0) % 360.0 - 180.0)
    return np.abs(seps - float(angle))


def _find_orb_entry_vector(body_a: str, body_b: str, angle: float, limit: float, start, end):
    """Future Window orb-entry search with unchanged grid/refinement semantics."""
    fw2 = _future_window_module()
    original_find_orb_entry = _capture_original_find_orb_entry(fw2)
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
        return original_find_orb_entry(body_a, body_b, angle, limit, start, end)

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


def install_future_window() -> bool:
    """Patch Future Window only if that optional layer is already loaded."""
    fw2 = _loaded_future_window_module()
    if fw2 is None:
        return False
    if getattr(fw2._find_orb_entry, "_lunea_horary_perf_v2", False):
        return False

    _capture_original_find_orb_entry(fw2)
    _find_orb_entry_vector._lunea_horary_perf_v2 = True
    fw2._find_orb_entry = _find_orb_entry_vector
    return True


def install() -> bool:
    changed = False
    if not getattr(core.get_tropical_ecliptic_lon, "_lunea_horary_perf_v2", False):
        _cached_core_lon._lunea_horary_perf_v2 = True
        _next_sign_ingress_vector._lunea_horary_perf_v2 = True
        _previous_sign_ingress_vector._lunea_horary_perf_v2 = True
        _next_station_vector._lunea_horary_perf_v2 = True

        core.get_tropical_ecliptic_lon = _cached_core_lon
        v6._next_sign_ingress = _next_sign_ingress_vector
        v6._previous_sign_ingress = _previous_sign_ingress_vector
        v6._next_station = _next_station_vector
        changed = True

    # Preserve the old full-chain behavior when Future Window was imported
    # before this module, without importing/activating Future Window for V6-only.
    return install_future_window() or changed


install()
