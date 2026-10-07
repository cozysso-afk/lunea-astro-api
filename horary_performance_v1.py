from __future__ import annotations

"""Performance-only memoization for deterministic Horary ephemeris scans.

This module must not alter Horary policy, routing, grades, thresholds, or stage
gates. It only reuses results when the calculation inputs are identical.
Mutable results are deep-copied on both cache ingress/egress so downstream
post-processing cannot mutate a cached value.
"""

from copy import deepcopy
from functools import lru_cache

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


@lru_cache(maxsize=1024)
def _cached_find_exact_aspect(
    body_a: str,
    body_b: str,
    angle: float,
    dt_iso: str,
    end_iso: str,
):
    result = _ORIGINAL_FIND_EXACT_ASPECT(
        body_a,
        body_b,
        float(angle),
        v6._parse_utc(dt_iso),
        v6._parse_utc(end_iso),
    )
    return deepcopy(result)


def _find_exact_aspect(body_a: str, body_b: str, angle: float, dt_utc, end_dt):
    # Exact-aspect timing is symmetric for A/B. Canonicalize only the memo key
    # so reverse-role callers can reuse the same deterministic search result.
    pair = tuple(sorted((str(body_a), str(body_b))))
    return deepcopy(
        _cached_find_exact_aspect(
            pair[0],
            pair[1],
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
