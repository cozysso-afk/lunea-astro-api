from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timedelta

import numpy as np

import astro_core as core
import horary_balance_v31 as v31


# LUNEA HORARY ENGINE V5
# ----------------------
# Traditional-calculation hardening layer:
# 1) Planetary moiety-based aspect orbs instead of aspect-type fixed limits.
# 2) Sect from the Sun's actual topocentric altitude at the question place/time.
# 3) Part of Fortune recomputed from that same sect decision.
# 4) Explicit calculation metadata so UI/tests can verify which policy ran.
#
# Classical full orbs commonly used in Lilly-style horary are halved to obtain
# each planet's moiety. A pair's operative orb is the sum of the two moieties.

VERSION = "LUNEA_HORARY_ENGINE_V5_MOIETY_SECT"

HORARY_FULL_ORBS_DEG = {
    "Saturn": 9.0,
    "Jupiter": 9.0,
    "Mars": 7.5,
    "Sun": 15.0,
    "Venus": 7.0,
    "Mercury": 7.0,
    "Moon": 12.5,
}
HORARY_MOIETIES_DEG = {
    body: value / 2.0 for body, value in HORARY_FULL_ORBS_DEG.items()
}

_ORIGINAL_ASPECT_LIMIT = core._horary_aspect_limit
_ORIGINAL_IS_DAY_CHART = v31._is_day_chart
_ORIGINAL_COMPUTE_HORARY = v31.compute_horary
_ORIGINAL_REFINE_PAIR = core._horary_refine_pair
_ORIGINAL_VECTOR_LONS = core.get_tropical_ecliptic_lons
_ORIGINAL_PLANET_MOTION = core.planet_motion

_REQUEST_LON_CACHE = ContextVar("lunea_horary_v5_request_lon_cache", default=None)


def _moiety_aspect_limit(body_a, body_b, aspect_key):
    """Return the traditional pair orb as the sum of planetary moieties."""
    a = HORARY_MOIETIES_DEG.get(body_a)
    b = HORARY_MOIETIES_DEG.get(body_b)
    if a is None or b is None:
        return _ORIGINAL_ASPECT_LIMIT(body_a, body_b, aspect_key)
    return float(a + b)



def _vectorized_refine_pair(body_a, body_b, aspect_angle, left_dt, right_dt, iterations=12):
    """Preserve the ternary-search math while batching each iteration's ephemeris calls."""
    def orbs(times):
        a = np.asarray(core.get_tropical_ecliptic_lons(body_a, times), dtype=float)
        b = np.asarray(core.get_tropical_ecliptic_lons(body_b, times), dtype=float)
        separations = np.abs((a - b + 180.0) % 360.0 - 180.0)
        return np.abs(separations - float(aspect_angle))

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


def _request_cached_lons(body_name, datetimes_utc):
    """Reuse identical body/time ephemeris points only inside one V5 request."""
    seq = list(datetimes_utc)
    cache = _REQUEST_LON_CACHE.get()
    if cache is None or not seq:
        return _ORIGINAL_VECTOR_LONS(body_name, seq)

    keys = [
        (str(body_name), dt.astimezone(core.UTC).isoformat())
        for dt in seq
    ]
    missing_positions = []
    missing_times = []
    for index, key in enumerate(keys):
        if key not in cache:
            missing_positions.append(index)
            missing_times.append(seq[index])

    if missing_times:
        values = np.asarray(_ORIGINAL_VECTOR_LONS(body_name, missing_times), dtype=float)
        for index, value in zip(missing_positions, values):
            cache[keys[index]] = float(value)

    return np.asarray([cache[key] for key in keys], dtype=float)


def _request_vector_planet_motion(body, dt_utc):
    """Same central-difference motion formula, batched only during a V5 request."""
    if _REQUEST_LON_CACHE.get() is None:
        return _ORIGINAL_PLANET_MOTION(body, dt_utc)

    window_hours = (
        0.25 if body == "Moon"
        else 1.0 if body in {"Sun", "Mercury", "Venus", "Mars"}
        else 6.0
    )
    values = np.asarray(
        core.get_tropical_ecliptic_lons(
            body,
            [
                dt_utc - timedelta(hours=window_hours),
                dt_utc,
                dt_utc + timedelta(hours=window_hours),
            ],
        ),
        dtype=float,
    )
    past, now, future = map(float, values)
    speed = core.circular_delta(future, past) / ((2.0 * window_hours) / 24.0)
    direction = "순행" if speed > 0.002 else "역행" if speed < -0.002 else "정지권"
    return now, float(speed), direction

def _parse_utc(value):
    raw = str(value or "").strip().replace("Z", "+00:00")
    if not raw:
        raise ValueError("missing utc moment")
    return datetime.fromisoformat(raw)


def _sect_evidence(data):
    moment = (data or {}).get("moment") or {}
    try:
        dt_utc = _parse_utc(moment.get("utc_iso"))
        latitude = float(moment["latitude"])
        longitude = float(moment["longitude"])
        altitude = float(core.sun_altitude_degrees(dt_utc, latitude, longitude))
        return {
            "day_chart": bool(altitude >= 0.0),
            "sun_altitude_deg": round(altitude, 6),
            "method": "topocentric_sun_altitude_geometric_horizon",
            "threshold_deg": 0.0,
            "fallback": False,
        }
    except Exception as exc:
        try:
            fallback_day = bool(_ORIGINAL_IS_DAY_CHART(data))
        except Exception:
            sun_house = int((((data or {}).get("planets") or {}).get("Sun") or {}).get("house") or 0)
            fallback_day = 7 <= sun_house <= 12
        return {
            "day_chart": fallback_day,
            "sun_altitude_deg": None,
            "method": "house_fallback",
            "threshold_deg": 0.0,
            "fallback": True,
            "fallback_reason": f"{type(exc).__name__}: {exc}",
        }


def _is_day_chart_altitude(data):
    return bool(_sect_evidence(data)["day_chart"])


def _recompute_part_of_fortune(data, sect):
    planets = (data or {}).get("planets") or {}
    angles = (data or {}).get("angles") or {}
    cusps = (data or {}).get("cusps") or []
    asc = (angles.get("ASC") or {}).get("longitude")
    sun_lon = (planets.get("Sun") or {}).get("longitude")
    moon_lon = (planets.get("Moon") or {}).get("longitude")
    if asc is None or sun_lon is None or moon_lon is None or len(cusps) != 12:
        return

    day_chart = bool(sect.get("day_chart"))
    pof_lon = core.calculate_pof(float(asc), float(sun_lon), float(moon_lon), day_chart)
    pof = {
        **core.sign_data(pof_lon),
        "name_ko": "포르투나",
        "house": core.cusp_house(pof_lon, cusps),
        "formula": "day: ASC+Moon-Sun" if day_chart else "night: ASC+Sun-Moon",
        "sect_source": sect.get("method"),
    }
    data.setdefault("points", {})["PartOfFortune"] = pof


def _compute_horary_v5(*args, **kwargs):
    token = _REQUEST_LON_CACHE.set({})
    try:
        data = _ORIGINAL_COMPUTE_HORARY(*args, **kwargs)
        if not isinstance(data, dict) or data.get("schema") != "LUNEA_HORARY_V1":
            return data

        sect = _sect_evidence(data)
        _recompute_part_of_fortune(data, sect)

        meta = data.setdefault("meta", {})
        meta["horary_engine"] = VERSION
        meta["sect"] = sect
        meta["aspect_orb_policy"] = {
            "method": "planetary_moiety_sum",
            "full_orbs_deg": dict(HORARY_FULL_ORBS_DEG),
            "moieties_deg": dict(HORARY_MOIETIES_DEG),
            "note": "Pair orb = moiety(body A) + moiety(body B), independent of aspect type.",
        }
        return data
    finally:
        _REQUEST_LON_CACHE.reset(token)


core._horary_aspect_limit = _moiety_aspect_limit
core._horary_refine_pair = _vectorized_refine_pair
core.get_tropical_ecliptic_lons = _request_cached_lons
core.planet_motion = _request_vector_planet_motion
v31._is_day_chart = _is_day_chart_altitude

if not getattr(v31.compute_horary, "_lunea_engine_v5", False):
    _compute_horary_v5._lunea_engine_v5 = True
    v31.compute_horary = _compute_horary_v5

# ROLLBACK FAST PATH
# ------------------
# V6 and the later V7/V8/Future/Judgment layers are intentionally not imported
# into the production Horary chain here. The historical V5 chain was the last
# fast path before the strict V6 ephemeris-event scans were activated. Keeping
# the newer modules in the repository preserves them for QA/rework without
# paying their repeated future-scan cost on every interactive Horary request.
