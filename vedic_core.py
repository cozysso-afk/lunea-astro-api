from __future__ import annotations

from threading import Lock
from typing import Optional

import swisseph as swe

from astro_core import local_birth_to_utc, resolve_coordinates, to_jd_ut

_SWE_LOCK = Lock()

RASHI = [
    ("Mesha", "양자리"), ("Vrishabha", "황소자리"), ("Mithuna", "쌍둥이자리"),
    ("Karka", "게자리"), ("Simha", "사자자리"), ("Kanya", "처녀자리"),
    ("Tula", "천칭자리"), ("Vrishchika", "전갈자리"), ("Dhanu", "사수자리"),
    ("Makara", "염소자리"), ("Kumbha", "물병자리"), ("Meena", "물고기자리"),
]
NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni",
    "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha",
    "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha",
    "Purva Bhadrapada", "Uttara Bhadrapada", "Revati",
]
YOGAS = [
    "Vishkambha", "Priti", "Ayushman", "Saubhagya", "Shobhana", "Atiganda",
    "Sukarman", "Dhriti", "Shula", "Ganda", "Vriddhi", "Dhruva", "Vyaghata",
    "Harshana", "Vajra", "Siddhi", "Vyatipata", "Variyana", "Parigha", "Shiva",
    "Siddha", "Sadhya", "Shubha", "Shukla", "Brahma", "Indra", "Vaidhriti",
]
MOVABLE_KARANAS = ["Bava", "Balava", "Kaulava", "Taitila", "Garaja", "Vanija", "Vishti"]
WEEKDAYS = [
    ("Somavara", "월요일"), ("Mangalavara", "화요일"), ("Budhavara", "수요일"),
    ("Guruvara", "목요일"), ("Shukravara", "금요일"), ("Shanivara", "토요일"),
    ("Ravivara", "일요일"),
]

PLANETS = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mercury": swe.MERCURY,
    "Venus": swe.VENUS,
    "Mars": swe.MARS,
    "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN,
    "Rahu": swe.TRUE_NODE,
}


def _rashi_data(longitude: float) -> dict:
    lon = float(longitude % 360.0)
    index = int(lon // 30)
    return {
        "rashi": RASHI[index][0],
        "rashi_ko": RASHI[index][1],
        "sign_index": index,
        "degree": round(lon % 30.0, 6),
        "longitude": round(lon, 6),
    }


def _nakshatra(longitude: float) -> dict:
    lon = float(longitude % 360.0)
    span = 360.0 / 27.0
    index = min(26, int(lon // span))
    offset = lon - index * span
    pada = min(4, int(offset // (span / 4.0)) + 1)
    return {
        "index": index + 1,
        "name": NAKSHATRAS[index],
        "pada": pada,
        "offset_degree": round(offset, 6),
    }


def _karana(elongation: float) -> dict:
    half_index = min(59, int((elongation % 360.0) // 6.0))
    if half_index == 0:
        name = "Kimstughna"
    elif 1 <= half_index <= 56:
        name = MOVABLE_KARANAS[(half_index - 1) % 7]
    elif half_index == 57:
        name = "Shakuni"
    elif half_index == 58:
        name = "Chatushpada"
    else:
        name = "Naga"
    return {"half_tithi_index": half_index + 1, "name": name}


def _panchanga(local_dt, sun_lon: float, moon_lon: float) -> dict:
    elongation = (moon_lon - sun_lon) % 360.0
    tithi_index = min(29, int(elongation // 12.0))
    paksha = "Shukla" if tithi_index < 15 else "Krishna"
    paksha_number = tithi_index + 1 if tithi_index < 15 else tithi_index - 14
    yoga_index = min(26, int(((sun_lon + moon_lon) % 360.0) // (360.0 / 27.0)))
    weekday = WEEKDAYS[local_dt.weekday()]
    return {
        "vara": {"name": weekday[0], "label_ko": weekday[1]},
        "tithi": {
            "index": tithi_index + 1,
            "paksha": paksha,
            "paksha_number": paksha_number,
            "elongation": round(elongation, 6),
        },
        "nakshatra": _nakshatra(moon_lon),
        "yoga": {"index": yoga_index + 1, "name": YOGAS[yoga_index]},
        "karana": _karana(elongation),
    }


def _sidereal_positions(jd_ut: float) -> tuple[dict, float]:
    flags = swe.FLG_SWIEPH | swe.FLG_SPEED | swe.FLG_SIDEREAL
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    ayanamsha = float(swe.get_ayanamsa_ut(jd_ut))
    positions = {}
    for name, body in PLANETS.items():
        values, retflags = swe.calc_ut(jd_ut, body, flags)
        lon = float(values[0] % 360.0)
        positions[name] = {
            **_rashi_data(lon),
            "speed_longitude": round(float(values[3]), 8),
            "retrograde": bool(values[3] < 0),
            "nakshatra": _nakshatra(lon),
            "retflags": int(retflags),
        }
    rahu_lon = positions["Rahu"]["longitude"]
    ketu_lon = (rahu_lon + 180.0) % 360.0
    positions["Ketu"] = {
        **_rashi_data(ketu_lon),
        "speed_longitude": positions["Rahu"]["speed_longitude"],
        "retrograde": positions["Rahu"]["retrograde"],
        "nakshatra": _nakshatra(ketu_lon),
        "derived_from": "Rahu+180",
    }
    return positions, ayanamsha


def compute_vedic_profile(
    birth_date: str,
    birth_time: str,
    timezone_name: str = "Asia/Seoul",
    place: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
) -> dict:
    local_dt, dt_utc = local_birth_to_utc(birth_date, birth_time, timezone_name)
    latitude, longitude, resolved_place = resolve_coordinates(place, lat, lon)
    jd_ut = to_jd_ut(dt_utc)

    with _SWE_LOCK:
        positions, ayanamsha = _sidereal_positions(jd_ut)
        swe.set_sid_mode(swe.SIDM_LAHIRI)
        cusps, ascmc = swe.houses_ex(
            jd_ut,
            float(latitude),
            float(longitude),
            b"W",
            swe.FLG_SIDEREAL,
        )

    lagna_lon = float(ascmc[0] % 360.0)
    lagna = {
        **_rashi_data(lagna_lon),
        "nakshatra": _nakshatra(lagna_lon),
    }
    asc_sign = lagna["sign_index"]
    whole_sign_houses = [
        {
            "house": house + 1,
            "rashi_index": (asc_sign + house) % 12,
            "rashi": RASHI[(asc_sign + house) % 12][0],
            "rashi_ko": RASHI[(asc_sign + house) % 12][1],
            "cusp": round(float(cusps[house] % 360.0), 6),
        }
        for house in range(12)
    ]
    for planet in positions.values():
        if "sign_index" in planet:
            planet["whole_sign_house"] = (planet["sign_index"] - asc_sign) % 12 + 1

    return {
        "schema": "LUNEA_VEDIC_PROFILE_V1",
        "zodiac": "sidereal",
        "ayanamsha": {
            "mode": "Lahiri",
            "swisseph_mode": "SIDM_LAHIRI",
            "degree": round(ayanamsha, 8),
        },
        "d1_rashi": {
            "lagna": lagna,
            "planets": positions,
            "whole_sign_houses": whole_sign_houses,
        },
        "panchanga": _panchanga(local_dt, positions["Sun"]["longitude"], positions["Moon"]["longitude"]),
        "birth": {
            "local_iso": local_dt.isoformat(),
            "utc_iso": dt_utc.isoformat(),
            "timezone": timezone_name,
            "place_input": place,
            "place_resolved": resolved_place,
            "latitude": latitude,
            "longitude": longitude,
        },
        "provenance": {
            "engine": "Swiss Ephemeris / pyswisseph",
            "sidereal": True,
            "ayanamsha": "Lahiri",
            "node_policy": "true_node",
            "house_policy": "whole_sign_from_sidereal_lagna",
            "d9_navamsa": False,
            "vimshottari_dasha": False,
            "interpretation_generated": False,
        },
    }
