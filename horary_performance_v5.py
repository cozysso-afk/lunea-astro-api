from __future__ import annotations

"""Performance-only acceleration for the production Horary V5 chain.

No Horary policy, routing, grades, thresholds, search horizons, sample spacing,
or refinement iteration counts are changed. This module only:
1) reuses identical scalar tropical-longitude evaluations,
2) reuses identical vector tropical-longitude evaluations,
3) batches the same two ternary-search sample times in the existing
   12-iteration exact-aspect refinement, and
4) memoizes identical V3.1 balanced-perfection inputs.

Cached mutable results are copied before reuse so downstream code cannot mutate
shared cache state.
"""

from collections import OrderedDict
from copy import deepcopy
from datetime import datetime
from functools import lru_cache
from threading import RLock

import numpy as np

import astro_core as core
import horary_balance_v3 as v3


VERSION = "LUNEA_HORARY_PERFORMANCE_V5_SAFE_CACHE_BATCH"

_ORIGINAL_CORE_LON = core.get_tropical_ecliptic_lon
_ORIGINAL_CORE_LONS = core.get_tropical_ecliptic_lons
_ORIGINAL_REFINE_PAIR = core._horary_refine_pair
_ORIGINAL_BALANCED_PERFECTION = v3._balanced_perfection_candidate

_SCALAR_CACHE_MAXSIZE = 8192
_VECTOR_CACHE_MAXSIZE = 96
_scalar_cache: OrderedDict[tuple[str, float], float] = OrderedDict()
_vector_cache: OrderedDict[tuple[str, tuple[str, ...]], np.ndarray] = OrderedDict()
_lock = RLock()

_scalar_hits = 0
_scalar_misses = 0
_vector_hits = 0
_vector_misses = 0
_pair_hits = 0
_pair_misses = 0


def _scalar_tt(time_obj) -> float:
    value = np.asarray(getattr(time_obj, "tt"))
    if value.shape != ():
        raise TypeError("non-scalar Skyfield Time")
    return float(value)


def _cached_core_lon(body_name, time_obj):
    global _scalar_hits, _scalar_misses
    try:
        key = (str(body_name), _scalar_tt(time_obj))
    except Exception:
        return _ORIGINAL_CORE_LON(body_name, time_obj)

    with _lock:
        cached = _scalar_cache.get(key)
        if cached is not None:
            _scalar_hits += 1
            _scalar_cache.move_to_end(key)
            return cached

    value = float(_ORIGINAL_CORE_LON(body_name, time_obj))
    with _lock:
        _scalar_misses += 1
        _scalar_cache[key] = value
        _scalar_cache.move_to_end(key)
        while len(_scalar_cache) > _SCALAR_CACHE_MAXSIZE:
            _scalar_cache.popitem(last=False)
    return value


def _time_key(dt) -> str:
    return dt.astimezone(core.UTC).isoformat()


def _cached_core_lons(body_name, datetimes_utc):
    global _vector_hits, _vector_misses
    times = list(datetimes_utc)
    key = (str(body_name), tuple(_time_key(dt) for dt in times))

    with _lock:
        cached = _vector_cache.get(key)
        if cached is not None:
            _vector_hits += 1
            _vector_cache.move_to_end(key)
            return cached.copy()

    values = np.asarray(_ORIGINAL_CORE_LONS(body_name, times), dtype=float)
    with _lock:
        _vector_misses += 1
        _vector_cache[key] = values.copy()
        _vector_cache.move_to_end(key)
        while len(_vector_cache) > _VECTOR_CACHE_MAXSIZE:
            _vector_cache.popitem(last=False)
    return values


def _vector_refine_pair(
    body_a,
    body_b,
    aspect_angle,
    left_dt,
    right_dt,
    iterations=12,
):
    """Same ternary-search grid and iteration count, with batched evaluations."""

    def orbs(times):
        a_lons = np.asarray(core.get_tropical_ecliptic_lons(body_a, times), dtype=float)
        b_lons = np.asarray(core.get_tropical_ecliptic_lons(body_b, times), dtype=float)
        seps = np.abs((a_lons - b_lons + 180.0) % 360.0 - 180.0)
        return np.abs(seps - float(aspect_angle))

    left, right = left_dt, right_dt
    for _ in range(iterations):
        span = right - left
        m1 = left + span / 3
        m2 = right - span / 3
        values = orbs([m1, m2])
        if float(values[0]) <= float(values[1]):
            right = m2
        else:
            left = m1

    exact = left + (right - left) / 2
    exact_orb = float(orbs([exact])[0])
    return exact, exact_orb


def _row_key(row) -> tuple[float, float]:
    return (
        round(float(row["longitude"]), 12),
        round(float(row.get("speed_deg_per_day") or 0.0), 12),
    )


@lru_cache(maxsize=2048)
def _cached_balanced_perfection(
    body_a: str,
    a_lon: float,
    a_speed: float,
    body_b: str,
    b_lon: float,
    b_speed: float,
    dt_iso: str,
    timezone_name: str,
):
    global _pair_misses
    _pair_misses += 1
    result = _ORIGINAL_BALANCED_PERFECTION(
        body_a,
        {"longitude": a_lon, "speed_deg_per_day": a_speed},
        body_b,
        {"longitude": b_lon, "speed_deg_per_day": b_speed},
        datetime.fromisoformat(dt_iso),
        timezone_name,
    )
    return deepcopy(result)


def _balanced_perfection_candidate(
    body_a,
    row_a,
    body_b,
    row_b,
    dt_utc,
    timezone_name,
):
    global _pair_hits
    before = _cached_balanced_perfection.cache_info().hits
    a_lon, a_speed = _row_key(row_a)
    b_lon, b_speed = _row_key(row_b)
    result = _cached_balanced_perfection(
        str(body_a),
        a_lon,
        a_speed,
        str(body_b),
        b_lon,
        b_speed,
        dt_utc.isoformat(),
        str(timezone_name),
    )
    if _cached_balanced_perfection.cache_info().hits > before:
        _pair_hits += 1
    return deepcopy(result)


def clear_caches() -> None:
    global _scalar_hits, _scalar_misses, _vector_hits, _vector_misses
    global _pair_hits, _pair_misses
    with _lock:
        _scalar_cache.clear()
        _vector_cache.clear()
        _scalar_hits = 0
        _scalar_misses = 0
        _vector_hits = 0
        _vector_misses = 0
        _pair_hits = 0
        _pair_misses = 0
    _cached_balanced_perfection.cache_clear()


def cache_info() -> dict:
    with _lock:
        return {
            "version": VERSION,
            "scalar_longitude": {
                "size": len(_scalar_cache),
                "maxsize": _SCALAR_CACHE_MAXSIZE,
                "hits": _scalar_hits,
                "misses": _scalar_misses,
            },
            "vector_longitude": {
                "size": len(_vector_cache),
                "maxsize": _VECTOR_CACHE_MAXSIZE,
                "hits": _vector_hits,
                "misses": _vector_misses,
            },
            "balanced_perfection": {
                "size": _cached_balanced_perfection.cache_info().currsize,
                "maxsize": _cached_balanced_perfection.cache_info().maxsize,
                "hits": _pair_hits,
                "misses": _pair_misses,
            },
        }


def install() -> bool:
    if getattr(core.get_tropical_ecliptic_lon, "_lunea_horary_perf_v5", False):
        return False

    for replacement in (
        _cached_core_lon,
        _cached_core_lons,
        _vector_refine_pair,
        _balanced_perfection_candidate,
    ):
        replacement._lunea_horary_perf_v5 = True

    core.get_tropical_ecliptic_lon = _cached_core_lon
    core.get_tropical_ecliptic_lons = _cached_core_lons
    core._horary_refine_pair = _vector_refine_pair
    v3._balanced_perfection_candidate = _balanced_perfection_candidate
    return True


def uninstall() -> bool:
    changed = False
    if core.get_tropical_ecliptic_lon is _cached_core_lon:
        core.get_tropical_ecliptic_lon = _ORIGINAL_CORE_LON
        changed = True
    if core.get_tropical_ecliptic_lons is _cached_core_lons:
        core.get_tropical_ecliptic_lons = _ORIGINAL_CORE_LONS
        changed = True
    if core._horary_refine_pair is _vector_refine_pair:
        core._horary_refine_pair = _ORIGINAL_REFINE_PAIR
        changed = True
    if v3._balanced_perfection_candidate is _balanced_perfection_candidate:
        v3._balanced_perfection_candidate = _ORIGINAL_BALANCED_PERFECTION
        changed = True
    clear_caches()
    return changed


install()
