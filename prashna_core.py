from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from skyfield import almanac
from skyfield.api import wgs84

from astro_core import load_ephemeris, resolve_coordinates
from vedic_core import WEEKDAYS, compute_vedic_profile

UTC = timezone.utc

SIGN_LORDS = [
    "Mars", "Venus", "Mercury", "Moon", "Sun", "Mercury",
    "Venus", "Mars", "Jupiter", "Saturn", "Saturn", "Jupiter",
]

OWN_SIGNS = {
    "Sun": {4},
    "Moon": {3},
    "Mercury": {2, 5},
    "Venus": {1, 6},
    "Mars": {0, 7},
    "Jupiter": {8, 11},
    "Saturn": {9, 10},
}
EXALTATION = {
    "Sun": 0,
    "Moon": 1,
    "Mars": 9,
    "Mercury": 5,
    "Jupiter": 3,
    "Venus": 11,
    "Saturn": 6,
}
DEBILITATION = {planet: (sign + 6) % 12 for planet, sign in EXALTATION.items()}

# Classical graha-drishti sign offsets. Nodes are intentionally excluded in V1.
ASPECT_OFFSETS = {
    "Sun": {6},
    "Moon": {6},
    "Mercury": {6},
    "Venus": {6},
    "Mars": {3, 6, 7},
    "Jupiter": {4, 6, 8},
    "Saturn": {2, 6, 9},
}

NATURAL_BENEFICS = {"Jupiter", "Venus"}
NATURAL_MALEFICS = {"Mars", "Saturn"}

TOPIC_ROUTES = {
    "general": {
        "subject_house": 7,
        "event_house": None,
        "note_ko": "특정 상대가 있는 일반 질문: 상대를 7H로 본다.",
    },
    "relationship": {
        "subject_house": 7,
        "event_house": 7,
        "note_ko": "관계 질문: 상대·관계 축을 7H로 본다.",
    },
    "reconciliation": {
        "subject_house": 7,
        "event_house": 11,
        "note_ko": "재회 질문: 상대 7H + 성취·회복 보조로 11H를 본다. V1 라우팅 규칙이다.",
    },
    "contact": {
        "subject_house": 7,
        "event_house": 9,
        "note_ko": "연락 질문: 상대=7H, 상대의 3H(연락)=radical 9H로 파생한다.",
    },
    "career": {
        "subject_house": 10,
        "event_house": 10,
        "note_ko": "직장·커리어 질문: 10H를 중심으로 본다.",
    },
    "exam": {
        "subject_house": 5,
        "event_house": 9,
        "note_ko": "시험 질문: 학습·판단 5H와 고등학습·시험 보조 9H를 본다.",
    },
    "money": {
        "subject_house": 2,
        "event_house": 11,
        "note_ko": "금전 질문: 2H와 성취·수익 보조 11H를 본다.",
    },
    "stock": {
        "subject_house": 5,
        "event_house": 11,
        "note_ko": "투기적 투자 질문: 5H와 이익 보조 11H를 본다.",
    },
    "home": {
        "subject_house": 4,
        "event_house": 4,
        "note_ko": "집·부동산 질문: 4H를 중심으로 본다.",
    },
    "health": {
        "subject_house": 1,
        "event_house": 6,
        "note_ko": "건강 질문: 질문자 1H와 질병·회복 과정 보조 6H를 본다.",
    },
    "legal": {
        "subject_house": 7,
        "event_house": 6,
        "note_ko": "분쟁·법률 질문: 상대 7H와 분쟁 보조 6H를 본다.",
    },
}


def _parse_question_moment(question_iso: str, timezone_name: str) -> tuple[datetime, datetime]:
    if not question_iso:
        raise ValueError("질문 시각이 필요합니다.")
    tz = ZoneInfo(timezone_name or "Asia/Seoul")
    parsed = datetime.fromisoformat(question_iso)
    if parsed.tzinfo is None:
        local_dt = parsed.replace(tzinfo=tz)
    else:
        local_dt = parsed.astimezone(tz)
    return local_dt, local_dt.astimezone(UTC)


def _skyfield_time(ts, dt: datetime):
    return ts.from_datetime(dt.astimezone(UTC))


def _sunrise_for_local_date(
    local_day: date,
    tz: ZoneInfo,
    latitude: float,
    longitude: float,
) -> Optional[datetime]:
    """Return the local sunrise for a civil date using Skyfield's sunrise/sunset model."""
    start_local = datetime.combine(local_day, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    ts, eph, *_ = load_ephemeris()
    location = wgs84.latlon(
        latitude_degrees=float(latitude),
        longitude_degrees=float(longitude),
    )
    state = almanac.sunrise_sunset(eph, location)
    times, values = almanac.find_discrete(
        _skyfield_time(ts, start_local),
        _skyfield_time(ts, end_local),
        state,
    )
    for moment, value in zip(times, values):
        # sunrise is the transition into daylight (True)
        if bool(value):
            dt = moment.utc_datetime()
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(tz)
    return None


def _sunrise_vara(
    local_dt: datetime,
    latitude: float,
    longitude: float,
) -> dict:
    tz = local_dt.tzinfo
    if not isinstance(tz, ZoneInfo):
        tz = ZoneInfo(getattr(tz, "key", None) or "Asia/Seoul")
        local_dt = local_dt.astimezone(tz)

    today = local_dt.date()
    sunrise_today = _sunrise_for_local_date(today, tz, latitude, longitude)
    fallback = None
    if sunrise_today is None:
        vedic_day = today
        fallback = "sunrise_not_found_use_civil_date"
        before_sunrise = False
    else:
        before_sunrise = local_dt < sunrise_today
        vedic_day = today - timedelta(days=1) if before_sunrise else today

    weekday = WEEKDAYS[vedic_day.weekday()]
    return {
        "name": weekday[0],
        "label_ko": weekday[1],
        "boundary": "local_sunrise",
        "civil_date": today.isoformat(),
        "vedic_day_date": vedic_day.isoformat(),
        "today_sunrise_local": sunrise_today.isoformat() if sunrise_today else None,
        "query_before_today_sunrise": before_sunrise,
        "fallback": fallback,
    }


def _house_ruler(d1: dict, house: int) -> tuple[str, int]:
    row = d1["whole_sign_houses"][house - 1]
    sign_index = int(row["rashi_index"])
    return SIGN_LORDS[sign_index], sign_index


def _dignity(planet: str, sign_index: int) -> dict:
    if planet not in EXALTATION:
        return {"state": "not_scored", "score": 0}
    if sign_index == EXALTATION[planet]:
        return {"state": "exalted", "score": 1}
    if sign_index == DEBILITATION[planet]:
        return {"state": "debilitated", "score": -1}
    if sign_index in OWN_SIGNS.get(planet, set()):
        return {"state": "own_sign", "score": 1}
    return {"state": "neutral", "score": 0}


def _aspects_sign(planet: str, from_sign: int, target_sign: int) -> bool:
    offsets = ASPECT_OFFSETS.get(planet, set())
    return ((target_sign - from_sign) % 12) in offsets


def _factor(code: str, label_ko: str, score: int, detail_ko: str) -> dict:
    return {
        "code": code,
        "label_ko": label_ko,
        "score": int(score),
        "detail_ko": detail_ko,
    }


def _judgment_support(d1: dict, topic: str) -> dict:
    route = TOPIC_ROUTES.get(topic) or TOPIC_ROUTES["general"]
    subject_house = int(route["subject_house"])
    event_house = route["event_house"]
    event_house = int(event_house) if event_house is not None else None

    planets = d1["planets"]
    subject_lord, subject_sign = _house_ruler(d1, subject_house)
    subject_planet = planets[subject_lord]
    subject_planet_sign = int(subject_planet["sign_index"])

    event_lord = None
    event_sign = None
    event_planet = None
    if event_house is not None:
        event_lord, event_sign = _house_ruler(d1, event_house)
        event_planet = planets[event_lord]

    factors = []

    subject_dignity = _dignity(subject_lord, subject_planet_sign)
    if subject_dignity["score"]:
        factors.append(_factor(
            "subject_lord_dignity",
            "대상 주인행성 존귀",
            subject_dignity["score"],
            f"{subject_lord}가 {subject_dignity['state']} 상태",
        ))

    if subject_planet.get("whole_sign_house") in {6, 8, 12}:
        factors.append(_factor(
            "subject_lord_dusthana",
            "대상 주인행성 두스타나",
            -1,
            f"{subject_lord}가 {subject_planet.get('whole_sign_house')}H에 위치",
        ))

    if event_house is not None and event_planet is not None:
        event_planet_sign = int(event_planet["sign_index"])
        event_dignity = _dignity(event_lord, event_planet_sign)
        if event_dignity["score"]:
            factors.append(_factor(
                "event_lord_dignity",
                "사건 주인행성 존귀",
                event_dignity["score"],
                f"{event_lord}가 {event_dignity['state']} 상태",
            ))

        if int(subject_planet.get("whole_sign_house") or 0) == event_house:
            factors.append(_factor(
                "subject_lord_in_event_house",
                "대상 주인행성이 사건 하우스에 위치",
                2,
                f"{subject_lord}가 {event_house}H에 위치",
            ))

        if int(event_planet.get("whole_sign_house") or 0) == subject_house:
            factors.append(_factor(
                "event_lord_in_subject_house",
                "사건 주인행성이 대상 하우스에 위치",
                2,
                f"{event_lord}가 {subject_house}H에 위치",
            ))

        if subject_lord == event_lord:
            factors.append(_factor(
                "shared_lord",
                "대상·사건 하우스가 같은 주인행성을 공유",
                1,
                f"두 하우스의 주인행성이 모두 {subject_lord}",
            ))
        else:
            subject_to_event = _aspects_sign(subject_lord, subject_planet_sign, event_planet_sign)
            event_to_subject = _aspects_sign(event_lord, event_planet_sign, subject_planet_sign)
            if subject_to_event and event_to_subject:
                factors.append(_factor(
                    "mutual_graha_drishti",
                    "대상·사건 주인행성 상호 Graha Drishti",
                    2,
                    f"{subject_lord}와 {event_lord}가 서로의 별자리에 고전 Graha Drishti를 보냄",
                ))
            elif subject_to_event or event_to_subject:
                factors.append(_factor(
                    "one_way_graha_drishti",
                    "대상·사건 주인행성 Graha Drishti 연결",
                    1,
                    f"{subject_lord}와 {event_lord} 사이에 한 방향 Graha Drishti가 있음",
                ))

        if event_planet.get("whole_sign_house") in {6, 8, 12}:
            factors.append(_factor(
                "event_lord_dusthana",
                "사건 주인행성 두스타나",
                -1,
                f"{event_lord}가 {event_planet.get('whole_sign_house')}H에 위치",
            ))

        moon = planets["Moon"]
        moon_sign = int(moon["sign_index"])
        if int(moon.get("whole_sign_house") or 0) == event_house:
            factors.append(_factor(
                "moon_in_event_house",
                "Moon이 사건 하우스에 위치",
                1,
                f"Moon이 {event_house}H에 위치",
            ))
        elif _aspects_sign("Moon", moon_sign, event_sign):
            factors.append(_factor(
                "moon_aspects_event_house",
                "Moon이 사건 하우스에 Graha Drishti",
                1,
                f"Moon이 {event_house}H 별자리를 7번째 시선으로 봄",
            ))

        for planet in ("Jupiter", "Venus"):
            p = planets[planet]
            if _aspects_sign(planet, int(p["sign_index"]), event_sign):
                factors.append(_factor(
                    f"{planet.lower()}_benefic_event_aspect",
                    f"{planet}의 사건 하우스 보조",
                    1,
                    f"{planet}가 {event_house}H 별자리에 Graha Drishti",
                ))
        for planet in ("Mars", "Saturn"):
            p = planets[planet]
            if _aspects_sign(planet, int(p["sign_index"]), event_sign):
                factors.append(_factor(
                    f"{planet.lower()}_malefic_event_aspect",
                    f"{planet}의 사건 하우스 압박",
                    -1,
                    f"{planet}가 {event_house}H 별자리에 Graha Drishti",
                ))

    lagna_degree = float(d1["lagna"]["degree"])
    confidence_flags = []
    if lagna_degree < 1.0 or lagna_degree > 29.0:
        confidence_flags.append({
            "code": "lagna_sandhi",
            "detail_ko": "Lagna가 별자리 경계 1° 이내라 하우스 주인 판정 민감도가 높다.",
        })

    score = sum(int(row["score"]) for row in factors)
    if score >= 4:
        band = "strong"
        band_ko = "강"
    elif score >= 1:
        band = "mixed"
        band_ko = "중"
    else:
        band = "weak"
        band_ko = "약"

    return {
        "rule_set": "LUNEA_PRASHNA_RULESET_V1",
        "method_note_ko": (
            "V1은 Whole Sign D1, 하우스 주인, 고전 Graha Drishti, 기본 존귀와 Moon 연결을 "
            "보수적으로 점수화한 LUNEA 규칙셋이다. 모든 프라슈나 유파의 보편 규칙을 뜻하지 않는다."
        ),
        "topic": topic,
        "route": {
            "subject_house": subject_house,
            "event_house": event_house,
            "note_ko": route["note_ko"],
            "subject_lord": subject_lord,
            "event_lord": event_lord,
        },
        "support_score": score,
        "support_band": band,
        "support_band_ko": band_ko,
        "factors": factors,
        "confidence_flags": confidence_flags,
        "binary_outcome_generated": False,
    }


def compute_prashna(
    question_text: str,
    question_iso: str,
    topic: str = "general",
    timezone_name: str = "Asia/Seoul",
    place: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
) -> dict:
    if not (question_text or "").strip():
        raise ValueError("질문 원문이 필요합니다.")

    local_dt, dt_utc = _parse_question_moment(question_iso, timezone_name)
    latitude, longitude, resolved_place = resolve_coordinates(place, lat, lon)

    vedic = compute_vedic_profile(
        birth_date=local_dt.date().isoformat(),
        birth_time=local_dt.strftime("%H:%M:%S"),
        timezone_name=timezone_name,
        place=resolved_place,
        lat=latitude,
        lon=longitude,
    )

    panchanga = dict(vedic["panchanga"])
    panchanga["vara"] = _sunrise_vara(local_dt, latitude, longitude)

    d1 = vedic["d1_rashi"]
    judgment = _judgment_support(d1, topic)
    if panchanga["vara"].get("fallback"):
        judgment["confidence_flags"].append({
            "code": "vara_sunrise_fallback",
            "detail_ko": "해당 날짜의 일출을 찾지 못해 Vara만 civil date로 대체했다.",
        })

    return {
        "schema": "LUNEA_PRASHNA_V1",
        "question": {
            "text": question_text.strip(),
            "topic": topic,
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
        "zodiac": vedic["zodiac"],
        "ayanamsha": vedic["ayanamsha"],
        "d1_rashi": d1,
        "panchanga": panchanga,
        "judgment_support": judgment,
        "provenance": {
            "engine": "Swiss Ephemeris + Skyfield sunrise boundary",
            "sidereal": True,
            "ayanamsha": "Lahiri",
            "house_policy": "whole_sign_from_sidereal_lagna",
            "node_policy": "true_node_positions_nodes_not_used_for_v1_drishti",
            "panchanga_vara_boundary": "local_sunrise",
            "panchanga_exact_moment": True,
            "rule_set": "LUNEA_PRASHNA_RULESET_V1",
            "independent_from_tropical_horary": True,
            "western_tropical_positions_reused": False,
            "binary_outcome_generated": False,
            "interpretation_generated": False,
        },
    }
