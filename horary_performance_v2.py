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
from contextvars import ContextVar
from copy import deepcopy
from datetime import timedelta
from functools import lru_cache
import importlib
import sys
from threading import RLock

import numpy as np

import astro_core as core
import horary_balance_v31 as v31
import horary_engine_v5 as v5
import horary_engine_v6 as v6


VERSION = "LUNEA_HORARY_PERFORMANCE_V2_HOTSPOT_BATCH"

_ORIGINAL_CORE_LON = core.get_tropical_ecliptic_lon
_ORIGINAL_COMPUTE_HORARY = v31.compute_horary
_ORIGINAL_NEXT_SIGN_INGRESS = v6._next_sign_ingress
_ORIGINAL_PREVIOUS_SIGN_INGRESS = v6._previous_sign_ingress
_ORIGINAL_NEXT_STATION = v6._next_station
_ORIGINAL_REFINE_STATION = v6._refine_station
_ORIGINAL_REFINE_SIGN_INGRESS = v6._refine_sign_ingress
_ORIGINAL_STRICT_ASPECT_STATE = v6._strict_aspect_state
_ORIGINAL_EXACT_EVENTS_BETWEEN = v6._exact_events_between
_ORIGINAL_FIND_ORB_ENTRY = None

_LON_CACHE_MAXSIZE = 65536
_lon_cache: OrderedDict[tuple[str, float], float] = OrderedDict()
_lon_lock = RLock()
_lon_hits = 0
_lon_misses = 0
_REFINE_INGRESS_CACHE = ContextVar("lunea_v6_refine_ingress_cache", default=None)
_ASPECT_STATE_CACHE = ContextVar("lunea_v6_aspect_state_cache", default=None)
_refine_ingress_hits = 0
_refine_ingress_misses = 0
_aspect_state_hits = 0
_aspect_state_misses = 0


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



def _compute_horary_with_shared_v5_cache(*args, **kwargs):
    """Keep request-local V5/V6 performance caches alive through advanced layers."""
    lon_token = v5._REQUEST_LON_CACHE.set({})
    prepared_token = v5._PREPARED_GRID_CACHE.set({})
    ingress_token = _REFINE_INGRESS_CACHE.set({})
    aspect_token = _ASPECT_STATE_CACHE.set({})
    try:
        return _ORIGINAL_COMPUTE_HORARY(*args, **kwargs)
    finally:
        _ASPECT_STATE_CACHE.reset(aspect_token)
        _REFINE_INGRESS_CACHE.reset(ingress_token)
        v5._PREPARED_GRID_CACHE.reset(prepared_token)
        v5._REQUEST_LON_CACHE.reset(lon_token)


def _refine_sign_ingress_cached(body: str, left, right, start_sign: int):
    """Reuse only byte-identical ingress-refinement inputs inside one request."""
    global _refine_ingress_hits, _refine_ingress_misses
    cache = _REFINE_INGRESS_CACHE.get()
    if cache is None:
        return _ORIGINAL_REFINE_SIGN_INGRESS(body, left, right, start_sign)

    key = (
        str(body),
        left.isoformat(),
        right.isoformat(),
        int(start_sign),
    )
    cached = cache.get(key)
    if cached is not None:
        _refine_ingress_hits += 1
        return cached

    exact = _ORIGINAL_REFINE_SIGN_INGRESS(body, left, right, start_sign)
    _refine_ingress_misses += 1
    cache[key] = exact
    return exact


def _strict_aspect_state_cached(body_a, row_a, body_b, row_b):
    """Reuse identical strict aspect-state inputs only within one advanced request."""
    global _aspect_state_hits, _aspect_state_misses
    cache = _ASPECT_STATE_CACHE.get()
    if cache is None:
        return _ORIGINAL_STRICT_ASPECT_STATE(body_a, row_a, body_b, row_b)

    key = (
        str(body_a),
        float(row_a["longitude"]),
        float(row_a.get("speed_deg_per_day") or 0.0),
        str(body_b),
        float(row_b["longitude"]),
        float(row_b.get("speed_deg_per_day") or 0.0),
    )
    cached = cache.get(key)
    if cached is not None:
        _aspect_state_hits += 1
        return deepcopy(cached)

    result = _ORIGINAL_STRICT_ASPECT_STATE(body_a, row_a, body_b, row_b)
    _aspect_state_misses += 1
    cache[key] = deepcopy(result)
    return result

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
    """V6 next-ingress search on the same coarse timestamps, batched in chunks."""
    start_sign = int(float(row["longitude"]) // 30.0)
    speed = abs(float(row.get("speed_deg_per_day") or 0.0))
    step_hours = 0.5 if body == "Moon" else 2.0 if speed >= 0.5 else 6.0 if speed >= 0.08 else 12.0
    chunk_days = 3.0 if body == "Moon" else 10.0 if speed >= 0.5 else 30.0
    end = dt_utc + timedelta(days=float(horizon_days))
    cursor = dt_utc

    while cursor < end:
        chunk_end = min(end, cursor + timedelta(days=chunk_days))
        chunk_horizon_days = (chunk_end - cursor).total_seconds() / 86400.0
        grid = _forward_grid(cursor, chunk_horizon_days, step_hours)
        if len(grid) < 2:
            break

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

        cursor = chunk_end
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

def _refine_station_vector(body: str, left, right):
    """Preserve V6's 24-step ternary search while batching each pair of probes."""
    lo, hi = left, right
    for _ in range(24):
        span = hi - lo
        m1 = lo + span / 3
        m2 = hi - span / 3
        speeds = _batch_speeds(body, [m1, m2])
        if abs(float(speeds[0])) <= abs(float(speeds[1])):
            hi = m2
        else:
            lo = m1
    return lo + (hi - lo) / 2


def _next_station_vector(body: str, row, dt_utc, horizon_days: float = 180.0):
    """V6 station search on the same coarse timestamps, batched in chunks."""
    if body in {"Sun", "Moon"}:
        return None
    step_hours = 3.0 if body in {"Moon", "Mercury", "Venus", "Mars"} else 8.0
    end = dt_utc + timedelta(days=float(horizon_days))
    chunk_days = 45.0
    cursor = dt_utc

    try:
        prev_speed = float(_batch_speeds(body, [dt_utc])[0])
    except Exception:
        return _ORIGINAL_NEXT_STATION(body, row, dt_utc, horizon_days=horizon_days)

    while cursor < end:
        chunk_end = min(end, cursor + timedelta(days=chunk_days))
        chunk_horizon_days = (chunk_end - cursor).total_seconds() / 86400.0
        grid = _forward_grid(cursor, chunk_horizon_days, step_hours)
        times = grid[1:]
        if not times:
            break

        try:
            speeds = _batch_speeds(body, times)
        except Exception:
            return _ORIGINAL_NEXT_STATION(body, row, dt_utc, horizon_days=horizon_days)

        left = cursor
        for right, speed_value in zip(times, speeds):
            speed = float(speed_value)
            if (
                v6._motion_sign(prev_speed) == 0
                or v6._motion_sign(speed) == 0
                or v6._motion_sign(prev_speed) != v6._motion_sign(speed)
            ):
                exact = v6._refine_station(body, left, right)
                return {
                    "type": "station",
                    "body": body,
                    "body_ko": core.PLANET_KO.get(body, body),
                    "utc": exact.isoformat(),
                    "days_from_question": round((exact - dt_utc).total_seconds() / 86400.0, 6),
                    "speed_before": round(v6._speed_at(body, exact - timedelta(hours=1)), 6),
                    "speed_after": round(v6._speed_at(body, exact + timedelta(hours=1)), 6),
                }
            prev_speed = speed
            left = right

        cursor = chunk_end
    return None



@lru_cache(maxsize=128)
def _cached_moon_prepared(start_iso: str, end_iso: str, step_hours: float):
    """Prepare one Skyfield observer for all Moon-course bodies on this interval."""
    start_dt = v6._parse_utc(start_iso)
    end_dt = v6._parse_utc(end_iso)
    times = list(core._sample_datetimes(start_dt, end_dt, float(step_hours)))
    if not times:
        return tuple(), None, None, tuple()

    ts, _, earth, targets, _, _, _ = core.load_ephemeris()
    sf_times = ts.from_datetimes([dt.astimezone(core.UTC) for dt in times])
    observer = earth.at(sf_times)

    apparent = observer.observe(targets["Moon"]).apparent()
    _, lon, _ = apparent.frame_latlon(core.ecliptic_frame)
    values = np.ravel(np.asarray(lon.degrees, dtype=float))
    if values.size != len(times):
        raise ValueError(
            f"Moon prepared longitude shape mismatch: {values.size} values for {len(times)} datetimes"
        )
    moon_lons = tuple(float(x % 360.0) for x in values)
    return tuple(times), observer, targets, moon_lons


def _exact_events_between_moon_cached(body_a: str, body_b: str, start_dt, end_dt):
    """Preserve V6 exact-event math while reusing the repeated Moon side."""
    if "Moon" not in {body_a, body_b}:
        return _ORIGINAL_EXACT_EVENTS_BETWEEN(body_a, body_b, start_dt, end_dt)
    if end_dt <= start_dt:
        return []

    step_hours = 0.5
    prepared_times, observer, targets, moon_values = _cached_moon_prepared(
        start_dt.isoformat(),
        end_dt.isoformat(),
        step_hours,
    )
    times = list(prepared_times)
    if len(times) < 3 or observer is None or targets is None:
        return []

    moon_lons = np.asarray(moon_values, dtype=float)
    other = body_b if body_a == "Moon" else body_a
    apparent = observer.observe(targets[other]).apparent()
    _, other_lon, _ = apparent.frame_latlon(core.ecliptic_frame)
    other_lons = np.ravel(np.asarray(other_lon.degrees, dtype=float))
    if other_lons.size != len(times):
        raise ValueError(
            f"{other} prepared longitude shape mismatch: "
            f"{other_lons.size} values for {len(times)} datetimes"
        )
    other_lons = np.mod(other_lons, 360.0)
    if body_a == "Moon":
        a_lons, b_lons = moon_lons, other_lons
    else:
        a_lons, b_lons = other_lons, moon_lons

    seps = np.abs((a_lons - b_lons + 180.0) % 360.0 - 180.0)
    out = []
    for key, spec in core.HORARY_ASPECTS.items():
        errors = np.abs(seps - float(spec["angle"]))
        for i in range(1, len(times) - 1):
            if not (errors[i] <= errors[i - 1] and errors[i] <= errors[i + 1]):
                continue
            if float(errors[i]) > 0.8:
                continue
            try:
                exact, orb = v6._refine_exact_aspect(
                    body_a,
                    body_b,
                    float(spec["angle"]),
                    times[i - 1],
                    times[i + 1],
                )
            except Exception:
                continue
            if orb > v6.ASPECT_EXACT_TOL or not (start_dt <= exact <= end_dt):
                continue
            stamp = round(exact.timestamp(), 1)
            if any(x["_stamp"] == stamp and x["aspect"] == key for x in out):
                continue
            target = body_b if body_a == "Moon" else body_a
            out.append({
                "_stamp": stamp,
                "body": target,
                "body_ko": core.PLANET_KO.get(target, target),
                "aspect": key,
                "aspect_ko": spec.get("label_ko", key),
                "exact_utc": exact.isoformat(),
                "exact_orb": round(orb, 6),
            })
    out.sort(key=lambda x: x["_stamp"])
    return out

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
    global _lon_hits, _lon_misses, _refine_ingress_hits, _refine_ingress_misses, _aspect_state_hits, _aspect_state_misses
    _cached_moon_prepared.cache_clear()
    with _lon_lock:
        _lon_cache.clear()
        _lon_hits = 0
        _lon_misses = 0
    _refine_ingress_hits = 0
    _refine_ingress_misses = 0
    _aspect_state_hits = 0
    _aspect_state_misses = 0


def cache_info() -> dict:
    with _lon_lock:
        return {
            "longitude": {
                "size": len(_lon_cache),
                "maxsize": _LON_CACHE_MAXSIZE,
                "hits": _lon_hits,
                "misses": _lon_misses,
            },
            "refine_sign_ingress": {
                "hits": _refine_ingress_hits,
                "misses": _refine_ingress_misses,
            },
            "strict_aspect_state": {
                "hits": _aspect_state_hits,
                "misses": _aspect_state_misses,
            },
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
        _refine_station_vector._lunea_horary_perf_v2 = True

        core.get_tropical_ecliptic_lon = _cached_core_lon
        v6._next_sign_ingress = _next_sign_ingress_vector
        v6._previous_sign_ingress = _previous_sign_ingress_vector
        v6._next_station = _next_station_vector
        v6._refine_station = _refine_station_vector
        v6._refine_sign_ingress = _refine_sign_ingress_cached
        v6._strict_aspect_state = _strict_aspect_state_cached
        core._horary_aspect_state = _strict_aspect_state_cached
        v6._exact_events_between = _exact_events_between_moon_cached
        changed = True

    if not getattr(v31.compute_horary, "_lunea_perf_v2_shared_v5_cache", False):
        _compute_horary_with_shared_v5_cache._lunea_perf_v2_shared_v5_cache = True
        v31.compute_horary = _compute_horary_with_shared_v5_cache
        changed = True

    # Preserve the old full-chain behavior when Future Window was imported
    # before this module, without importing/activating Future Window for V6-only.
    return install_future_window() or changed


install()
