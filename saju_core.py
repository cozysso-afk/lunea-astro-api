from __future__ import annotations

from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Optional
from zoneinfo import ZoneInfo

from lunar_python import Solar

STEM_KO = {
    "甲": "갑", "乙": "을", "丙": "병", "丁": "정", "戊": "무",
    "己": "기", "庚": "경", "辛": "신", "壬": "임", "癸": "계",
}
BRANCH_KO = {
    "子": "자", "丑": "축", "寅": "인", "卯": "묘", "辰": "진", "巳": "사",
    "午": "오", "未": "미", "申": "신", "酉": "유", "戌": "술", "亥": "해",
}
STEM_ELEMENT = {
    "甲": "목", "乙": "목", "丙": "화", "丁": "화", "戊": "토",
    "己": "토", "庚": "금", "辛": "금", "壬": "수", "癸": "수",
}
BRANCH_ELEMENT = {
    "子": "수", "丑": "토", "寅": "목", "卯": "목", "辰": "토", "巳": "화",
    "午": "화", "未": "토", "申": "금", "酉": "금", "戌": "토", "亥": "수",
}
STEM_POLARITY = {
    "甲": "yang", "乙": "yin", "丙": "yang", "丁": "yin", "戊": "yang",
    "己": "yin", "庚": "yang", "辛": "yin", "壬": "yang", "癸": "yin",
}
GENERATES = {"목": "화", "화": "토", "토": "금", "금": "수", "수": "목"}
CONTROLS = {"목": "토", "화": "금", "토": "수", "금": "목", "수": "화"}


def _library_version() -> str:
    try:
        return version("lunar-python")
    except PackageNotFoundError:
        return "unknown"


def _parse_local_datetime(birth_date: str, birth_time: str, timezone_name: str) -> datetime:
    try:
        date_part = datetime.strptime(str(birth_date).strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("birth_date는 YYYY-MM-DD 형식이어야 합니다.") from exc

    raw_time = str(birth_time).strip()
    parsed_time = None
    for pattern in ("%H:%M", "%H:%M:%S"):
        try:
            parsed_time = datetime.strptime(raw_time, pattern).time()
            break
        except ValueError:
            continue
    if parsed_time is None:
        raise ValueError("birth_time은 HH:MM 또는 HH:MM:SS 형식이어야 합니다.")

    try:
        tz = ZoneInfo(timezone_name or "Asia/Seoul")
    except Exception as exc:
        raise ValueError(f"지원되지 않는 timezone: {timezone_name}") from exc

    return datetime.combine(date_part, parsed_time, tzinfo=tz)


def _format_ganzhi(value: str) -> dict:
    if not value or len(value) < 2:
        raise ValueError(f"잘못된 간지 값: {value!r}")
    stem, branch = value[0], value[1]
    if stem not in STEM_KO or branch not in BRANCH_KO:
        raise ValueError(f"지원되지 않는 간지 값: {value!r}")
    return {
        "hanja": value,
        "hangul": f"{STEM_KO[stem]}{BRANCH_KO[branch]}",
        "display": f"{value}({STEM_KO[stem]}{BRANCH_KO[branch]})",
        "stem": stem,
        "stem_hangul": STEM_KO[stem],
        "branch": branch,
        "branch_hangul": BRANCH_KO[branch],
        "stem_element": STEM_ELEMENT[stem],
        "branch_element": BRANCH_ELEMENT[branch],
    }


def _ten_god(day_stem: str, target_stem: str) -> str:
    day_element = STEM_ELEMENT[day_stem]
    target_element = STEM_ELEMENT[target_stem]
    same_polarity = STEM_POLARITY[day_stem] == STEM_POLARITY[target_stem]

    if day_element == target_element:
        return "비견" if same_polarity else "겁재"
    if GENERATES[day_element] == target_element:
        return "식신" if same_polarity else "상관"
    if CONTROLS[day_element] == target_element:
        return "편재" if same_polarity else "정재"
    if CONTROLS[target_element] == day_element:
        return "편관" if same_polarity else "정관"
    if GENERATES[target_element] == day_element:
        return "편인" if same_polarity else "정인"
    return ""


def _visible_element_counts(pillars: dict) -> dict:
    counts = {"목": 0, "화": 0, "토": 0, "금": 0, "수": 0}
    for pillar in pillars.values():
        counts[pillar["stem_element"]] += 1
        counts[pillar["branch_element"]] += 1
    return counts


def compute_four_pillars(
    birth_date: str,
    birth_time: str,
    timezone_name: str = "Asia/Seoul",
    place: Optional[str] = None,
) -> dict:
    """Compute deterministic Four Pillars from local civil birth time.

    V1 intentionally does not apply true-solar-time longitude correction or make
    strength/yongshin judgments. Those are school-dependent and remain manual.
    """
    local_dt = _parse_local_datetime(birth_date, birth_time, timezone_name)
    solar = Solar.fromYmdHms(
        local_dt.year,
        local_dt.month,
        local_dt.day,
        local_dt.hour,
        local_dt.minute,
        local_dt.second,
    )
    lunar = solar.getLunar()
    eight = lunar.getEightChar()

    raw = {
        "year": eight.getYear(),
        "month": eight.getMonth(),
        "day": eight.getDay(),
        "hour": eight.getTime(),
    }
    pillars = {name: _format_ganzhi(value) for name, value in raw.items()}
    day_stem = pillars["day"]["stem"]

    for name, pillar in pillars.items():
        pillar["ten_god_stem"] = "일간" if name == "day" else _ten_god(day_stem, pillar["stem"])

    offset = local_dt.utcoffset()
    offset_minutes = int(offset.total_seconds() // 60) if offset is not None else None

    return {
        "engine": "LUNEA_SAJU_FOUR_PILLARS_V1",
        "pillars": pillars,
        "day_master": {
            "stem": day_stem,
            "hangul": STEM_KO[day_stem],
            "element": STEM_ELEMENT[day_stem],
            "polarity": STEM_POLARITY[day_stem],
        },
        "visible_elements": _visible_element_counts(pillars),
        "provenance": {
            "library": "lunar-python",
            "library_version": _library_version(),
            "calendar_input": "gregorian_local_civil_time",
            "timezone": timezone_name,
            "utc_offset_minutes": offset_minutes,
            "local_iso": local_dt.isoformat(),
            "place_label": str(place or "").strip() or None,
            "solar_term_month_boundary": True,
            "true_solar_time_correction": False,
            "school_dependent_strength_judgment": False,
            "manual_override_supported": True,
            "eight_char_sect": eight.getSect(),
        },
    }
