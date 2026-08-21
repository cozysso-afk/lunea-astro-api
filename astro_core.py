from __future__ import annotations

from functools import lru_cache
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import swisseph as swe
from skyfield.api import load, wgs84
from skyfield.framelib import ecliptic_frame

UTC = timezone.utc

SIGNS_KO = [
    "양자리","황소자리","쌍둥이자리","게자리","사자자리","처녀자리",
    "천칭자리","전갈자리","사수자리","염소자리","물병자리","물고기자리"
]
SIGNS_EN = [
    "Aries","Taurus","Gemini","Cancer","Leo","Virgo",
    "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"
]

PLANET_KEYS = {
    "Sun": ("sun",),
    "Moon": ("moon",),
    "Mercury": ("mercury", "mercury barycenter"),
    "Venus": ("venus", "venus barycenter"),
    "Mars": ("mars", "mars barycenter"),
    "Jupiter": ("jupiter", "jupiter barycenter"),
    "Saturn": ("saturn", "saturn barycenter"),
    "Uranus": ("uranus", "uranus barycenter"),
    "Neptune": ("neptune", "neptune barycenter"),
    "Pluto": ("pluto", "pluto barycenter"),
}

PLANET_KO = {
    "Sun":"태양","Moon":"달","Mercury":"수성","Venus":"금성","Mars":"화성",
    "Jupiter":"목성","Saturn":"토성","Uranus":"천왕성","Neptune":"해왕성","Pluto":"명왕성"
}

# 기존 astro-app의 국내 출생지 테이블을 API용으로 재사용.
KOREA_BIRTHPLACES = {
    "전라남도 여수시": (34.7604,127.6622),
    "전라남도 순천시": (34.9507,127.4872),
    "전라남도 광양시": (34.9407,127.6959),
    "광주광역시": (35.1595,126.8526),
    "전북특별자치도 전주시": (35.8242,127.1480),
    "전북특별자치도 군산시": (35.9677,126.7366),
    "서울특별시": (37.5665,126.9780),
    "부산광역시": (35.1796,129.0756),
    "대구광역시": (35.8714,128.6014),
    "인천광역시": (37.4563,126.7052),
    "대전광역시": (36.3504,127.3845),
    "울산광역시": (35.5384,129.3114),
    "세종특별자치시": (36.4800,127.2890),
    "경기도 수원시": (37.2636,127.0286),
    "경기도 성남시": (37.4200,127.1265),
    "경기도 고양시": (37.6584,126.8320),
    "경기도 용인시": (37.2411,127.1776),
    "강원특별자치도 춘천시": (37.8813,127.7300),
    "강원특별자치도 강릉시": (37.7519,128.8761),
    "충청북도 청주시": (36.6424,127.4890),
    "충청남도 천안시": (36.8151,127.1139),
    "충청남도 공주시": (36.4465,127.1190),
    "경상북도 포항시": (36.0190,129.3435),
    "경상북도 경주시": (35.8562,129.2247),
    "경상남도 창원시": (35.2279,128.6811),
    "경상남도 진주시": (35.1800,128.1076),
    "경상남도 통영시": (34.8544,128.4332),
    "제주특별자치도 제주시": (33.4996,126.5312),
    "제주특별자치도 서귀포시": (33.2541,126.5601),
}

PLACE_ALIASES = {
    "여수":"전라남도 여수시","여수시":"전라남도 여수시",
    "순천":"전라남도 순천시","순천시":"전라남도 순천시",
    "광양":"전라남도 광양시","광양시":"전라남도 광양시",
    "광주":"광주광역시","서울":"서울특별시","부산":"부산광역시",
    "대구":"대구광역시","인천":"인천광역시","대전":"대전광역시",
    "울산":"울산광역시","세종":"세종특별자치시","제주":"제주특별자치도 제주시",
}

ASPECTS = {
    "합": 0.0,
    "육십분위": 60.0,
    "사분위": 90.0,
    "삼분위": 120.0,
    "충": 180.0,
}

@lru_cache(maxsize=1)
def load_ephemeris():
    ts = load.timescale()
    try:
        eph = load("de440s.bsp")
        used = "DE440s"
        fallback_reason = None
    except Exception as exc:
        eph = load("de421.bsp")
        used = "DE421"
        fallback_reason = str(exc)

    targets = {}
    target_keys = {}
    for body, candidates in PLANET_KEYS.items():
        last_error = None
        for candidate in candidates:
            try:
                targets[body] = eph[candidate]
                target_keys[body] = candidate
                break
            except (KeyError, ValueError) as err:
                last_error = err
        else:
            raise KeyError(f"{used}에서 {body} target을 찾지 못했습니다: {last_error}")

    return ts, eph, eph["earth"], targets, target_keys, used, fallback_reason

def resolve_coordinates(place: str | None, lat: float | None, lon: float | None):
    if lat is not None and lon is not None:
        return float(lat), float(lon), (place or "직접 좌표")

    raw = (place or "").strip()
    if not raw:
        raise ValueError("출생지 또는 위도/경도를 입력해야 합니다.")

    canonical = PLACE_ALIASES.get(raw, raw)
    if canonical in KOREA_BIRTHPLACES:
        la, lo = KOREA_BIRTHPLACES[canonical]
        return float(la), float(lo), canonical

    # '전라남도 여수시 출생' 같은 입력도 최대한 매칭.
    for name, coords in KOREA_BIRTHPLACES.items():
        short = name.split()[-1].replace("시","").replace("군","")
        if short and short in raw:
            return float(coords[0]), float(coords[1]), name

    raise ValueError(
        f"현재 내장 출생지 목록에서 '{raw}'를 찾지 못했습니다. "
        "위도/경도를 직접 보내거나 API 출생지 목록을 확장해 주세요."
    )

def local_birth_to_utc(birth_date: str, birth_time: str, timezone_name: str):
    if not birth_date or not birth_time:
        raise ValueError("생년월일과 출생시각이 모두 필요합니다.")
    tz = ZoneInfo(timezone_name or "Asia/Seoul")
    naive = datetime.fromisoformat(f"{birth_date}T{birth_time}")
    local_dt = naive.replace(tzinfo=tz)
    return local_dt, local_dt.astimezone(UTC)

def sf_time(dt_aware):
    ts, *_ = load_ephemeris()
    return ts.from_datetime(dt_aware.astimezone(UTC))

def to_jd_ut(dt_utc):
    dt_utc = dt_utc.astimezone(UTC)
    hour = (
        dt_utc.hour
        + dt_utc.minute / 60.0
        + dt_utc.second / 3600.0
        + dt_utc.microsecond / 3_600_000_000.0
    )
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, hour, swe.GREG_CAL)

def get_tropical_ecliptic_lon(body_name, time_obj):
    _, _, earth, targets, _, _, _ = load_ephemeris()
    apparent = earth.at(time_obj).observe(targets[body_name]).apparent()
    _, lon, _ = apparent.frame_latlon(ecliptic_frame)
    return float(lon.degrees % 360.0)

def circular_delta(a, b):
    return (a - b + 180.0) % 360.0 - 180.0

def angular_separation(a, b):
    return abs(circular_delta(a, b))

def sign_data(lon):
    lon = float(lon % 360.0)
    idx = int(lon // 30)
    return {
        "sign": SIGNS_KO[idx],
        "sign_en": SIGNS_EN[idx],
        "degree": round(lon % 30.0, 6),
        "longitude": round(lon, 6),
        "sign_index": idx,
    }

def compute_houses(dt_utc, latitude, longitude):
    jd_ut = to_jd_ut(dt_utc)
    placidus_cusps, ascmc = swe.houses_ex(
        jd_ut, float(latitude), float(longitude), b"P", 0
    )
    asc = float(ascmc[0] % 360.0)
    mc = float(ascmc[1] % 360.0)
    vertex = float(ascmc[3] % 360.0)
    asc_sign = int(asc // 30)
    whole_cusps = [float(((asc_sign + i) % 12) * 30.0) for i in range(12)]
    return {
        "jd_ut": jd_ut,
        "asc": asc,
        "mc": mc,
        "vertex": vertex,
        "whole_cusps": whole_cusps,
        "placidus_cusps": [float(x % 360.0) for x in placidus_cusps],
    }

def whole_sign_house(lon, asc_lon):
    return (int((lon % 360) // 30) - int((asc_lon % 360) // 30)) % 12 + 1

def cusp_house(lon, cusps):
    lon %= 360.0
    for i in range(12):
        start = cusps[i] % 360.0
        end = cusps[(i + 1) % 12] % 360.0
        span = (end - start) % 360.0
        pos = (lon - start) % 360.0
        if span > 0 and pos < span:
            return i + 1
    return None

def sun_altitude_degrees(dt_utc, latitude, longitude):
    _, eph, earth, *_ = load_ephemeris()
    observer = earth + wgs84.latlon(
        latitude_degrees=float(latitude),
        longitude_degrees=float(longitude)
    )
    apparent = observer.at(sf_time(dt_utc)).observe(eph["sun"]).apparent()
    alt, _, _ = apparent.altaz()
    return float(alt.degrees)

def calculate_pof(asc_lon, sun_lon, moon_lon, day_chart):
    if day_chart:
        return (asc_lon + moon_lon - sun_lon) % 360.0
    return (asc_lon + sun_lon - moon_lon) % 360.0

def planet_motion(body, dt_utc):
    # 기존 astro-app의 apparent longitude를 그대로 이용한 중앙차분.
    window_hours = 0.25 if body == "Moon" else 1.0 if body in {"Sun","Mercury","Venus","Mars"} else 6.0
    past = get_tropical_ecliptic_lon(body, sf_time(dt_utc - timedelta(hours=window_hours)))
    now = get_tropical_ecliptic_lon(body, sf_time(dt_utc))
    future = get_tropical_ecliptic_lon(body, sf_time(dt_utc + timedelta(hours=window_hours)))
    speed = circular_delta(future, past) / ((2 * window_hours) / 24.0)
    direction = "순행" if speed > 0.002 else "역행" if speed < -0.002 else "정지권"
    return now, float(speed), direction

def natal_aspect_orb(body_a, body_b):
    # Natal 전용 보수적 오브.
    if "Sun" in {body_a, body_b} or "Moon" in {body_a, body_b}:
        return 6.0
    if body_a in {"Mercury","Venus","Mars"} or body_b in {"Mercury","Venus","Mars"}:
        return 5.0
    return 4.0

def compute_natal_aspects(longitudes):
    names = list(longitudes)
    out = []
    for i, a in enumerate(names):
        for b in names[i+1:]:
            sep = angular_separation(longitudes[a], longitudes[b])
            candidates = []
            for name, angle in ASPECTS.items():
                orb = abs(sep - angle)
                if orb <= natal_aspect_orb(a, b):
                    candidates.append((orb, name, angle))
            if not candidates:
                continue
            orb, name, angle = min(candidates)
            out.append({
                "a": a,
                "b": b,
                "aspect": name,
                "angle": angle,
                "orb": round(float(orb), 4),
            })
    out.sort(key=lambda x: x["orb"])
    return out

def compute_natal(
    birth_date: str,
    birth_time: str,
    place: str | None = None,
    timezone_name: str = "Asia/Seoul",
    lat: float | None = None,
    lon: float | None = None,
):
    latitude, longitude, resolved_place = resolve_coordinates(place, lat, lon)
    local_dt, dt_utc = local_birth_to_utc(birth_date, birth_time, timezone_name)

    houses = compute_houses(dt_utc, latitude, longitude)

    planets = {}
    longitudes = {}
    for body in PLANET_KEYS:
        lon_now, speed, direction = planet_motion(body, dt_utc)
        sd = sign_data(lon_now)
        longitudes[body] = lon_now
        planets[body] = {
            **sd,
            "name_ko": PLANET_KO[body],
            "whole_house": whole_sign_house(lon_now, houses["asc"]),
            "placidus_house": cusp_house(lon_now, houses["placidus_cusps"]),
            "speed_deg_per_day": round(speed, 6),
            "direction": direction,
            "retrograde": direction == "역행",
        }

    angles = {}
    for key, ko, value in [
        ("ASC","상승점",houses["asc"]),
        ("MC","중천점",houses["mc"]),
        ("Vertex","버텍스",houses["vertex"]),
    ]:
        angles[key] = {
            **sign_data(value),
            "name_ko": ko,
            "whole_house": whole_sign_house(value, houses["asc"]),
            "placidus_house": cusp_house(value, houses["placidus_cusps"]),
        }

    day_chart = sun_altitude_degrees(dt_utc, latitude, longitude) > 0.0
    pof_lon = calculate_pof(
        houses["asc"], planets["Sun"]["longitude"], planets["Moon"]["longitude"], day_chart
    )
    points = {
        "PartOfFortune": {
            **sign_data(pof_lon),
            "name_ko": "포르투나·행운점",
            "whole_house": whole_sign_house(pof_lon, houses["asc"]),
            "placidus_house": cusp_house(pof_lon, houses["placidus_cusps"]),
        }
    }

    _, _, _, _, target_keys, ephemeris_used, fallback_reason = load_ephemeris()

    return {
        "schema": "LUNEA_ASTRO_NATAL_V3",
        "birth": {
            "date": birth_date,
            "time": birth_time,
            "timezone": timezone_name,
            "place_input": place,
            "place_resolved": resolved_place,
            "latitude": latitude,
            "longitude": longitude,
            "local_iso": local_dt.isoformat(),
            "utc_iso": dt_utc.isoformat(),
        },
        "zodiac": "tropical",
        "house_policy": {
            "primary": "whole_sign",
            "secondary": "placidus",
        },
        "sect": "day" if day_chart else "night",
        "planets": planets,
        "angles": angles,
        "points": points,
        "aspects": compute_natal_aspects(longitudes),
        "cusps": {
            "whole_sign": [round(x, 6) for x in houses["whole_cusps"]],
            "placidus": [round(x, 6) for x in houses["placidus_cusps"]],
        },
        "meta": {
            "ephemeris": ephemeris_used,
            "ephemeris_fallback_reason": fallback_reason,
            "planet_target_keys": target_keys,
            "calculation": "Skyfield apparent tropical longitude + Swiss Ephemeris houses",
        },
    }
