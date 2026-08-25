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
# LUNEA HORARY V1
# - A separate question-moment chart. It never reuses natal data.
# - Tropical zodiac + Regiomontanus houses.
# - Traditional seven planets and Ptolemaic aspects only.
# - Produces deterministic calculation evidence; final judgment remains
#   interpretive and must preserve the original question.
# ============================================================

HORARY_PLANETS = ("Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn")

HORARY_ASPECTS = {
    "conjunction": {"angle": 0.0, "label_ko": "합"},
    "sextile": {"angle": 60.0, "label_ko": "육십분위"},
    "square": {"angle": 90.0, "label_ko": "사분위"},
    "trine": {"angle": 120.0, "label_ko": "삼분위"},
    "opposition": {"angle": 180.0, "label_ko": "충"},
}

HORARY_RULER_BY_SIGN = (
    "Mars", "Venus", "Mercury", "Moon", "Sun", "Mercury",
    "Venus", "Mars", "Jupiter", "Saturn", "Saturn", "Jupiter",
)

HORARY_EXALTATION_BY_SIGN = (
    "Sun", "Moon", None, "Jupiter", None, "Mercury",
    "Saturn", None, None, "Mars", None, "Venus",
)

HORARY_TOPIC_SPECS = {
    "general": {
        "label_ko": "일반·특정 상대",
        "quesited_house": 7,
        "event_house": None,
        "note": "일반 질문의 기본 상대축으로 7하우스를 사용합니다.",
    },
    "relationship": {
        "label_ko": "연애·상대방",
        "quesited_house": 7,
        "event_house": 5,
        "note": "특정 상대는 7하우스, 연애의 전개는 5하우스를 보조로 봅니다.",
    },
    "reconciliation": {
        "label_ko": "재회·관계 회복",
        "quesited_house": 7,
        "event_house": None,
        "note": "질문자와 특정 상대의 1–7하우스 관계축을 우선합니다.",
    },
    "contact": {
        "label_ko": "연락·메시지",
        "quesited_house": 7,
        "event_house": 9,
        "note": "특정 상대는 7하우스, 상대의 연락은 7하우스에서 파생한 3번째인 9하우스를 보조로 봅니다.",
    },
    "career": {
        "label_ko": "직장·이직·커리어",
        "quesited_house": 10,
        "event_house": None,
        "note": "직업·지위·결과를 나타내는 10하우스를 사용합니다.",
    },
    "exam": {
        "label_ko": "시험·합격",
        "quesited_house": 9,
        "event_house": 10,
        "note": "학업·시험은 9하우스, 판정·결과는 10하우스를 보조로 봅니다.",
    },
    "money": {
        "label_ko": "금전·재물",
        "quesited_house": 2,
        "event_house": None,
        "note": "질문자의 자산과 현금 흐름을 나타내는 2하우스를 사용합니다.",
    },
    "stock": {
        "label_ko": "주식·투기적 투자",
        "quesited_house": 5,
        "event_house": 2,
        "note": "투기·위험 감수는 5하우스, 실제 자금은 2하우스를 보조로 봅니다.",
    },
    "home": {
        "label_ko": "집·부동산·가족 기반",
        "quesited_house": 4,
        "event_house": None,
        "note": "집·토지·가족 기반을 나타내는 4하우스를 사용합니다.",
    },
    "health": {
        "label_ko": "건강·회복",
        "quesited_house": 6,
        "event_house": 1,
        "note": "질병·관리의 6하우스와 질문자 신체의 1하우스를 함께 봅니다.",
    },
    "legal": {
        "label_ko": "법률·소송·공적 판단",
        "quesited_house": 9,
        "event_house": 10,
        "note": "법률은 9하우스, 판결·공적 결과는 10하우스를 보조로 봅니다.",
    },
}

def _horary_local_to_utc(question_iso: str, timezone_name: str):
    if not question_iso:
        raise ValueError("질문을 처음 분명하게 이해한 시각이 필요합니다.")
    tz = ZoneInfo(timezone_name or "Asia/Seoul")
    raw = str(question_iso).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("질문 시각은 ISO 형식이어야 합니다.") from exc
    if dt.tzinfo is None:
        local_dt = dt.replace(tzinfo=tz)
    else:
        local_dt = dt.astimezone(tz)
    return local_dt, local_dt.astimezone(UTC)

def compute_regiomontanus_houses(dt_utc, latitude, longitude):
    jd_ut = to_jd_ut(dt_utc)
    cusps, ascmc = swe.houses_ex(
        jd_ut, float(latitude), float(longitude), b"R", 0
    )
    return {
        "jd_ut": jd_ut,
        "asc": float(ascmc[0] % 360.0),
        "mc": float(ascmc[1] % 360.0),
        "vertex": float(ascmc[3] % 360.0),
        "cusps": [float(x % 360.0) for x in cusps],
    }

def _horary_ruler_for_cusp(cusp_lon):
    return HORARY_RULER_BY_SIGN[int((cusp_lon % 360.0) // 30)]

def _horary_aspect_limit(body_a, body_b, aspect_key):
    base = {
        "conjunction": 8.0,
        "sextile": 5.0,
        "square": 7.0,
        "trine": 7.0,
        "opposition": 8.0,
    }[aspect_key]
    if "Moon" in {body_a, body_b}:
        base += 2.0
    elif "Sun" in {body_a, body_b}:
        base += 1.0
    return base

def _horary_aspect_state(body_a, row_a, body_b, row_b):
    sep_now = angular_separation(row_a["longitude"], row_b["longitude"])
    candidates = []
    for key, spec in HORARY_ASPECTS.items():
        candidates.append((abs(sep_now - spec["angle"]), key, spec))
    orb, key, spec = min(candidates)
    limit = _horary_aspect_limit(body_a, body_b, key)

    hours = 1.0 if "Moon" in {body_a, body_b} else 3.0
    fraction = hours / 24.0
    sep_past = angular_separation(
        row_a["longitude"] - row_a["speed_deg_per_day"] * fraction,
        row_b["longitude"] - row_b["speed_deg_per_day"] * fraction,
    )
    sep_future = angular_separation(
        row_a["longitude"] + row_a["speed_deg_per_day"] * fraction,
        row_b["longitude"] + row_b["speed_deg_per_day"] * fraction,
    )
    orb_past = abs(sep_past - spec["angle"])
    orb_future = abs(sep_future - spec["angle"])

    if orb <= 0.05:
        phase = "exact"
        phase_ko = "정확"
    elif orb <= limit and orb_future + 0.005 < orb:
        phase = "applying"
        phase_ko = "적용"
    elif orb <= limit and orb_past + 0.005 < orb:
        phase = "separating"
        phase_ko = "분리"
    elif orb <= limit:
        phase = "unclear"
        phase_ko = "정지·전환 확인 필요"
    else:
        phase = "out_of_orb"
        phase_ko = "유효 오브 밖"

    return {
        "a": body_a,
        "a_ko": PLANET_KO[body_a],
        "b": body_b,
        "b_ko": PLANET_KO[body_b],
        "aspect": key,
        "aspect_ko": spec["label_ko"],
        "angle": spec["angle"],
        "orb": round(float(orb), 4),
        "max_orb": round(float(limit), 2),
        "phase": phase,
        "phase_ko": phase_ko,
        "within_orb": bool(orb <= limit),
        "relative_speed_deg_per_day": round(
            abs(row_a["speed_deg_per_day"] - row_b["speed_deg_per_day"]), 6
        ),
    }

def _horary_dignity(body, sign_index):
    if HORARY_RULER_BY_SIGN[sign_index] == body:
        return "domicile", "본질적 존귀·도머사일"
    if HORARY_EXALTATION_BY_SIGN[sign_index] == body:
        return "exaltation", "고양"
    opposite = (sign_index + 6) % 12
    if HORARY_RULER_BY_SIGN[opposite] == body:
        return "detriment", "손상·디트리먼트"
    if HORARY_EXALTATION_BY_SIGN[opposite] == body:
        return "fall", "추락"
    return "peregrine", "무권위·페레그린"

def _horary_reception(body_a, row_a, body_b, row_b):
    a_sign = int(row_a["sign_index"])
    b_sign = int(row_b["sign_index"])
    a_in_b_domicile = HORARY_RULER_BY_SIGN[a_sign] == body_b
    b_in_a_domicile = HORARY_RULER_BY_SIGN[b_sign] == body_a
    a_in_b_exaltation = HORARY_EXALTATION_BY_SIGN[a_sign] == body_b
    b_in_a_exaltation = HORARY_EXALTATION_BY_SIGN[b_sign] == body_a
    return {
        "a": body_a,
        "b": body_b,
        "a_in_b_domicile": a_in_b_domicile,
        "b_in_a_domicile": b_in_a_domicile,
        "a_in_b_exaltation": a_in_b_exaltation,
        "b_in_a_exaltation": b_in_a_exaltation,
        "mutual_domicile": a_in_b_domicile and b_in_a_domicile,
        "mutual_reception": (
            (a_in_b_domicile or a_in_b_exaltation)
            and (b_in_a_domicile or b_in_a_exaltation)
        ),
        "has_reception": (
            a_in_b_domicile or b_in_a_domicile
            or a_in_b_exaltation or b_in_a_exaltation
        ),
    }

def _horary_refine_pair(body_a, body_b, aspect_angle, left_dt, right_dt, iterations=12):
    def orb_at(dt):
        a = get_tropical_ecliptic_lon(body_a, sf_time(dt))
        b = get_tropical_ecliptic_lon(body_b, sf_time(dt))
        return abs(angular_separation(a, b) - aspect_angle)

    left, right = left_dt, right_dt
    for _ in range(iterations):
        span = right - left
        m1 = left + span / 3
        m2 = right - span / 3
        if orb_at(m1) <= orb_at(m2):
            right = m2
        else:
            left = m1
    exact = left + (right - left) / 2
    return exact, orb_at(exact)

def _horary_perfection_candidate(body_a, row_a, body_b, row_b, dt_utc, timezone_name):
    if body_a == body_b:
        return {
            "perfects": False,
            "reason": "same_significator",
            "reason_ko": "질문자와 대상의 주인이 같아 두 행성 간 적용각으로 판정할 수 없습니다.",
        }

    aspect = _horary_aspect_state(body_a, row_a, body_b, row_b)
    if aspect["phase"] not in {"applying", "exact"}:
        return {
            "perfects": False,
            "reason": "no_applying_aspect",
            "reason_ko": "현재 유효 오브 안에서 두 주인행성의 적용각이 확인되지 않습니다.",
            "aspect": aspect,
        }
    if aspect["phase"] == "exact":
        return {
            "perfects": True,
            "reason": "exact_now",
            "reason_ko": "질문 시각에 두 주인행성의 각이 이미 정확합니다.",
            "aspect": aspect,
            "exact_utc": dt_utc.isoformat(),
            "exact_local": _iso_local(dt_utc, timezone_name),
            "days_from_question": 0.0,
            "before_sign_change": True,
        }

    rel_speed = aspect["relative_speed_deg_per_day"]
    if rel_speed < 0.01:
        return {
            "perfects": False,
            "reason": "relative_motion_too_slow",
            "reason_ko": "상대 속도가 너무 느려 성사 시각을 안정적으로 잡을 수 없습니다.",
            "aspect": aspect,
        }

    rough_days = aspect["orb"] / rel_speed
    max_days = min(30.0, max(2.0, rough_days * 1.8 + 1.0))
    step_hours = 1.0 if "Moon" in {body_a, body_b} else 3.0
    times = _sample_datetimes(dt_utc, dt_utc + timedelta(days=max_days), step_hours)
    a_lons = get_tropical_ecliptic_lons(body_a, times)
    b_lons = get_tropical_ecliptic_lons(body_b, times)
    seps = np.abs((a_lons - b_lons + 180.0) % 360.0 - 180.0)
    orbs = np.abs(seps - aspect["angle"])
    idx = int(np.argmin(orbs))

    if float(orbs[idx]) > 0.35:
        return {
            "perfects": False,
            "reason": "aspect_does_not_perfect",
            "reason_ko": "적용 중으로 보이지만 30일 안에 정확각 성사가 확인되지 않습니다.",
            "aspect": aspect,
        }

    left = times[max(0, idx - 1)]
    right = times[min(len(times) - 1, idx + 1)]
    exact_dt, exact_orb = _horary_refine_pair(
        body_a, body_b, aspect["angle"], left, right
    )
    a_exact = get_tropical_ecliptic_lon(body_a, sf_time(exact_dt))
    b_exact = get_tropical_ecliptic_lon(body_b, sf_time(exact_dt))
    before_sign_change = (
        int(a_exact // 30) == int(row_a["longitude"] // 30)
        and int(b_exact // 30) == int(row_b["longitude"] // 30)
    )
    days_from = (exact_dt - dt_utc).total_seconds() / 86400.0
    return {
        "perfects": bool(before_sign_change),
        "reason": "perfects" if before_sign_change else "sign_change_before_perfection",
        "reason_ko": (
            "두 주인행성의 적용각이 별자리 변경 전에 정확해집니다."
            if before_sign_change
            else "정확각 후보 전 한쪽 주인행성이 별자리를 바꾸므로 단순 성사로 판정하지 않습니다."
        ),
        "aspect": aspect,
        "exact_utc": exact_dt.isoformat(),
        "exact_local": _iso_local(exact_dt, timezone_name),
        "exact_orb": round(float(exact_orb), 6),
        "days_from_question": round(float(days_from), 4),
        "before_sign_change": before_sign_change,
    }

def _horary_moon_course(planets, dt_utc, timezone_name):
    moon = planets["Moon"]
    speed = max(0.01, float(moon["speed_deg_per_day"]))
    remaining = (30.0 - (moon["longitude"] % 30.0)) % 30.0
    if remaining < 1e-6:
        remaining = 30.0
    days_to_exit = min(3.5, remaining / speed)
    end_dt = dt_utc + timedelta(days=days_to_exit)
    times = _sample_datetimes(dt_utc, end_dt, 1.0)
    moon_lons = get_tropical_ecliptic_lons("Moon", times)
    hits = []

    for body in HORARY_PLANETS:
        if body == "Moon":
            continue
        other_lons = get_tropical_ecliptic_lons(body, times)
        seps = np.abs((moon_lons - other_lons + 180.0) % 360.0 - 180.0)
        for key, spec in HORARY_ASPECTS.items():
            orbs = np.abs(seps - spec["angle"])
            if len(orbs) < 2:
                continue
            idx = int(np.argmin(orbs))
            minimum = float(orbs[idx])
            if idx == 0 or minimum > 0.35:
                continue
            hits.append({
                "body": body,
                "body_ko": PLANET_KO[body],
                "aspect": key,
                "aspect_ko": spec["label_ko"],
                "time_local": _iso_local(times[idx], timezone_name),
                "hours_from_question": round(
                    (times[idx] - dt_utc).total_seconds() / 3600.0, 2
                ),
                "orb": round(minimum, 4),
            })

    hits.sort(key=lambda x: x["hours_from_question"])
    return {
        "void_of_course": not bool(hits),
        "sign_exit_local": _iso_local(end_dt, timezone_name),
        "hours_to_sign_exit": round(days_to_exit * 24.0, 2),
        "next_aspects": hits[:6],
    }

def _horary_potential_prohibitions(planets, querent_ruler, quesited_ruler, main):
    if not main or not main.get("perfects") or not main.get("days_from_question"):
        return []
    main_days = float(main["days_from_question"])
    out = []
    for third in HORARY_PLANETS:
        if third in {querent_ruler, quesited_ruler}:
            continue
        for target in {querent_ruler, quesited_ruler}:
            record = _horary_aspect_state(
                third, planets[third], target, planets[target]
            )
            rel_speed = record["relative_speed_deg_per_day"]
            if record["phase"] != "applying" or rel_speed < 0.01:
                continue
            estimate = record["orb"] / rel_speed
            if 0 < estimate < main_days:
                out.append({
                    "intervening": third,
                    "intervening_ko": PLANET_KO[third],
                    "target": target,
                    "target_ko": PLANET_KO[target],
                    "aspect": record["aspect"],
                    "aspect_ko": record["aspect_ko"],
                    "estimated_days": round(float(estimate), 3),
                    "classification": "potential_only",
                    "note_ko": "주 성사각보다 먼저 정확해질 수 있는 잠재 개입각입니다. 이것만으로 고전적 금지·프로히비션을 확정하지 않습니다.",
                })
    out.sort(key=lambda x: x["estimated_days"])
    return out[:6]

def _horary_warning_flags(houses, planets, moon_course):
    warnings = []
    asc_degree = houses["asc"] % 30.0
    if asc_degree < 3.0:
        warnings.append({
            "code": "early_asc",
            "level": "caution",
            "text_ko": "ASC(상승점)가 별자리 초도수입니다. 질문이 아직 충분히 무르익지 않았을 가능성을 점검하세요.",
        })
    if asc_degree > 27.0:
        warnings.append({
            "code": "late_asc",
            "level": "caution",
            "text_ko": "ASC(상승점)가 별자리 말도수입니다. 상황이 이미 상당 부분 결정됐을 가능성을 점검하세요.",
        })
    if planets["Saturn"]["house"] == 7:
        warnings.append({
            "code": "saturn_in_7",
            "level": "caution",
            "text_ko": "Saturn(토성)이 7하우스에 있습니다. 해석 오류·지연 가능성을 특별히 경계하는 전통적 고려사항입니다.",
        })
    moon_lon = planets["Moon"]["longitude"]
    if 195.0 <= moon_lon <= 225.0:
        warnings.append({
            "code": "moon_via_combusta",
            "level": "caution",
            "text_ko": "Moon(달)이 Via Combusta(비아 콤부스타·연소의 길)에 있습니다. 정서적 혼란과 불안정성을 경계합니다.",
        })
    if moon_course["void_of_course"]:
        warnings.append({
            "code": "void_moon",
            "level": "caution",
            "text_ko": "Moon(달)이 별자리를 떠나기 전 전통 7행성과 완성하는 주요 적용각이 없습니다.",
        })
    return warnings

def compute_horary(
    question_text: str,
    question_iso: str,
    topic: str = "general",
    timezone_name: str = "Asia/Seoul",
    place: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
):
    question = str(question_text or "").strip()
    if not question:
        raise ValueError("호라리 질문 원문을 입력해야 합니다.")

    latitude, longitude, resolved_place = resolve_coordinates(place, lat, lon)
    local_dt, dt_utc = _horary_local_to_utc(question_iso, timezone_name)
    houses = compute_regiomontanus_houses(dt_utc, latitude, longitude)
    spec = HORARY_TOPIC_SPECS.get(topic, HORARY_TOPIC_SPECS["general"])

    planets = {}
    for body in HORARY_PLANETS:
        lon_now, speed, direction = planet_motion(body, dt_utc)
        sd = sign_data(lon_now)
        dignity, dignity_ko = _horary_dignity(body, sd["sign_index"])
        planets[body] = {
            **sd,
            "name_ko": PLANET_KO[body],
            "house": cusp_house(lon_now, houses["cusps"]),
            "speed_deg_per_day": round(float(speed), 6),
            "direction": direction,
            "retrograde": direction == "역행",
            "dignity": dignity,
            "dignity_ko": dignity_ko,
        }

    querent_ruler = _horary_ruler_for_cusp(houses["cusps"][0])
    quesited_house = int(spec["quesited_house"])
    quesited_ruler = _horary_ruler_for_cusp(houses["cusps"][quesited_house - 1])
    event_house = spec.get("event_house")
    event_ruler = (
        _horary_ruler_for_cusp(houses["cusps"][int(event_house) - 1])
        if event_house else None
    )

    primary_aspect = (
        _horary_aspect_state(
            querent_ruler, planets[querent_ruler],
            quesited_ruler, planets[quesited_ruler],
        )
        if querent_ruler != quesited_ruler else None
    )
    perfection = _horary_perfection_candidate(
        querent_ruler, planets[querent_ruler],
        quesited_ruler, planets[quesited_ruler],
        dt_utc, timezone_name,
    )
    reception = (
        _horary_reception(
            querent_ruler, planets[querent_ruler],
            quesited_ruler, planets[quesited_ruler],
        )
        if querent_ruler != quesited_ruler else {
            "a": querent_ruler,
            "b": quesited_ruler,
            "same_significator": True,
            "has_reception": False,
            "mutual_reception": False,
        }
    )
    moon_course = _horary_moon_course(planets, dt_utc, timezone_name)
    prohibitions = _horary_potential_prohibitions(
        planets, querent_ruler, quesited_ruler, perfection
    )

    applying_aspects = []
    for i, body_a in enumerate(HORARY_PLANETS):
        for body_b in HORARY_PLANETS[i + 1:]:
            record = _horary_aspect_state(
                body_a, planets[body_a], body_b, planets[body_b]
            )
            if record["phase"] in {"applying", "exact"}:
                applying_aspects.append(record)
    applying_aspects.sort(key=lambda x: x["orb"])

    warnings = _horary_warning_flags(houses, planets, moon_course)
    if prohibitions:
        warnings.append({
            "code": "potential_intervention",
            "level": "review",
            "text_ko": "주 성사각보다 앞서는 잠재 개입각이 있습니다. 실제 금지·좌절 여부는 리셉션과 행성 상태를 함께 검토해야 합니다.",
        })

    _, _, _, _, target_keys, ephemeris_used, fallback_reason = load_ephemeris()
    return {
        "schema": "LUNEA_HORARY_V1",
        "question": {
            "text": question,
            "topic": topic if topic in HORARY_TOPIC_SPECS else "general",
            "topic_label_ko": spec["label_ko"],
            "topic_note_ko": spec["note"],
        },
        "moment": {
            "local_iso": local_dt.isoformat(),
            "utc_iso": dt_utc.isoformat(),
            "timezone": timezone_name,
            "place_input": place,
            "place_resolved": resolved_place,
            "latitude": latitude,
            "longitude": longitude,
        },
        "zodiac": "tropical",
        "house_system": "regiomontanus",
        "angles": {
            "ASC": {**sign_data(houses["asc"]), "name_ko": "상승점"},
            "MC": {**sign_data(houses["mc"]), "name_ko": "중천점"},
        },
        "cusps": [round(float(x), 6) for x in houses["cusps"]],
        "planets": planets,
        "significators": {
            "querent": {
                "house": 1,
                "ruler": querent_ruler,
                "ruler_ko": PLANET_KO[querent_ruler],
                "planet": planets[querent_ruler],
            },
            "quesited": {
                "house": quesited_house,
                "ruler": quesited_ruler,
                "ruler_ko": PLANET_KO[quesited_ruler],
                "planet": planets[quesited_ruler],
            },
            "event": ({
                "house": int(event_house),
                "ruler": event_ruler,
                "ruler_ko": PLANET_KO[event_ruler],
                "planet": planets[event_ruler],
            } if event_house else None),
            "moon": planets["Moon"],
        },
        "judgment_support": {
            "primary_connection": primary_aspect,
            "perfection": perfection,
            "reception": reception,
            "moon_course": moon_course,
            "potential_prohibition": prohibitions,
            "warnings": warnings,
            "applying_aspects": applying_aspects,
        },
        "meta": {
            "ephemeris": ephemeris_used,
            "ephemeris_fallback_reason": fallback_reason,
            "planet_target_keys": {
                k: v for k, v in target_keys.items() if k in HORARY_PLANETS
            },
            "calculation": "Skyfield apparent tropical longitude + Swiss Ephemeris Regiomontanus houses",
            "interpretation_boundary": "Calculation evidence only; no deterministic event guarantee.",
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

# ============================================================
# LUNEA RETURN ENGINE V1
# ============================================================

RETURN_CONFIG_V1 = {
    "Moon":    {"window_days": 40,    "step_hours": 1.0,  "label_ko":"달회귀"},
    "Sun":     {"window_days": 400,   "step_hours": 12.0, "label_ko":"태양회귀"},
    "Mercury": {"window_days": 500,   "step_hours": 6.0,  "label_ko":"수성회귀"},
    "Venus":   {"window_days": 600,   "step_hours": 12.0, "label_ko":"금성회귀"},
    "Mars":    {"window_days": 900,   "step_hours": 12.0, "label_ko":"화성회귀"},
    "Jupiter": {"window_days": 5000,  "step_hours": 48.0, "label_ko":"목성회귀"},
    "Saturn":  {"window_days": 12000, "step_hours": 96.0, "label_ko":"토성회귀"},
}

RETURN_ALLOWED_BODIES = tuple(RETURN_CONFIG_V1.keys())

def _return_delta(body, target_lon, dt_utc):
    lon = get_tropical_ecliptic_lon(body, sf_time(dt_utc))
    return circular_delta(lon, target_lon)

def _bisect_return_crossing(body, target_lon, left_dt, right_dt, iterations=52):
    fl = _return_delta(body, target_lon, left_dt)
    fr = _return_delta(body, target_lon, right_dt)
    if abs(fl) < 1e-8:
        return left_dt
    if abs(fr) < 1e-8:
        return right_dt
    if fl * fr > 0:
        return None

    a, b = left_dt, right_dt
    fa, fb = fl, fr
    for _ in range(iterations):
        mid = a + (b-a)/2
        fm = _return_delta(body, target_lon, mid)
        if abs(fm) < 1e-8 or (b-a).total_seconds() <= .5:
            return mid
        if fa * fm <= 0:
            b, fb = mid, fm
        else:
            a, fa = mid, fm
    return a + (b-a)/2

def _dedup_datetimes(values, tolerance_seconds=1800):
    out = []
    for dt in sorted(values):
        if not out or abs((dt-out[-1]).total_seconds()) > tolerance_seconds:
            out.append(dt)
    return out

def find_longitude_crossings_v1(body, target_lon, start_dt_utc, end_dt_utc, step_hours):
    samples = _sample_datetimes(start_dt_utc, end_dt_utc, step_hours)
    lons = get_tropical_ecliptic_lons(body, samples)
    vals = circular_delta_array(lons, target_lon)
    roots = []

    # Normal sign-changing longitude crossings.
    for i in range(len(samples)-1):
        a, b = float(vals[i]), float(vals[i+1])
        # Ignore circular wrap at +/-180; return target is near zero.
        if max(abs(a), abs(b)) > 90:
            continue
        if a == 0:
            roots.append(samples[i])
            continue
        if a*b <= 0:
            root = _bisect_return_crossing(
                body, target_lon, samples[i], samples[i+1]
            )
            if root is not None:
                roots.append(root)

    # A station can touch the natal degree and reverse without a clean sign change.
    absvals = np.abs(vals)
    for i in range(1, len(samples)-1):
        if absvals[i] <= absvals[i-1] and absvals[i] <= absvals[i+1] and absvals[i] <= .75:
            dt, orb = _refine_minimum_orb(
                body, target_lon, 0.0, samples[i-1], samples[i+1], iterations=18
            )
            if orb <= .06:
                roots.append(dt)

    return _dedup_datetimes(roots)

def _classify_return_passes(body, roots):
    rows = []
    for dt in roots:
        _, speed, direction = planet_motion(body, dt)
        rows.append({
            "dt":dt,
            "direction":direction,
            "speed":float(speed),
            "pass_type":"single_pass",
            "pass_label_ko":"단일 통과",
        })

    # If retrograde creates multiple passes in the same cycle, distinguish them.
    for i,row in enumerate(rows):
        if row["direction"] == "역행":
            row["pass_type"] = "retrograde_pass"
            row["pass_label_ko"] = "역행 통과"
            continue

        nearby_retro_before = any(
            r["direction"]=="역행" and 0 < (row["dt"]-r["dt"]).total_seconds() <= 140*86400
            for r in rows
        )
        nearby_retro_after = any(
            r["direction"]=="역행" and 0 < (r["dt"]-row["dt"]).total_seconds() <= 140*86400
            for r in rows
        )
        if nearby_retro_after:
            row["pass_type"] = "first_pass"
            row["pass_label_ko"] = "1차 순행 통과"
        elif nearby_retro_before:
            row["pass_type"] = "final_pass"
            row["pass_label_ko"] = "최종 순행 통과"
    return rows

def _return_chart_snapshot(body, exact_dt_utc, latitude, longitude):
    houses = compute_houses(exact_dt_utc, latitude, longitude)
    bodies = ["Sun","Moon","Mercury","Venus","Mars","Jupiter","Saturn"]
    planets = {}
    for name in bodies:
        lon = get_tropical_ecliptic_lon(name, sf_time(exact_dt_utc))
        planets[name] = {
            **sign_data(lon),
            "name_ko": PLANET_KO.get(name,name),
            "whole_house": whole_sign_house(lon,houses["asc"]),
            "placidus_house": cusp_house(lon,houses["placidus_cusps"]),
        }
    angles = {}
    for key,ko,value in [
        ("ASC","상승점",houses["asc"]),
        ("MC","중천점",houses["mc"]),
        ("Vertex","버텍스",houses["vertex"]),
    ]:
        angles[key] = {
            **sign_data(value),
            "name_ko":ko,
            "whole_house":whole_sign_house(value,houses["asc"]),
            "placidus_house":cusp_house(value,houses["placidus_cusps"]),
        }
    return {
        "focus_body":body,
        "planets":planets,
        "angles":angles,
    }

def _return_row_json(row, timezone_name):
    return {
        "time":_iso_local(row["dt"],timezone_name),
        "direction":row["direction"],
        "speed_deg_per_day":round(row["speed"],6),
        "pass_type":row["pass_type"],
        "pass_label_ko":row["pass_label_ko"],
    }

def calculate_return_context(
    natal,
    bodies,
    center_iso=None,
    timezone_name="Asia/Seoul",
    place=None,
    lat=None,
    lon=None,
):
    if not isinstance(natal,dict):
        raise ValueError("Natal payload가 필요합니다.")

    natal_planets = natal.get("planets") or {}
    center_dt = _as_aware_utc(center_iso)

    requested = []
    for body in bodies or []:
        if body in RETURN_ALLOWED_BODIES and body not in requested:
            requested.append(body)
    if not requested:
        requested = ["Sun","Moon"]

    birth = natal.get("birth") or {}
    if lat is None:
        lat = birth.get("latitude")
    if lon is None:
        lon = birth.get("longitude")
    if place is None:
        place = birth.get("place_resolved") or birth.get("place_input")

    latitude, longitude, resolved_place = resolve_coordinates(place,lat,lon)

    results = {}
    for body in requested:
        body_data = natal_planets.get(body)
        if not isinstance(body_data,dict) or body_data.get("longitude") is None:
            continue
        target_lon = float(body_data["longitude"])
        cfg = RETURN_CONFIG_V1[body]
        start = center_dt - timedelta(days=cfg["window_days"])
        end = center_dt + timedelta(days=cfg["window_days"])

        roots = find_longitude_crossings_v1(
            body,target_lon,start,end,cfg["step_hours"]
        )
        classified = _classify_return_passes(body,roots)
        prev = [r for r in classified if r["dt"] <= center_dt]
        fut = [r for r in classified if r["dt"] > center_dt]
        previous = max(prev,key=lambda x:x["dt"]) if prev else None
        next_row = min(fut,key=lambda x:x["dt"]) if fut else None

        anchor = next_row or previous
        snapshot = None
        if anchor:
            snapshot = _return_chart_snapshot(
                body,anchor["dt"],latitude,longitude
            )

        results[body] = {
            "body":body,
            "body_ko":PLANET_KO.get(body,body),
            "return_label_ko":cfg["label_ko"],
            "natal_longitude":round(target_lon,6),
            "previous":_return_row_json(previous,timezone_name) if previous else None,
            "next":_return_row_json(next_row,timezone_name) if next_row else None,
            "all_passes":[_return_row_json(r,timezone_name) for r in classified],
            "anchor_chart":snapshot,
        }

    return {
        "schema":"LUNEA_RETURN_CONTEXT_V1",
        "center":_iso_local(center_dt,timezone_name),
        "timezone":timezone_name,
        "location":{
            "place_input":place,
            "place_resolved":resolved_place,
            "latitude":latitude,
            "longitude":longitude,
            "note":"Return house/angle positions depend on the location used for the return moment."
        },
        "requested_bodies":requested,
        "returns":results,
        "rules":{
            "zodiac":"tropical",
            "house_primary":"whole_sign",
            "house_secondary":"placidus",
            "note":"A return describes a planetary cycle/context; it does not guarantee a specific event."
        }
    }


# ============================================================
# LUNEA THAI TAKSA V1
# ============================================================

THAI_TAKSA_SEQUENCE = [1,2,3,4,7,5,8,6]

THAI_PLANET_INFO = {
    1:{"key":"Sun","ko":"태양","thai":"อาทิตย์","weekday_ko":"일요일"},
    2:{"key":"Moon","ko":"달","thai":"จันทร์","weekday_ko":"월요일"},
    3:{"key":"Mars","ko":"화성","thai":"อังคาร","weekday_ko":"화요일"},
    4:{"key":"Mercury","ko":"수성","thai":"พุธ","weekday_ko":"수요일 낮"},
    5:{"key":"Jupiter","ko":"목성","thai":"พฤหัสบดี","weekday_ko":"목요일"},
    6:{"key":"Venus","ko":"금성","thai":"ศุกร์","weekday_ko":"금요일"},
    7:{"key":"Saturn","ko":"토성","thai":"เสาร์","weekday_ko":"토요일"},
    8:{"key":"Rahu","ko":"라후","thai":"ราหู","weekday_ko":"수요일 밤"},
}

TAKSA_POSITIONS = [
    ("Boriwan","บริวาร","보리완","주변 사람·관계망·기본 환경"),
    ("Ayu","อายุ","아유","생명력·건강·지속성"),
    ("Dech","เดช","데트","힘·권위·명예·사회적 영향"),
    ("Sri","ศรี","시리","매력·호감·명예·행운의 보조"),
    ("Mula","มูละ","물라","재산·자원·기반"),
    ("Utsaha","อุตสาหะ","웃사하","노력·일·실행력"),
    ("Montri","มนตรี","몬뜨리","도움·조언·후원자"),
    ("Kalakini","กาลกิณี","깔라끼니","마찰·취약점·피해야 할 요소"),
]

TAKSA_TOPIC_FOCUS = {
    "연락":["Montri","Utsaha"],
    "소식":["Montri","Dech"],
    "재회":["Sri","Montri","Boriwan"],
    "연애":["Sri","Boriwan"],
    "시험":["Dech","Utsaha","Montri"],
    "학업":["Utsaha","Montri"],
    "직장":["Dech","Utsaha","Montri"],
    "이직":["Dech","Utsaha","Mula"],
    "금전":["Mula","Sri"],
    "투자심리":["Mula","Utsaha","Kalakini"],
    "general":["Boriwan","Ayu","Montri"],
}

def _thai_local_dt(iso_value, timezone_name):
    tz = ZoneInfo(timezone_name or "Asia/Seoul")
    if iso_value:
        dt = datetime.fromisoformat(str(iso_value).replace("Z","+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        else:
            dt = dt.astimezone(tz)
        return dt
    return datetime.now(tz)

def _thai_effective_day(local_dt):
    # Traditional Taksa-style day boundary: 06:00 local time.
    if local_dt.hour < 6:
        effective_date = (local_dt - timedelta(days=1)).date()
    else:
        effective_date = local_dt.date()
    weekday = effective_date.weekday()  # Mon=0

    # Wednesday night / Rahu: Wednesday 18:00 through Thursday 05:59.
    if weekday == 2 and (local_dt.hour >= 18 or local_dt.hour < 6):
        return 8, effective_date, "Wednesday night / Rahu"
    mapping = {0:2,1:3,2:4,3:5,4:6,5:7,6:1}
    return mapping[weekday], effective_date, "weekday ruler"

def _taksa_grid_for_birth_planet(birth_planet_number):
    idx = THAI_TAKSA_SEQUENCE.index(int(birth_planet_number))
    rotated = THAI_TAKSA_SEQUENCE[idx:] + THAI_TAKSA_SEQUENCE[:idx]
    rows = []
    for (en,thai,ko,meaning),planet_number in zip(TAKSA_POSITIONS,rotated):
        info = THAI_PLANET_INFO[planet_number]
        rows.append({
            "position":en,
            "position_thai":thai,
            "position_ko":ko,
            "meaning_ko":meaning,
            "planet_number":planet_number,
            "planet":info["key"],
            "planet_ko":info["ko"],
            "planet_thai":info["thai"],
        })
    return rows

def calculate_thai_taksa(
    natal,
    topic="general",
    current_iso=None,
    timezone_name="Asia/Seoul",
):
    if not isinstance(natal,dict):
        raise ValueError("Natal payload가 필요합니다.")
    birth = natal.get("birth") or {}
    birth_iso = birth.get("local_iso")
    if not birth_iso:
        raise ValueError("Natal birth.local_iso가 필요합니다.")

    birth_local = _thai_local_dt(birth_iso,timezone_name)
    birth_number,effective_birth_date,birth_rule = _thai_effective_day(birth_local)
    grid = _taksa_grid_for_birth_planet(birth_number)

    current_local = _thai_local_dt(current_iso,timezone_name)
    current_number,effective_current_date,current_rule = _thai_effective_day(current_local)

    current_position = next(
        (r for r in grid if r["planet_number"]==current_number),None
    )
    topic_key = topic if topic in TAKSA_TOPIC_FOCUS else "general"
    focus_positions = TAKSA_TOPIC_FOCUS[topic_key]
    focus_rows = [r for r in grid if r["position"] in focus_positions]

    kalakini = next((r for r in grid if r["position"]=="Kalakini"),None)

    return {
        "schema":"LUNEA_THAI_TAKSA_V1",
        "system":"Maha Taksa / Taksa-Pakorn",
        "birth":{
            "local_iso":birth_local.isoformat(),
            "effective_date":effective_birth_date.isoformat(),
            "planet_number":birth_number,
            "weekday_label":THAI_PLANET_INFO[birth_number]["weekday_ko"],
            "ruler":THAI_PLANET_INFO[birth_number],
            "day_boundary":"06:00 local time",
            "rule_detail":birth_rule,
        },
        "grid":grid,
        "kalakini":kalakini,
        "question":{
            "topic":topic_key,
            "focus_positions":focus_positions,
            "focus_rows":focus_rows,
            "mapping_type":"LUNEA question-resonance layer; not a classical event-timing formula",
        },
        "current_day":{
            "local_iso":current_local.isoformat(),
            "effective_date":effective_current_date.isoformat(),
            "planet_number":current_number,
            "ruler":THAI_PLANET_INFO[current_number],
            "falls_in_natal_taksa":current_position,
            "interpretation_scope":"daily symbolic emphasis only; not a precise event forecast",
        },
        "rules":{
            "wednesday_night":"18:00 Wednesday through 05:59 Thursday = Rahu (8)",
            "day_boundary":"06:00 local time",
            "forecast_limit":"Taksa is kept as a separate structural/support layer. Precise dates remain Western Transit/Return territory."
        }
    }
