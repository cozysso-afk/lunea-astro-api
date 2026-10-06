from __future__ import annotations

"""Performance-only memoization for deterministic Horary ephemeris scans.

This module must not alter Horary policy, routing, grades, thresholds, or stage
gates. It only reuses results when the calculation inputs are identical.
Mutable results are deep-copied on both cache ingress/egress so downstream
post-processing cannot mutate a cached value.
"""

from copy import deepcopy
from functools import lru_cache

import numpy as np
import swisseph as swe

import astro_core as core
import horary_engine_v6 as v6


VERSION = "LUNEA_HORARY_PERFORMANCE_V1_MEMO"
_CANONICAL_EVENT_HORIZON_DAYS = 180.0

_ORIGINAL_PLANET_LON = v6._planet_lon
_ORIGINAL_SPEED_AT = v6._speed_at
_ORIGINAL_NEXT_SIGN_INGRESS = v6._next_sign_ingress
_ORIGINAL_NEXT_STATION = v6._next_station
_ORIGINAL_FIND_EXACT_ASPECT = v6._find_exact_aspect
_ORIGINAL_EXACT_EVENTS_BETWEEN = v6._exact_events_between


def _dt_key(value) -> str:
    return value.isoformat()


def _row_key(row) -> tuple[float, float]:
    return (
        float(row["longitude"]),
        float(row.get("speed_deg_per_day") or 0.0),
    )


@lru_cache(maxsize=8192)
def _cached_planet_lon(body: str, dt_iso: str) -> float:
    return float(_ORIGINAL_PLANET_LON(body, v6._parse_utc(dt_iso)))


def _planet_lon(body: str, dt_utc) -> float:
    return _cached_planet_lon(str(body), _dt_key(dt_utc))


@lru_cache(maxsize=8192)
def _cached_speed_at(body: str, dt_iso: str) -> float:
    return float(_ORIGINAL_SPEED_AT(body, v6._parse_utc(dt_iso)))


def _speed_at(body: str, dt_utc) -> float:
    return _cached_speed_at(str(body), _dt_key(dt_utc))


@lru_cache(maxsize=1024)
def _cached_next_sign_ingress(
    body: str,
    longitude: float,
    speed_deg_per_day: float,
    dt_iso: str,
):
    """Compute the first ingress once for all callers using horizons <= 180d."""
    result = _ORIGINAL_NEXT_SIGN_INGRESS(
        body,
        {"longitude": longitude, "speed_deg_per_day": speed_deg_per_day},
        v6._parse_utc(dt_iso),
        horizon_days=_CANONICAL_EVENT_HORIZON_DAYS,
    )
    return deepcopy(result)


def _within_requested_horizon(result, horizon_days: float):
    if not result:
        return None
    try:
        days = float(result["days_from_question"])
    except Exception:
        return deepcopy(result)
    return deepcopy(result) if days <= float(horizon_days) + 1e-9 else None


def _next_sign_ingress(body: str, row, dt_utc, horizon_days: float = 180.0):
    longitude, speed = _row_key(row)
    horizon = float(horizon_days)
    if horizon <= _CANONICAL_EVENT_HORIZON_DAYS:
        result = _cached_next_sign_ingress(
            str(body), longitude, speed, _dt_key(dt_utc)
        )
        return _within_requested_horizon(result, horizon)
    return deepcopy(
        _ORIGINAL_NEXT_SIGN_INGRESS(
            str(body),
            {"longitude": longitude, "speed_deg_per_day": speed},
            dt_utc,
            horizon_days=horizon,
        )
    )


@lru_cache(maxsize=1024)
def _cached_next_station(
    body: str,
    longitude: float,
    speed_deg_per_day: float,
    dt_iso: str,
):
    """Compute the first station once for all callers using horizons <= 180d."""
    result = _ORIGINAL_NEXT_STATION(
        body,
        {"longitude": longitude, "speed_deg_per_day": speed_deg_per_day},
        v6._parse_utc(dt_iso),
        horizon_days=_CANONICAL_EVENT_HORIZON_DAYS,
    )
    return deepcopy(result)


def _next_station(body: str, row, dt_utc, horizon_days: float = 180.0):
    longitude, speed = _row_key(row)
    horizon = float(horizon_days)
    if horizon <= _CANONICAL_EVENT_HORIZON_DAYS:
        result = _cached_next_station(
            str(body), longitude, speed, _dt_key(dt_utc)
        )
        return _within_requested_horizon(result, horizon)
    return deepcopy(
        _ORIGINAL_NEXT_STATION(
            str(body),
            {"longitude": longitude, "speed_deg_per_day": speed},
            dt_utc,
            horizon_days=horizon,
        )
    )


_SWEPH_PLANETS = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mercury": swe.MERCURY,
    "Venus": swe.VENUS,
    "Mars": swe.MARS,
    "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN,
}


def _swiss_coarse_lons(body: str, times):
    planet = _SWEPH_PLANETS.get(str(body))
    if planet is None:
        raise KeyError(body)
    flags = swe.FLG_SWIEPH
    return np.fromiter(
        (
            float(swe.calc_ut(core.to_jd_ut(dt), planet, flags)[0][0] % 360.0)
            for dt in times
        ),
        dtype=float,
        count=len(times),
    )


def _find_exact_aspect_swiss_coarse(
    body_a: str,
    body_b: str,
    angle: float,
    dt_utc,
    end_dt,
):
    """Use Swiss only for V6 coarse bracketing; retain Skyfield exact refinement."""
    if end_dt <= dt_utc:
        return None
    span_days = max(0.01, (end_dt - dt_utc).total_seconds() / 86400.0)
    step_hours = 0.5 if "Moon" in {body_a, body_b} else 1.5 if span_days < 7 else 3.0
    times = list(core._sample_datetimes(dt_utc, end_dt, step_hours))
    if len(times) < 2:
        return None

    a_lons = _swiss_coarse_lons(body_a, times)
    b_lons = _swiss_coarse_lons(body_b, times)
    seps = np.abs((a_lons - b_lons + 180.0) % 360.0 - 180.0)
    errors = np.abs(seps - float(angle))
    idx = int(np.argmin(errors))
    if idx == 0 or float(errors[idx]) > 1.25:
        return None

    left = times[max(0, idx - 1)]
    right = times[min(len(times) - 1, idx + 1)]
    if right <= left:
        return None

    exact, orb = v6._refine_exact_aspect(body_a, body_b, angle, left, right)
    if exact < dt_utc or exact > end_dt or orb > v6.ASPECT_EXACT_TOL:
        return None
    return {
        "type": "exact_aspect",
        "utc": exact.isoformat(),
        "days_from_question": round((exact - dt_utc).total_seconds() / 86400.0, 6),
        "exact_orb": round(orb, 6),
    }


@lru_cache(maxsize=1024)
def _cached_find_exact_aspect(
    body_a: str,
    body_b: str,
    angle: float,
    dt_iso: str,
    end_iso: str,
):
    start_dt = v6._parse_utc(dt_iso)
    end_dt = v6._parse_utc(end_iso)
    try:
        result = _find_exact_aspect_swiss_coarse(
            body_a,
            body_b,
            float(angle),
            start_dt,
            end_dt,
        )
    except Exception:
        result = _ORIGINAL_FIND_EXACT_ASPECT(
            body_a,
            body_b,
            float(angle),
            start_dt,
            end_dt,
        )
    return deepcopy(result)


def _find_exact_aspect(body_a: str, body_b: str, angle: float, dt_utc, end_dt):
    return deepcopy(
        _cached_find_exact_aspect(
            str(body_a),
            str(body_b),
            float(angle),
            _dt_key(dt_utc),
            _dt_key(end_dt),
        )
    )


@lru_cache(maxsize=512)
def _cached_exact_events_between(
    body_a: str,
    body_b: str,
    start_iso: str,
    end_iso: str,
):
    result = _ORIGINAL_EXACT_EVENTS_BETWEEN(
        body_a,
        body_b,
        v6._parse_utc(start_iso),
        v6._parse_utc(end_iso),
    )
    return deepcopy(result)


def _exact_events_between(body_a: str, body_b: str, start_dt, end_dt):
    return deepcopy(
        _cached_exact_events_between(
            str(body_a), str(body_b), _dt_key(start_dt), _dt_key(end_dt)
        )
    )


def clear_caches() -> None:
    for cached in (
        _cached_planet_lon,
        _cached_speed_at,
        _cached_next_sign_ingress,
        _cached_next_station,
        _cached_find_exact_aspect,
        _cached_exact_events_between,
    ):
        cached.cache_clear()


def cache_info() -> dict:
    return {
        "planet_lon": _cached_planet_lon.cache_info(),
        "speed_at": _cached_speed_at.cache_info(),
        "next_sign_ingress": _cached_next_sign_ingress.cache_info(),
        "next_station": _cached_next_station.cache_info(),
        "find_exact_aspect": _cached_find_exact_aspect.cache_info(),
        "exact_events_between": _cached_exact_events_between.cache_info(),
    }


def install() -> bool:
    if getattr(v6._next_station, "_lunea_performance_v1", False):
        return False

    for replacement in (
        _planet_lon,
        _speed_at,
        _next_sign_ingress,
        _next_station,
        _find_exact_aspect,
        _exact_events_between,
    ):
        replacement._lunea_performance_v1 = True

    v6._planet_lon = _planet_lon
    v6._speed_at = _speed_at
    v6._next_sign_ingress = _next_sign_ingress
    v6._next_station = _next_station
    v6._find_exact_aspect = _find_exact_aspect
    v6._exact_events_between = _exact_events_between
    return True


install()
