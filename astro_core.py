from __future__ import annotations

from functools import lru_cache
from collections import Counter
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
# ============================================================
# LUNEA TRANSIT SCANNER V1
# - Reuses deterministic Natal payload produced above.
# - Whole Sign = primary event/topic house.
# - Placidus = secondary psychological/cusp emphasis.
# - Adaptive time grid + separate near-exact refinement.
# ============================================================

TRANSIT_ASPECTS = {
    "합": {"angle": 0.0, "activation": 1.00, "polarity": 0.00},
    "육십분위": {"angle": 60.0, "activation": 0.72, "polarity": 0.55},
    "사분위": {"angle": 90.0, "activation": 0.90, "polarity": -0.55},
    "삼분위": {"angle": 120.0, "activation": 0.82, "polarity": 0.65},
    "충": {"angle": 180.0, "activation": 1.00, "polarity": -0.45},
}

LAYER_BY_TRANSIT = {
    "Moon":"일일","Sun":"중기","Mercury":"중기","Venus":"중기","Mars":"중기",
    "Jupiter":"장기","Saturn":"장기","Uranus":"장기","Neptune":"장기","Pluto":"장기"
}

PLANET_TONE = {
    "Sun":0.15,"Moon":0.05,"Mercury":0.00,"Venus":0.45,"Mars":-0.25,
    "Jupiter":0.50,"Saturn":-0.45,"Uranus":-0.15,"Neptune":-0.10,
    "Pluto":-0.25,"ASC":0.0,"MC":0.0,"Vertex":0.0,"PartOfFortune":0.15
}

TRADITIONAL_RULER_BY_SIGN = {
    0:"Mars",1:"Venus",2:"Mercury",3:"Moon",4:"Sun",5:"Mercury",
    6:"Venus",7:"Mars",8:"Jupiter",9:"Saturn",10:"Saturn",11:"Jupiter"
}

TOPIC_SPECS = {
    "general": {
        "label":"전체 흐름",
        "targets":{"Sun":.70,"Moon":.75,"Mercury":.55,"Venus":.55,"Mars":.50,"Jupiter":.55,"Saturn":.55,"ASC":.70,"MC":.55},
        "transits":{"Moon":.75,"Sun":.55,"Mercury":.60,"Venus":.60,"Mars":.55,"Jupiter":.55,"Saturn":.55,"Uranus":.35,"Neptune":.30,"Pluto":.35},
        "houses":{1:.75,3:.45,5:.45,7:.55,10:.60,11:.45},
        "ruler_houses":[1,7,10],
    },
    "연락": {
        "label":"연락·메시지",
        "targets":{"Mercury":1.0,"Venus":.70,"Moon":.60,"Sun":.30,"ASC":.30},
        "transits":{"Mercury":1.0,"Moon":.85,"Venus":.70,"Mars":.35,"Jupiter":.30,"Saturn":.25,"Uranus":.35},
        "houses":{3:1.0,7:.85,1:.25,11:.30},
        "ruler_houses":[3,7],
    },
    "재회": {
        "label":"재회·과거 인연",
        "targets":{"Mercury":.90,"Venus":1.0,"Moon":.80,"Saturn":.65,"Pluto":.55,"ASC":.25},
        "transits":{"Mercury":.90,"Venus":1.0,"Moon":.75,"Saturn":.65,"Jupiter":.45,"Uranus":.45,"Pluto":.55},
        "houses":{3:.65,5:.80,7:1.0,8:.45,12:.40},
        "ruler_houses":[5,7,12],
    },
    "연애": {
        "label":"연애·호감",
        "targets":{"Venus":1.0,"Moon":.85,"Mars":.65,"Sun":.45,"Mercury":.35,"ASC":.45},
        "transits":{"Venus":1.0,"Moon":.85,"Mars":.65,"Mercury":.50,"Jupiter":.55,"Saturn":.35,"Sun":.35},
        "houses":{5:1.0,7:1.0,1:.35,8:.40},
        "ruler_houses":[5,7],
    },
    "시험": {
        "label":"시험·합격",
        "targets":{"Mercury":1.0,"Jupiter":.80,"Saturn":.85,"Mars":.55,"Moon":.45,"Sun":.45,"MC":.45},
        "transits":{"Mercury":1.0,"Jupiter":.75,"Saturn":.85,"Mars":.60,"Moon":.55,"Sun":.40},
        "houses":{3:.85,6:.65,9:1.0,10:.75},
        "ruler_houses":[3,9,10],
    },
    "학업": {
        "label":"학업·공부",
        "targets":{"Mercury":1.0,"Saturn":.80,"Sun":.55,"Mars":.45,"Moon":.35,"MC":.25},
        "transits":{"Mercury":1.0,"Saturn":.75,"Mars":.55,"Sun":.50,"Moon":.45,"Jupiter":.35},
        "houses":{3:1.0,6:.80,9:1.0,10:.30},
        "ruler_houses":[3,6,9],
    },
    "직장": {
        "label":"직장·업무",
        "targets":{"MC":1.0,"Sun":.85,"Saturn":.90,"Mercury":.70,"Jupiter":.70,"Mars":.55,"Moon":.30},
        "transits":{"Saturn":.90,"Jupiter":.85,"Sun":.70,"Mercury":.70,"Mars":.65,"Uranus":.45,"Moon":.30},
        "houses":{6:.90,10:1.0,2:.45,11:.40},
        "ruler_houses":[6,10],
    },
    "이직": {
        "label":"이직·커리어 전환",
        "targets":{"MC":1.0,"Jupiter":.90,"Uranus":.90,"Mercury":.70,"Saturn":.65,"Venus":.55,"Sun":.45},
        "transits":{"Jupiter":.95,"Uranus":1.0,"Mercury":.75,"Saturn":.70,"Venus":.60,"Sun":.45,"Mars":.40},
        "houses":{6:.55,10:1.0,2:.55,9:.65,11:.75},
        "ruler_houses":[6,10,11],
    },
    "금전": {
        "label":"금전·재물",
        "targets":{"Venus":1.0,"Jupiter":.90,"Mercury":.65,"Saturn":.50,"Moon":.25,"MC":.30},
        "transits":{"Venus":1.0,"Jupiter":.95,"Mercury":.70,"Saturn":.55,"Mars":.40,"Moon":.35,"Uranus":.35},
        "houses":{2:1.0,8:.70,11:.80,10:.30},
        "ruler_houses":[2,8,11],
    },
    "소식": {
        "label":"소식·문서",
        "targets":{"Mercury":1.0,"Moon":.65,"Jupiter":.60,"Uranus":.60,"MC":.45,"Sun":.30},
        "transits":{"Mercury":1.0,"Moon":.80,"Jupiter":.60,"Uranus":.65,"Saturn":.35,"Sun":.30},
        "houses":{3:1.0,9:.70,10:.70,11:.70},
        "ruler_houses":[3,9,10,11],
    },
    "투자심리": {
        "label":"투자 판단·심리",
        "targets":{"Mercury":.90,"Mars":.80,"Jupiter":.75,"Saturn":.70,"Uranus":.65,"Moon":.40},
        "transits":{"Mercury":.90,"Mars":.85,"Jupiter":.80,"Saturn":.75,"Uranus":.75,"Moon":.55,"Venus":.45},
        "houses":{2:.95,5:.80,8:.75,11:.85},
        "ruler_houses":[2,5,8,11],
    },
}

def _as_aware_utc(value):
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)

def _sample_datetimes(start_dt_utc, end_dt_utc, step_hours):
    out = []
    cur = start_dt_utc
    step = timedelta(hours=float(step_hours))
    while cur <= end_dt_utc:
        out.append(cur)
        cur += step
    if not out or out[-1] < end_dt_utc:
        out.append(end_dt_utc)
    return out

def get_tropical_ecliptic_lons(body_name, datetimes_utc):
    if not datetimes_utc:
        return np.array([], dtype=float)
    ts, _, earth, targets, _, _, _ = load_ephemeris()
    times = ts.from_datetimes([d.astimezone(UTC) for d in datetimes_utc])
    apparent = earth.at(times).observe(targets[body_name]).apparent()
    _, lon, _ = apparent.frame_latlon(ecliptic_frame)

    # Skyfield can return an ndarray with an extra singleton axis depending
    # on vectorized target/time shapes. Transit Scanner expects a strict
    # 1-D sequence where one index == one sampled datetime.
    arr = np.asarray(lon.degrees, dtype=float)
    arr = np.ravel(arr)
    if arr.size != len(datetimes_utc):
        arr = np.squeeze(np.asarray(lon.degrees, dtype=float))
        arr = np.ravel(arr)
    if arr.size != len(datetimes_utc):
        raise ValueError(
            f"{body_name} vector longitude shape mismatch: "
            f"{arr.size} values for {len(datetimes_utc)} datetimes"
        )
    return np.mod(arr, 360.0)

def circular_delta_array(a, b):
    arr = np.ravel(np.asarray(a, dtype=float))
    return (arr - float(b) + 180.0) % 360.0 - 180.0

def max_orb_for(body, aspect_name):
    if body == "Moon":
        base = 2.6
    elif body in {"Sun","Mercury","Venus","Mars"}:
        base = 3.0
    else:
        base = 2.5
    if aspect_name in {"합","충"}:
        base += 0.35
    return base

def orb_weight(orb, max_orb):
    if orb <= .40: return 1.0
    if orb <= .90: return .86
    if orb <= 1.60: return .68
    if orb <= 2.30: return .50
    if orb <= max_orb: return .32
    return 0.0

def house_ruler(house_no, asc_lon):
    asc_sign = int((float(asc_lon) % 360.0) // 30)
    return TRADITIONAL_RULER_BY_SIGN[(asc_sign + int(house_no) - 1) % 12]

def aspect_polarity(record):
    base = record["base_polarity"]
    transit_tone = PLANET_TONE.get(record["transit"], 0.0)
    target_tone = PLANET_TONE.get(record["target"], 0.0)
    if record["aspect"] == "합":
        value = .70 * transit_tone + .30 * target_tone
    else:
        value = .75 * base + .30 * transit_tone + .10 * target_tone
    return max(-1.0, min(1.0, value))

def direction_modifier(topic, body, direction):
    if direction == "정지권":
        return 1.06, 0.0
    if direction != "역행":
        return 1.0, 0.0
    if topic == "재회" and body in {"Mercury","Venus"}:
        return 1.10, -0.02
    if topic in {"연락","소식"} and body == "Mercury":
        return 1.02, -0.07
    if topic in {"직장","이직","시험","학업"} and body == "Mercury":
        return .98, -0.05
    return 1.0, -0.02

def _natal_payload_parts(natal):
    if not isinstance(natal, dict):
        raise ValueError("Natal payload가 필요합니다.")
    planets = natal.get("planets") or {}
    angles = natal.get("angles") or {}
    points = natal.get("points") or {}
    cusps = natal.get("cusps") or {}

    asc = (angles.get("ASC") or {}).get("longitude")
    if asc is None:
        raise ValueError("Natal ASC가 없습니다.")

    placidus = cusps.get("placidus")
    if not isinstance(placidus, list) or len(placidus) != 12:
        raise ValueError("Natal Placidus cusp 12개가 필요합니다.")

    targets = {}
    for key, value in planets.items():
        if isinstance(value, dict) and value.get("longitude") is not None:
            targets[key] = float(value["longitude"])
    for key in ["ASC","MC","Vertex"]:
        value = angles.get(key)
        if isinstance(value, dict) and value.get("longitude") is not None:
            targets[key] = float(value["longitude"])
    pof = points.get("PartOfFortune")
    if isinstance(pof, dict) and pof.get("longitude") is not None:
        targets["PartOfFortune"] = float(pof["longitude"])

    return targets, float(asc), [float(x) for x in placidus]

def _topic_spec(topic):
    key = topic if topic in TOPIC_SPECS else "general"
    return key, TOPIC_SPECS[key]

def _transit_bodies_for_topic(spec):
    return [b for b in PLANET_KEYS if spec["transits"].get(b, 0.0) > 0]

def _target_weight(spec, target, asc_lon):
    w = spec["targets"].get(target, 0.0)
    if target in PLANET_KEYS:
        rulers = {house_ruler(h, asc_lon) for h in spec["ruler_houses"]}
        if target in rulers:
            w += .18
    return w

def _motion_arrays(body, sample_times):
    h = 0.25 if body == "Moon" else 1.0 if body in {"Sun","Mercury","Venus","Mars"} else 6.0
    past_times = [d - timedelta(hours=h) for d in sample_times]
    future_times = [d + timedelta(hours=h) for d in sample_times]

    now = np.ravel(get_tropical_ecliptic_lons(body, sample_times))
    past = np.ravel(get_tropical_ecliptic_lons(body, past_times))
    future = np.ravel(get_tropical_ecliptic_lons(body, future_times))

    n = len(sample_times)
    if not (now.size == past.size == future.size == n):
        raise ValueError(
            f"{body} transit vector size mismatch: "
            f"now={now.size}, past={past.size}, future={future.size}, samples={n}"
        )

    # Elementwise circular difference. Do not cast the whole vector to float.
    speed = (future - past + 180.0) % 360.0 - 180.0
    speed = np.ravel(speed / ((2*h) / 24.0))
    return now, past, future, speed

def _best_aspect_record(body, target, target_lon, lon_now, lon_past, lon_future, speed):
    sep = abs(circular_delta(float(lon_now), target_lon))
    best = None
    for name, spec in TRANSIT_ASPECTS.items():
        orb = abs(sep - spec["angle"])
        max_orb = max_orb_for(body, name)
        if orb > max_orb:
            continue
        past_orb = abs(abs(circular_delta(float(lon_past), target_lon)) - spec["angle"])
        future_orb = abs(abs(circular_delta(float(lon_future), target_lon)) - spec["angle"])
        if orb <= .03:
            motion, motion_mult = "정확(Exact)", 1.15
        elif future_orb < past_orb - 1e-5:
            motion, motion_mult = "적용(Applying)", 1.08
        elif future_orb > past_orb + 1e-5:
            motion, motion_mult = "분리(Separating)", .92
        else:
            motion, motion_mult = "변화 미미", 1.0
        direction = "순행" if speed > .002 else "역행" if speed < -.002 else "정지권"
        rec = {
            "transit":body,"target":target,"aspect":name,"angle":spec["angle"],
            "orb":float(orb),"orb_weight":orb_weight(orb,max_orb),
            "motion":motion,"motion_mult":motion_mult,"direction":direction,
            "activation_mult":spec["activation"],"base_polarity":spec["polarity"],
        }
        if best is None or rec["orb"] < best["orb"]:
            best = rec
    return best

def _score_sample(topic, spec, targets, asc_lon, placidus_cusps, body_rows, idx):
    raw_activation = 0.0
    polarity_num = 0.0
    polarity_den = 0.0
    evidences = []
    layers = set()

    for body, rows in body_rows.items():
        lon_now = float(np.ravel(rows["now"])[idx])
        lon_past = float(np.ravel(rows["past"])[idx])
        lon_future = float(np.ravel(rows["future"])[idx])
        speed = float(np.ravel(rows["speed"])[idx])
        transit_w = spec["transits"].get(body,0.0)
        if transit_w <= 0:
            continue

        w_house = whole_sign_house(lon_now, asc_lon)
        p_house = cusp_house(lon_now, placidus_cusps)

        for target, target_lon in targets.items():
            target_w = _target_weight(spec, target, asc_lon)
            if target_w <= 0:
                continue
            rec = _best_aspect_record(
                body,target,target_lon,lon_now,lon_past,lon_future,speed
            )
            if not rec:
                continue

            dir_mult, dir_pol = direction_modifier(topic, body, rec["direction"])
            contribution = (
                rec["orb_weight"] * rec["motion_mult"] * rec["activation_mult"]
                * transit_w * target_w * dir_mult
            )
            if contribution <= 0:
                continue
            rec["score"] = contribution
            rec["whole_house"] = w_house
            rec["placidus_house"] = p_house
            pol = max(-1.0, min(1.0, aspect_polarity(rec) + dir_pol))
            rec["polarity"] = pol
            raw_activation += contribution
            polarity_num += contribution * pol
            polarity_den += contribution
            layers.add(LAYER_BY_TRANSIT[body])
            evidences.append(rec)

        w_weight = spec["houses"].get(w_house,0.0)
        p_weight = spec["houses"].get(p_house,0.0) if p_house else 0.0
        house_contrib = .22*transit_w*w_weight + .09*transit_w*p_weight
        if house_contrib > 0:
            raw_activation += house_contrib
            layers.add(LAYER_BY_TRANSIT[body])
            evidences.append({
                "kind":"house","transit":body,"score":house_contrib,
                "whole_house":w_house,"placidus_house":p_house,
                "whole_relevant":bool(w_weight),"placidus_relevant":bool(p_weight),
            })

    aspect_evidence = [e for e in evidences if e.get("kind") != "house"]
    strong_count = sum(1 for e in aspect_evidence if e["score"] >= .50)
    stacking_bonus = min(7.0, max(0,len(layers)-1)*2.0 + min(3,strong_count)*.8)
    activation = max(0.0, min(100.0, raw_activation*18.0 + stacking_bonus))
    favorability = 50.0
    if polarity_den:
        favorability = max(0.0, min(100.0, 50.0 + (polarity_num/polarity_den)*40.0))

    evidences.sort(key=lambda x:x.get("score",0), reverse=True)
    return {
        "activation":int(round(activation)),
        "favorability":int(round(favorability)),
        "layers":sorted(layers),
        "evidence":evidences[:6],
    }

def _adaptive_step_hours(days):
    if days <= 14: return 6.0
    if days <= 45: return 12.0
    return 24.0

def _iso_local(dt_utc, timezone_name):
    tz = ZoneInfo(timezone_name or "Asia/Seoul")
    return dt_utc.astimezone(tz).isoformat()

def _summarize_evidence(evidences, limit=4):
    aspect_rows = [e for e in evidences if e.get("aspect")]
    counts = Counter(
        (e["transit"],e["target"],e["aspect"])
        for e in aspect_rows
    )
    out = []
    for (body,target,aspect), count in counts.most_common(limit):
        best = min(
            (e for e in aspect_rows if e["transit"]==body and e["target"]==target and e["aspect"]==aspect),
            key=lambda e:e["orb"]
        )
        out.append({
            "transit":body,"transit_ko":PLANET_KO.get(body,body),
            "target":target,
            "aspect":aspect,
            "best_orb":round(float(best["orb"]),3),
            "motion":best.get("motion"),
            "direction":best.get("direction"),
            "count":count,
        })
    return out

def _windowize(samples, threshold, step_hours, timezone_name, caution=False):
    qualifying = []
    for i,s in enumerate(samples):
        if s["activation"] < threshold:
            continue
        if caution and s["favorability"] > 42:
            continue
        qualifying.append(i)
    if not qualifying:
        return []

    groups = []
    cur = [qualifying[0]]
    for idx in qualifying[1:]:
        if idx == cur[-1] + 1:
            cur.append(idx)
        else:
            groups.append(cur)
            cur = [idx]
    groups.append(cur)

    windows = []
    half = timedelta(hours=step_hours/2)
    for g in groups:
        rows = [samples[i] for i in g]
        peak = max(rows, key=lambda x:(x["activation"],x["favorability"]))
        all_ev = []
        for r in rows:
            all_ev.extend(r.get("evidence",[]))
        start_dt = rows[0]["dt_utc"] - half
        end_dt = rows[-1]["dt_utc"] + half
        windows.append({
            "start":_iso_local(start_dt,timezone_name),
            "end":_iso_local(end_dt,timezone_name),
            "peak":_iso_local(peak["dt_utc"],timezone_name),
            "peak_activation":peak["activation"],
            "peak_favorability":peak["favorability"],
            "evidence":_summarize_evidence(all_ev),
        })
    windows.sort(key=lambda x:(x["peak_activation"],x["peak_favorability"]), reverse=True)
    return windows

def _aspect_orb_at(body, target_lon, aspect_angle, dt_utc):
    lon = get_tropical_ecliptic_lon(body, sf_time(dt_utc))
    return abs(abs(circular_delta(lon,target_lon)) - aspect_angle)

def _refine_minimum_orb(body, target_lon, aspect_angle, left_dt, right_dt, iterations=16):
    # Ternary minimization around a coarse local minimum.
    a, b = left_dt, right_dt
    for _ in range(iterations):
        span = b - a
        m1 = a + span/3
        m2 = b - span/3
        f1 = _aspect_orb_at(body,target_lon,aspect_angle,m1)
        f2 = _aspect_orb_at(body,target_lon,aspect_angle,m2)
        if f1 <= f2:
            b = m2
        else:
            a = m1
    mid = a + (b-a)/2
    return mid, _aspect_orb_at(body,target_lon,aspect_angle,mid)

def _exact_grid_step(body, days):
    if body == "Moon":
        return 3.0 if days <= 45 else 6.0
    if body in {"Mercury","Venus","Mars","Sun"}:
        return 6.0 if days <= 45 else 12.0
    return 24.0

def _find_exact_hits(spec, targets, asc_lon, start_dt, end_dt, days, timezone_name):
    candidates = []
    bodies = _transit_bodies_for_topic(spec)
    for body in bodies:
        step = _exact_grid_step(body, days)
        times = _sample_datetimes(start_dt,end_dt,step)
        lons = get_tropical_ecliptic_lons(body,times)

        for target,target_lon in targets.items():
            tw = _target_weight(spec,target,asc_lon)
            if tw <= 0:
                continue
            for aspect_name, aspect_spec in TRANSIT_ASPECTS.items():
                angle = aspect_spec["angle"]
                orbs = np.abs(np.abs(circular_delta_array(lons,target_lon)) - angle)
                if len(orbs) < 3:
                    continue
                for i in range(1,len(orbs)-1):
                    if orbs[i] <= orbs[i-1] and orbs[i] <= orbs[i+1] and orbs[i] <= 1.0:
                        candidates.append({
                            "coarse_orb":float(orbs[i]),
                            "body":body,"target":target,"target_lon":target_lon,
                            "aspect":aspect_name,"angle":angle,
                            "left":times[i-1],"right":times[i+1],
                            "weight":spec["transits"].get(body,0)*tw*aspect_spec["activation"],
                        })

    # Refine only strongest/closest candidates to keep free server responsive.
    candidates.sort(key=lambda x:(x["coarse_orb"],-x["weight"]))
    hits = []
    for c in candidates[:28]:
        dt, orb = _refine_minimum_orb(
            c["body"],c["target_lon"],c["angle"],c["left"],c["right"]
        )
        if orb > .25:
            continue
        _, speed, direction = planet_motion(c["body"],dt)
        hits.append({
            "time":_iso_local(dt,timezone_name),
            "transit":c["body"],
            "transit_ko":PLANET_KO.get(c["body"],c["body"]),
            "target":c["target"],
            "aspect":c["aspect"],
            "orb":round(float(orb),4),
            "precision":"exact" if orb <= .08 else "near_exact",
            "direction":direction,
            "score":round(float(c["weight"])/(1.0+orb),4),
        })

    # Deduplicate same hit found from adjacent local minima.
    hits.sort(key=lambda x:(x["time"],x["transit"],x["target"],x["aspect"]))
    dedup = []
    for h in hits:
        duplicate = False
        hdt = datetime.fromisoformat(h["time"])
        for old in dedup[-8:]:
            if (
                old["transit"]==h["transit"] and old["target"]==h["target"]
                and old["aspect"]==h["aspect"]
                and abs((hdt-datetime.fromisoformat(old["time"])).total_seconds()) < 3*3600
            ):
                duplicate = True
                if h["orb"] < old["orb"]:
                    old.update(h)
                break
        if not duplicate:
            dedup.append(h)

    dedup.sort(key=lambda x:(-x["score"],x["orb"]))
    return dedup[:12]

def scan_transits(natal, topic="general", start_iso=None, days=30, timezone_name="Asia/Seoul"):
    days = int(days)
    if days < 1 or days > 120:
        raise ValueError("트랜짓 스캔 기간은 1~120일이어야 합니다.")

    topic_key, spec = _topic_spec(topic)
    targets, asc_lon, placidus_cusps = _natal_payload_parts(natal)

    start_dt = _as_aware_utc(start_iso)
    end_dt = start_dt + timedelta(days=days)
    step_hours = _adaptive_step_hours(days)
    sample_times = _sample_datetimes(start_dt,end_dt,step_hours)

    body_rows = {}
    for body in _transit_bodies_for_topic(spec):
        now,past,future,speed = _motion_arrays(body,sample_times)
        body_rows[body] = {"now":now,"past":past,"future":future,"speed":speed}

    samples = []
    for idx,dt in enumerate(sample_times):
        scored = _score_sample(
            topic_key,spec,targets,asc_lon,placidus_cusps,body_rows,idx
        )
        samples.append({"dt_utc":dt,**scored})

    max_activation = max((s["activation"] for s in samples), default=0)
    percentile75 = float(np.percentile([s["activation"] for s in samples],75)) if samples else 0
    peak_threshold = max(45.0, min(float(max_activation), max(percentile75, max_activation*.72)))
    if max_activation < 45:
        peak_threshold = max_activation + 1  # intentionally yields no "strong" windows

    peak_windows = _windowize(
        samples,peak_threshold,step_hours,timezone_name,caution=False
    )
    caution_threshold = max(40.0, max_activation*.60)
    caution_windows = _windowize(
        samples,caution_threshold,step_hours,timezone_name,caution=True
    )

    strongest_samples = sorted(
        samples,key=lambda x:(x["activation"],x["favorability"]),reverse=True
    )[:5]

    exact_hits = _find_exact_hits(
        spec,targets,asc_lon,start_dt,end_dt,days,timezone_name
    )

    # JSON-safe compact timeline.
    timeline = [{
        "time":_iso_local(s["dt_utc"],timezone_name),
        "activation":s["activation"],
        "favorability":s["favorability"],
    } for s in samples]

    overall = {
        "max_activation":max_activation,
        "average_activation":int(round(np.mean([s["activation"] for s in samples]))) if samples else 0,
        "average_favorability":int(round(np.mean([s["favorability"] for s in samples]))) if samples else 50,
        "strong_signal":bool(max_activation >= 45),
    }

    top_points = [{
        "time":_iso_local(s["dt_utc"],timezone_name),
        "activation":s["activation"],
        "favorability":s["favorability"],
        "evidence":_summarize_evidence(s["evidence"]),
    } for s in strongest_samples]

    return {
        "schema":"LUNEA_TRANSIT_SCAN_V1",
        "topic":topic_key,
        "topic_label":spec["label"],
        "range":{
            "start":_iso_local(start_dt,timezone_name),
            "end":_iso_local(end_dt,timezone_name),
            "days":days,
            "timezone":timezone_name,
            "sample_step_hours":step_hours,
        },
        "overall":overall,
        "peak_windows":peak_windows[:5],
        "caution_windows":caution_windows[:4],
        "exact_hits":exact_hits,
        "top_points":top_points,
        "timeline":timeline,
        "rules":{
            "zodiac":"tropical",
            "house_primary":"whole_sign",
            "house_secondary":"placidus",
            "note":"Transit activation is a timing/activation signal, not a guaranteed event outcome."
        }
    }
