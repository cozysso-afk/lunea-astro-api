from __future__ import annotations

from datetime import datetime

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


def _moiety_aspect_limit(body_a, body_b, aspect_key):
    """Return the traditional pair orb as the sum of planetary moieties."""
    a = HORARY_MOIETIES_DEG.get(body_a)
    b = HORARY_MOIETIES_DEG.get(body_b)
    if a is None or b is None:
        return _ORIGINAL_ASPECT_LIMIT(body_a, body_b, aspect_key)
    return float(a + b)


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
        # Defensive compatibility fallback only. Normal API payloads include
        # utc/latitude/longitude, so production should use altitude.
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


# Patch before any actual question calculation occurs. v31's runtime global
# lookup of _is_day_chart therefore uses the altitude-based implementation.
core._horary_aspect_limit = _moiety_aspect_limit
v31._is_day_chart = _is_day_chart_altitude

if not getattr(v31.compute_horary, "_lunea_engine_v5", False):
    _compute_horary_v5._lunea_engine_v5 = True
    v31.compute_horary = _compute_horary_v5

# V6 must load after V5 has installed moiety-orb and sect policies.
import horary_engine_v6  # noqa: F401,E402
