from __future__ import annotations

"""Isolated V6-only performance probe.

No policy/routing/grade/threshold changes. This module is imported only by the
temporary benchmark workflow. It deliberately does not import Future Window,
V7, V8, Judgment V2, or the existing performance_v1/v2 modules.
"""

from collections import OrderedDict
from copy import deepcopy
from datetime import timedelta
from functools import lru_cache
from threading import RLock

import numpy as np

import astro_core as core
import horary_engine_v6 as v6


_ORIGINAL_CORE_LON = core.get_tropical_ecliptic_lon
_ORIGINAL_NEXT_SIGN_INGRESS = v6._next_sign_ingress
_ORIGINAL_PREVIOUS_SIGN_INGRESS = v6._previous_sign_ingress
_ORIGINAL_NEXT_STATION = v6._next_station
_ORIGINAL_FIND_EXACT_ASPECT = v6._find_exact_aspect
_ORIGINAL_EXACT_EVENTS_BETWEEN = v6._exact_events_between

_CACHE_MAX = 65536
_lon_cache: OrderedDict[tuple[str, float], float] = OrderedDict()
_lock = RLock()


def _scalar_tt(time_obj) -> float:
    value = np.asarray(getattr(time_obj, "tt"))
    if value.shape != ():
        raise TypeError("non-scalar Skyfield Time")
    return float(value)


def _cached_core_lon(body_name, time_obj):
    try:
        key = (str(body_name), _scalar_tt(time_obj))
    except Exception:
        return _ORIGINAL_CORE_LON(body_name, time_obj)
    with _lock:
        cached = _lon_cache.get(key)
        if cached is not None:
            _lon_cache.move_to_end(key)
            return cached
    value = float(_ORIGINAL_CORE_LON(body_name, time_obj))
    with _lock:
        _lon_cache[key] = value
        _lon_cache.move_to_end(key)
        while len(_lon_cache) > _CACHE_MAX:
            _lon_cache.popitem(last=False)
    return value


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


def _next_sign_ingress_raw(body: str, row, dt_utc, horizon_days: float):
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


@lru_cache(maxsize=2048)
def _cached_next_sign_ingress(body, longitude, speed, dt_iso, horizon):
    return deepcopy(_next_sign_ingress_raw(
        body,
        {"longitude": longitude, "speed_deg_per_day": speed},
        v6._parse_utc(dt_iso),
        float(horizon),
    ))


def _next_sign_ingress(body: str, row, dt_utc, horizon_days: float = 180.0):
    return deepcopy(_cached_next_sign_ingress(
        str(body),
        float(row["longitude"]),
        float(row.get("speed_deg_per_day") or 0.0),
        dt_utc.isoformat(),
        float(horizon_days),
    ))


def _previous_sign_ingress_raw(body: str, row, dt_utc, horizon_days: float):
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


@lru_cache(maxsize=1024)
def _cached_previous_sign_ingress(body, longitude, speed, dt_iso, horizon):
    return _previous_sign_ingress_raw(
        body,
        {"longitude": longitude, "speed_deg_per_day": speed},
        v6._parse_utc(dt_iso),
        float(horizon),
    )


def _previous_sign_ingress(body: str, row, dt_utc, horizon_days: float = 5.0):
    return _cached_previous_sign_ingress(
        str(body),
        float(row["longitude"]),
        float(row.get("speed_deg_per_day") or 0.0),
        dt_utc.isoformat(),
        float(horizon_days),
    )


def _motion_window_hours(body: str) -> float:
    if body == "Moon":
        return 0.25
    if body in {"Sun", "Mercury", "Venus", "Mars"}:
        return 1.0
    return 6.0


def _batch_speeds(body: str, times):
    if not times:
        return np.asarray([], dtype=float)
    h = _motion_window_hours(body)
    past = [dt - timedelta(hours=h) for dt in times]
    future = [dt + timedelta(hours=h) for dt in times]
    values = np.ravel(core.get_tropical_ecliptic_lons(body, past + future))
    n = len(times)
    past_lons = values[:n]
    future_lons = values[n:]
    delta = (future_lons - past_lons + 180.0) % 360.0 - 180.0
    return np.ravel(delta / ((2.0 * h) / 24.0))


def _refine_station_vector(body: str, left, right, iterations: int = 24):
    lo, hi = left, right
    for _ in range(iterations):
        span = hi - lo
        m1 = lo + span / 3
        m2 = hi - span / 3
        speeds = _batch_speeds(body, [m1, m2])
        if abs(float(speeds[0])) <= abs(float(speeds[1])):
            hi = m2
        else:
            lo = m1
    return lo + (hi - lo) / 2


def _next_station_raw(body: str, row, dt_utc, horizon_days: float):
    step_hours = 3.0 if body in {"Moon", "Mercury", "Venus", "Mars"} else 8.0
    times = _forward_grid(dt_utc, horizon_days, step_hours)
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
            exact = _refine_station_vector(body, times[index - 1], times[index])
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


@lru_cache(maxsize=2048)
def _cached_next_station(body, longitude, speed, dt_iso, horizon):
    return deepcopy(_next_station_raw(
        body,
        {"longitude": longitude, "speed_deg_per_day": speed},
        v6._parse_utc(dt_iso),
        float(horizon),
    ))


def _next_station(body: str, row, dt_utc, horizon_days: float = 180.0):
    return deepcopy(_cached_next_station(
        str(body),
        float(row["longitude"]),
        float(row.get("speed_deg_per_day") or 0.0),
        dt_utc.isoformat(),
        float(horizon_days),
    ))


@lru_cache(maxsize=2048)
def _cached_find_exact(body_a, body_b, angle, start_iso, end_iso):
    return deepcopy(_ORIGINAL_FIND_EXACT_ASPECT(
        body_a, body_b, float(angle), v6._parse_utc(start_iso), v6._parse_utc(end_iso)
    ))


def _find_exact_aspect(body_a, body_b, angle, start_dt, end_dt):
    return deepcopy(_cached_find_exact(
        str(body_a), str(body_b), float(angle), start_dt.isoformat(), end_dt.isoformat()
    ))


@lru_cache(maxsize=1024)
def _cached_events(body_a, body_b, start_iso, end_iso):
    return deepcopy(_ORIGINAL_EXACT_EVENTS_BETWEEN(
        body_a, body_b, v6._parse_utc(start_iso), v6._parse_utc(end_iso)
    ))


def _exact_events_between(body_a, body_b, start_dt, end_dt):
    return deepcopy(_cached_events(
        str(body_a), str(body_b), start_dt.isoformat(), end_dt.isoformat()
    ))


def install():
    core.get_tropical_ecliptic_lon = _cached_core_lon
    v6._next_sign_ingress = _next_sign_ingress
    v6._previous_sign_ingress = _previous_sign_ingress
    v6._next_station = _next_station
    v6._find_exact_aspect = _find_exact_aspect
    v6._exact_events_between = _exact_events_between


install()
