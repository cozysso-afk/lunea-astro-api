from __future__ import annotations

"""LUNEA Horary performance V2: vectorized ephemeris scan layer.

Keeps the exact Horary search grid, horizons, thresholds, and refinement logic,
but evaluates coarse station/ingress samples in Skyfield vector batches instead
of thousands of scalar ephemeris calls.
"""

from datetime import timedelta

import numpy as np

import astro_core as core
import horary_engine_v6 as v6


VERSION = "LUNEA_HORARY_PERFORMANCE_V2_VECTOR_SCAN"

_ORIGINAL_NEXT_SIGN_INGRESS = v6._next_sign_ingress
_ORIGINAL_PREVIOUS_SIGN_INGRESS = v6._previous_sign_ingress
_ORIGINAL_NEXT_STATION = v6._next_station


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


def _motion_speeds_batched(body: str, sample_times):
    n = len(sample_times)
    if not n:
        return np.array([], dtype=float)
    h = 0.25 if body == "Moon" else 1.0 if body in {"Sun", "Mercury", "Venus", "Mars"} else 6.0
    past = [d - timedelta(hours=h) for d in sample_times]
    future = [d + timedelta(hours=h) for d in sample_times]
    combined = past + list(sample_times) + future
    values = np.ravel(core.get_tropical_ecliptic_lons(body, combined))
    if values.size != n * 3:
        raise ValueError(f"{body} Horary motion vector size mismatch: {values.size} != {n * 3}")
    past_lon = values[:n]
    future_lon = values[2 * n :]
    delta = (future_lon - past_lon + 180.0) % 360.0 - 180.0
    return np.ravel(delta / ((2 * h) / 24.0))


def _next_sign_ingress(body: str, row, dt_utc, horizon_days: float = 180.0):
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

    for idx, lon in enumerate(lons, start=1):
        if int(float(lon) // 30.0) != start_sign:
            left, right = grid[idx - 1], grid[idx]
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


def _previous_sign_ingress(body: str, row, dt_utc, horizon_days: float = 5.0):
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

    for idx, lon in enumerate(lons, start=1):
        if int(float(lon) // 30.0) != start_sign:
            left, right = grid[idx], grid[idx - 1]
            lo, hi = left, right
            for _ in range(28):
                mid = lo + (hi - lo) / 2
                if v6._sign_index_at(body, mid) == start_sign:
                    hi = mid
                else:
                    lo = mid
            return hi
    return dt_utc - timedelta(days=float(horizon_days))


def _next_station(body: str, row, dt_utc, horizon_days: float = 180.0):
    start_speed = float(row.get("speed_deg_per_day") or 0.0)
    step_hours = 3.0 if body in {"Moon", "Mercury", "Venus", "Mars"} else 8.0
    grid = _forward_grid(dt_utc, horizon_days, step_hours)
    try:
        speeds = _motion_speeds_batched(body, grid)
        if speeds.size != len(grid):
            raise ValueError("station vector size mismatch")
    except Exception:
        return _ORIGINAL_NEXT_STATION(body, row, dt_utc, horizon_days=horizon_days)

    prev_speed = float(speeds[0]) if speeds.size else start_speed
    for idx in range(1, len(grid)):
        speed = float(speeds[idx])
        if (
            v6._motion_sign(prev_speed) == 0
            or v6._motion_sign(speed) == 0
            or v6._motion_sign(prev_speed) != v6._motion_sign(speed)
        ):
            left, right = grid[idx - 1], grid[idx]
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
    return None


def install() -> bool:
    if getattr(v6._next_station, "_lunea_performance_v2", False):
        return False
    for replacement in (_next_sign_ingress, _previous_sign_ingress, _next_station):
        replacement._lunea_performance_v2 = True
    v6._next_sign_ingress = _next_sign_ingress
    v6._previous_sign_ingress = _previous_sign_ingress
    v6._next_station = _next_station
    return True


install()
