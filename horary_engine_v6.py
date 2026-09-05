from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np

import astro_core as core
import horary_balance_v3 as v3
import horary_balance_v31 as v31


# LUNEA HORARY ENGINE V6
# ----------------------
# Strict traditional-core gate over V5/V3.1:
# - geometric nearest aspect != operative traditional aspect
# - out-of-orb aspects never enter the direct perfection pipeline
# - applying/separating is determined from actual ephemeris motion when a
#   question-moment context is available
# - exact aspect / sign ingress / station are compared as timed events
# - Moon VOC is traditional-seven-planets + Ptolemaic aspects only
# - derived event axes, reception and dignity are explicitly separated
# - modern bodies are supplemental and never enter traditional perfection/VOC
#
# This module is deliberately additive. V5 still owns the planetary-moiety
# orb table and solar-altitude sect decision.

VERSION = "LUNEA_HORARY_ENGINE_V6_STRICT_TRADITIONAL_CORE"
_CONTEXT_DT_UTC: ContextVar[datetime | None] = ContextVar(
    "lunea_horary_v6_dt_utc", default=None
)
_ORIGINAL_COMPUTE_HORARY = v31.compute_horary

ASPECT_EXACT_TOL = 0.15
ASPECT_MOTION_EPS = 0.0025
STATION_SPEED_EPS = 0.003

TRADITIONAL_STATE_KO = {
    "valid_applying": "유효 오브 안 · 적용",
    "valid_separating": "유효 오브 안 · 분리",
    "valid_exact": "유효 오브 안 · 정확",
    "valid_unclear": "유효 오브 안 · 정지/전환 확인 필요",
    "out_of_orb_applying": "유효 오브 밖 · 기하학적으로 접근 중",
    "out_of_orb_separating": "유효 오브 밖 · 기하학적으로 멀어지는 중",
    "out_of_orb_unclear": "유효 오브 밖 · 운동 방향 불명확",
    "no_major_aspect": "전통 주요각 없음",
}


def _parse_utc(value) -> datetime:
    if isinstance(value, datetime):
        return value
    raw = str(value or "").strip().replace("Z", "+00:00")
    if not raw:
        raise ValueError("missing utc moment")
    return datetime.fromisoformat(raw)


def _iso_local(dt_utc: datetime, timezone_name: str) -> str:
    try:
        return dt_utc.astimezone(ZoneInfo(timezone_name or "Asia/Seoul")).isoformat()
    except Exception:
        return core._iso_local(dt_utc, timezone_name)


def _planet_lon(body: str, dt_utc: datetime) -> float:
    return float(core.get_tropical_ecliptic_lon(body, core.sf_time(dt_utc)))


def _aspect_error_at(body_a: str, body_b: str, angle: float, dt_utc: datetime) -> float:
    a = _planet_lon(body_a, dt_utc)
    b = _planet_lon(body_b, dt_utc)
    return abs(core.angular_separation(a, b) - float(angle))


def _nearest_geometric_aspect(row_a, row_b):
    sep = core.angular_separation(float(row_a["longitude"]), float(row_b["longitude"]))
    candidates = []
    for key, spec in core.HORARY_ASPECTS.items():
        candidates.append((abs(float(sep) - float(spec["angle"])), key, spec))
    orb, key, spec = min(candidates)
    return float(sep), float(orb), key, spec


def _motion_probe_hours(body_a: str, body_b: str) -> float:
    if "Moon" in {body_a, body_b}:
        return 0.5
    if {body_a, body_b} & {"Mercury", "Venus", "Mars", "Sun"}:
        return 2.0
    return 6.0


def _actual_or_fallback_motion(
    body_a: str,
    row_a,
    body_b: str,
    row_b,
    angle: float,
    current_orb: float,
):
    hours = _motion_probe_hours(body_a, body_b)
    dt_utc = _CONTEXT_DT_UTC.get()

    if dt_utc is not None:
        try:
            delta = timedelta(hours=hours)
            past = _aspect_error_at(body_a, body_b, angle, dt_utc - delta)
            future = _aspect_error_at(body_a, body_b, angle, dt_utc + delta)
            method = "ephemeris_short_step"
            return float(past), float(future), hours, method
        except Exception:
            pass

    fraction = hours / 24.0
    a_lon = float(row_a["longitude"])
    b_lon = float(row_b["longitude"])
    a_speed = float(row_a.get("speed_deg_per_day") or 0.0)
    b_speed = float(row_b.get("speed_deg_per_day") or 0.0)
    past_sep = core.angular_separation(a_lon - a_speed * fraction, b_lon - b_speed * fraction)
    future_sep = core.angular_separation(a_lon + a_speed * fraction, b_lon + b_speed * fraction)
    return (
        abs(float(past_sep) - float(angle)),
        abs(float(future_sep) - float(angle)),
        hours,
        "signed_speed_short_step_fallback",
    )


def _strict_aspect_state(body_a, row_a, body_b, row_b):
    sep_now, orb, key, spec = _nearest_geometric_aspect(row_a, row_b)
    limit = float(core._horary_aspect_limit(body_a, body_b, key))
    within = bool(orb <= limit + 1e-9)
    past_error, future_error, probe_hours, method = _actual_or_fallback_motion(
        body_a, row_a, body_b, row_b, float(spec["angle"]), orb
    )

    if orb <= 0.05:
        motion = "exact"
    elif future_error + ASPECT_MOTION_EPS < orb:
        motion = "applying"
    elif past_error + ASPECT_MOTION_EPS < orb:
        motion = "separating"
    else:
        motion = "unclear"

    if within:
        traditional_state = {
            "applying": "valid_applying",
            "separating": "valid_separating",
            "exact": "valid_exact",
            "unclear": "valid_unclear",
        }[motion]
        phase = motion
        phase_ko = {
            "applying": "적용",
            "separating": "분리",
            "exact": "정확",
            "unclear": "정지·전환 확인 필요",
        }[motion]
        operative = key
    else:
        traditional_state = {
            "applying": "out_of_orb_applying",
            "separating": "out_of_orb_separating",
            "exact": "out_of_orb_unclear",
            "unclear": "out_of_orb_unclear",
        }[motion]
        phase = "out_of_orb"
        phase_ko = "유효 오브 밖"
        operative = None

    return {
        "a": body_a,
        "a_ko": core.PLANET_KO.get(body_a, body_a),
        "b": body_b,
        "b_ko": core.PLANET_KO.get(body_b, body_b),
        "aspect": key,
        "aspect_ko": spec.get("label_ko", key),
        "angle": float(spec["angle"]),
        "orb": round(orb, 4),
        "max_orb": round(limit, 4),
        "phase": phase,
        "phase_ko": phase_ko,
        "within_orb": within,
        "closest_geometric_aspect": {
            "aspect": key,
            "aspect_ko": spec.get("label_ko", key),
            "angle": float(spec["angle"]),
            "orb": round(orb, 4),
        },
        "traditional_valid_aspect": operative,
        "traditional_valid_aspect_ko": spec.get("label_ko", key) if operative else None,
        "traditional_state": traditional_state,
        "traditional_state_ko": TRADITIONAL_STATE_KO[traditional_state],
        "motion_phase": motion,
        "motion_method": method,
        "motion_probe_hours": probe_hours,
        "error_past_deg": round(float(past_error), 6),
        "error_now_deg": round(float(orb), 6),
        "error_future_deg": round(float(future_error), 6),
        "separation_deg": round(float(sep_now), 6),
        "relative_speed_deg_per_day": round(
            abs(
                float(row_a.get("speed_deg_per_day") or 0.0)
                - float(row_b.get("speed_deg_per_day") or 0.0)
            ),
            6,
        ),
    }


def _sign_index_at(body: str, dt_utc: datetime) -> int:
    return int(_planet_lon(body, dt_utc) // 30.0)


def _refine_sign_ingress(body: str, left: datetime, right: datetime, start_sign: int) -> datetime:
    for _ in range(28):
        mid = left + (right - left) / 2
        if _sign_index_at(body, mid) == start_sign:
            left = mid
        else:
            right = mid
    return right


def _next_sign_ingress(body: str, row, dt_utc: datetime, horizon_days: float = 180.0):
    start_sign = int(float(row["longitude"]) // 30.0)
    speed = abs(float(row.get("speed_deg_per_day") or 0.0))
    step_hours = 0.5 if body == "Moon" else 2.0 if speed >= 0.5 else 6.0 if speed >= 0.08 else 12.0
    end = dt_utc + timedelta(days=float(horizon_days))
    left = dt_utc
    while left < end:
        right = min(end, left + timedelta(hours=step_hours))
        try:
            if _sign_index_at(body, right) != start_sign:
                exact = _refine_sign_ingress(body, left, right, start_sign)
                return {
                    "type": "sign_ingress",
                    "body": body,
                    "body_ko": core.PLANET_KO.get(body, body),
                    "utc": exact.isoformat(),
                    "days_from_question": round((exact - dt_utc).total_seconds() / 86400.0, 6),
                    "from_sign_index": start_sign,
                    "to_sign_index": _sign_index_at(body, exact + timedelta(seconds=2)),
                }
        except Exception:
            pass
        left = right
    return None


def _previous_sign_ingress(body: str, row, dt_utc: datetime, horizon_days: float = 5.0):
    start_sign = int(float(row["longitude"]) // 30.0)
    speed = abs(float(row.get("speed_deg_per_day") or 0.0))
    step_hours = 0.5 if body == "Moon" else 3.0 if speed >= 0.5 else 8.0
    earliest = dt_utc - timedelta(days=float(horizon_days))
    right = dt_utc
    while right > earliest:
        left = max(earliest, right - timedelta(hours=step_hours))
        try:
            if _sign_index_at(body, left) != start_sign:
                lo, hi = left, right
                for _ in range(28):
                    mid = lo + (hi - lo) / 2
                    if _sign_index_at(body, mid) == start_sign:
                        hi = mid
                    else:
                        lo = mid
                return hi
        except Exception:
            pass
        right = left
    return earliest


def _speed_at(body: str, dt_utc: datetime) -> float:
    _, speed, _ = core.planet_motion(body, dt_utc)
    return float(speed)


def _motion_sign(speed: float) -> int:
    if speed > STATION_SPEED_EPS:
        return 1
    if speed < -STATION_SPEED_EPS:
        return -1
    return 0


def _refine_station(body: str, left: datetime, right: datetime) -> datetime:
    lo, hi = left, right
    for _ in range(24):
        span = hi - lo
        m1 = lo + span / 3
        m2 = hi - span / 3
        if abs(_speed_at(body, m1)) <= abs(_speed_at(body, m2)):
            hi = m2
        else:
            lo = m1
    return lo + (hi - lo) / 2


def _next_station(body: str, row, dt_utc: datetime, horizon_days: float = 180.0):
    start_speed = float(row.get("speed_deg_per_day") or 0.0)
    step_hours = 3.0 if body in {"Moon", "Mercury", "Venus", "Mars"} else 8.0
    end = dt_utc + timedelta(days=float(horizon_days))
    left = dt_utc
    try:
        prev_speed = _speed_at(body, left)
    except Exception:
        prev_speed = start_speed

    while left < end:
        right = min(end, left + timedelta(hours=step_hours))
        try:
            speed = _speed_at(body, right)
        except Exception:
            left = right
            continue
        if (
            _motion_sign(prev_speed) == 0
            or _motion_sign(speed) == 0
            or (_motion_sign(prev_speed) != _motion_sign(speed))
        ):
            exact = _refine_station(body, left, right)
            return {
                "type": "station",
                "body": body,
                "body_ko": core.PLANET_KO.get(body, body),
                "utc": exact.isoformat(),
                "days_from_question": round((exact - dt_utc).total_seconds() / 86400.0, 6),
                "speed_before": round(_speed_at(body, exact - timedelta(hours=1)), 6),
                "speed_after": round(_speed_at(body, exact + timedelta(hours=1)), 6),
            }
        prev_speed = speed
        left = right
    return None


def _refine_exact_aspect(body_a: str, body_b: str, angle: float, left: datetime, right: datetime):
    exact, orb = core._horary_refine_pair(body_a, body_b, float(angle), left, right, iterations=18)
    return exact, float(orb)


def _find_exact_aspect(body_a: str, body_b: str, angle: float, dt_utc: datetime, end_dt: datetime):
    if end_dt <= dt_utc:
        return None
    span_days = max(0.01, (end_dt - dt_utc).total_seconds() / 86400.0)
    step_hours = 0.5 if "Moon" in {body_a, body_b} else 1.5 if span_days < 7 else 3.0
    times = list(core._sample_datetimes(dt_utc, end_dt, step_hours))
    if len(times) < 2:
        return None
    a_lons = np.asarray(core.get_tropical_ecliptic_lons(body_a, times), dtype=float)
    b_lons = np.asarray(core.get_tropical_ecliptic_lons(body_b, times), dtype=float)
    seps = np.abs((a_lons - b_lons + 180.0) % 360.0 - 180.0)
    errors = np.abs(seps - float(angle))
    idx = int(np.argmin(errors))
    if idx == 0 or float(errors[idx]) > 1.25:
        return None
    left = times[max(0, idx - 1)]
    right = times[min(len(times) - 1, idx + 1)]
    if right <= left:
        return None
    exact, orb = _refine_exact_aspect(body_a, body_b, angle, left, right)
    if exact < dt_utc or exact > end_dt or orb > ASPECT_EXACT_TOL:
        return None
    return {
        "type": "exact_aspect",
        "utc": exact.isoformat(),
        "days_from_question": round((exact - dt_utc).total_seconds() / 86400.0, 6),
        "exact_orb": round(orb, 6),
    }


def _station_breaks_application(body_a, body_b, angle, station_dt: datetime) -> bool:
    try:
        before = _aspect_error_at(body_a, body_b, angle, station_dt - timedelta(hours=2))
        after = _aspect_error_at(body_a, body_b, angle, station_dt + timedelta(hours=2))
        return bool(after > before + 0.01)
    except Exception:
        return True


def _strict_perfection_candidate(body_a, row_a, body_b, row_b, dt_utc, timezone_name):
    if body_a == body_b:
        return {
            "perfects": False,
            "indeterminate": True,
            "shared_ruler": True,
            "reason": "same_significator",
            "reason_ko": "질문자와 대상이 같은 주인행성을 공유해 두 행성의 직접 성사각으로 판정하지 않습니다.",
            "perfection_check_started": False,
        }

    state = _strict_aspect_state(body_a, row_a, body_b, row_b)
    if not state.get("within_orb"):
        return {
            "perfects": False,
            "indeterminate": False,
            "reason": "out_of_orb_no_active_perfection",
            "reason_ko": "가장 가까운 기하학적 주요각은 있으나 전통 유효 오브 밖이므로 직접 성사각으로 채택하지 않습니다.",
            "aspect": state,
            "perfection_check_started": False,
            "refranation_applicable": False,
            "before_sign_change": None,
        }

    if state.get("phase") == "exact":
        return {
            "perfects": True,
            "indeterminate": False,
            "reason": "exact_now",
            "reason_ko": "질문 시각에 유효 주요각이 이미 정확합니다.",
            "aspect": state,
            "exact_utc": dt_utc.isoformat(),
            "exact_local": _iso_local(dt_utc, timezone_name),
            "days_from_question": 0.0,
            "before_sign_change": True,
            "perfection_check_started": True,
            "refranation_applicable": False,
            "started_within_orb": True,
        }

    if state.get("phase") != "applying":
        return {
            "perfects": False,
            "indeterminate": False,
            "reason": "no_valid_applying_aspect",
            "reason_ko": "유효 오브 안의 주요각은 있으나 현재 적용각이 아니므로 직접 성사각으로 진행하지 않습니다.",
            "aspect": state,
            "perfection_check_started": False,
            "refranation_applicable": False,
        }

    ingress_a = _next_sign_ingress(body_a, row_a, dt_utc)
    ingress_b = _next_sign_ingress(body_b, row_b, dt_utc)
    station_a = _next_station(body_a, row_a, dt_utc)
    station_b = _next_station(body_b, row_b, dt_utc)
    ingress_events = [x for x in (ingress_a, ingress_b) if x]
    station_events = [x for x in (station_a, station_b) if x]

    hard_end_days = 180.0
    if ingress_events:
        hard_end_days = min(hard_end_days, min(float(x["days_from_question"]) for x in ingress_events) + 0.02)
    end_dt = dt_utc + timedelta(days=max(0.02, hard_end_days))
    exact = _find_exact_aspect(body_a, body_b, float(state["angle"]), dt_utc, end_dt)

    events = []
    if exact:
        events.append(exact)
    events.extend(ingress_events)
    events.extend(station_events)
    events.sort(key=lambda x: float(x.get("days_from_question") or 0.0))

    blocking_station = None
    for row in station_events:
        station_dt = _parse_utc(row["utc"])
        if _station_breaks_application(body_a, body_b, float(state["angle"]), station_dt):
            blocking_station = row
            break

    blockers = list(ingress_events)
    if blocking_station:
        blockers.append(blocking_station)
    blockers.sort(key=lambda x: float(x.get("days_from_question") or 0.0))
    first_blocker = blockers[0] if blockers else None

    if exact and (first_blocker is None or float(exact["days_from_question"]) <= float(first_blocker["days_from_question"]) + 1e-6):
        exact_dt = _parse_utc(exact["utc"])
        return {
            "perfects": True,
            "indeterminate": False,
            "reason": "perfects",
            "reason_ko": "유효 적용각이 별자리 변경이나 적용 철회보다 먼저 정확해집니다.",
            "aspect": state,
            "exact_utc": exact_dt.isoformat(),
            "exact_local": _iso_local(exact_dt, timezone_name),
            "exact_orb": exact["exact_orb"],
            "days_from_question": exact["days_from_question"],
            "before_sign_change": True,
            "perfection_check_started": True,
            "refranation_applicable": True,
            "started_within_orb": True,
            "event_queue": events[:8],
            "first_event": exact,
        }

    if first_blocker and first_blocker.get("type") == "sign_ingress":
        return {
            "perfects": False,
            "indeterminate": False,
            "reason": "sign_change_before_perfection",
            "reason_ko": "유효 적용각은 있으나 정확각 완성 전에 주인행성이 별자리를 바꿉니다. 이는 sign ingress 중단이며 Refranation(리프레이네이션)과 별도입니다.",
            "aspect": state,
            "before_sign_change": False,
            "sign_change_body": first_blocker.get("body"),
            "interruption_type": "sign_ingress",
            "is_refranation": False,
            "perfection_check_started": True,
            "refranation_applicable": True,
            "started_within_orb": True,
            "event_queue": events[:8],
            "first_event": first_blocker,
        }

    if first_blocker and first_blocker.get("type") == "station":
        return {
            "perfects": False,
            "indeterminate": False,
            "reason": "refranation_station_before_perfection",
            "reason_ko": "유효 적용각이 있었지만 정확각 전에 정지·방향 전환이 적용을 깨뜨려 Refranation(리프레이네이션)으로 분류합니다.",
            "aspect": state,
            "before_sign_change": True,
            "interruption_type": "station",
            "is_refranation": True,
            "station": first_blocker,
            "perfection_check_started": True,
            "refranation_applicable": True,
            "started_within_orb": True,
            "event_queue": events[:8],
            "first_event": first_blocker,
        }

    return {
        "perfects": False,
        "indeterminate": False,
        "reason": "valid_applying_no_exact_perfection",
        "reason_ko": "유효 적용각은 확인되지만 현재 별자리 안에서 정확각 완성이 확인되지 않습니다.",
        "aspect": state,
        "before_sign_change": None,
        "perfection_check_started": True,
        "refranation_applicable": True,
        "started_within_orb": True,
        "event_queue": events[:8],
        "first_event": events[0] if events else None,
    }


def _exact_events_between(body_a: str, body_b: str, start_dt: datetime, end_dt: datetime):
    if end_dt <= start_dt:
        return []
    step_hours = 0.5 if "Moon" in {body_a, body_b} else 2.0
    times = list(core._sample_datetimes(start_dt, end_dt, step_hours))
    if len(times) < 3:
        return []
    a_lons = np.asarray(core.get_tropical_ecliptic_lons(body_a, times), dtype=float)
    b_lons = np.asarray(core.get_tropical_ecliptic_lons(body_b, times), dtype=float)
    seps = np.abs((a_lons - b_lons + 180.0) % 360.0 - 180.0)
    out = []

    for key, spec in core.HORARY_ASPECTS.items():
        errors = np.abs(seps - float(spec["angle"]))
        for i in range(1, len(times) - 1):
            if not (errors[i] <= errors[i - 1] and errors[i] <= errors[i + 1]):
                continue
            if float(errors[i]) > 0.8:
                continue
            try:
                exact, orb = _refine_exact_aspect(body_a, body_b, float(spec["angle"]), times[i - 1], times[i + 1])
            except Exception:
                continue
            if orb > ASPECT_EXACT_TOL or not (start_dt <= exact <= end_dt):
                continue
            stamp = round(exact.timestamp(), 1)
            if any(x["_stamp"] == stamp and x["aspect"] == key for x in out):
                continue
            out.append({
                "_stamp": stamp,
                "body": body_b if body_a == "Moon" else body_a,
                "body_ko": core.PLANET_KO.get(body_b if body_a == "Moon" else body_a, body_b if body_a == "Moon" else body_a),
                "aspect": key,
                "aspect_ko": spec.get("label_ko", key),
                "exact_utc": exact.isoformat(),
                "exact_orb": round(orb, 6),
            })
    out.sort(key=lambda x: x["_stamp"])
    return out


def _strict_moon_course(planets, dt_utc, timezone_name):
    moon = planets["Moon"]
    next_ingress = _next_sign_ingress("Moon", moon, dt_utc, horizon_days=4.0)
    if not next_ingress:
        remaining = (30.0 - (float(moon["longitude"]) % 30.0)) % 30.0
        speed = max(0.1, abs(float(moon.get("speed_deg_per_day") or 13.0)))
        end_dt = dt_utc + timedelta(days=max(0.01, remaining / speed))
    else:
        end_dt = _parse_utc(next_ingress["utc"])

    prev_dt = _previous_sign_ingress("Moon", moon, dt_utc, horizon_days=4.0)
    future = []
    past = []
    for body in core.HORARY_PLANETS:
        if body == "Moon":
            continue
        future.extend(_exact_events_between("Moon", body, dt_utc, end_dt))
        past.extend(_exact_events_between("Moon", body, prev_dt, dt_utc))

    future.sort(key=lambda x: _parse_utc(x["exact_utc"]))
    past.sort(key=lambda x: _parse_utc(x["exact_utc"]))

    future_rows = []
    for row in future:
        exact = _parse_utc(row["exact_utc"])
        future_rows.append({k: v for k, v in row.items() if k != "_stamp"} | {
            "time_local": _iso_local(exact, timezone_name),
            "hours_from_question": round((exact - dt_utc).total_seconds() / 3600.0, 4),
            "orb": row["exact_orb"],
            "applying": True,
            "before_sign_change": exact <= end_dt,
        })

    last = None
    if past:
        row = past[-1]
        exact = _parse_utc(row["exact_utc"])
        last = {k: v for k, v in row.items() if k != "_stamp"} | {
            "time_local": _iso_local(exact, timezone_name),
            "hours_before_question": round((dt_utc - exact).total_seconds() / 3600.0, 4),
            "separating": True,
        }

    hours_to_exit = max(0.0, (end_dt - dt_utc).total_seconds() / 3600.0)
    next_row = future_rows[0] if future_rows else None
    return {
        "void_of_course": next_row is None,
        "policy": "traditional_7_planets_ptolemaic_aspects_before_moon_sign_ingress",
        "policy_ko": "전통 7행성 기준 VOC · 주요 Ptolemaic(프톨레마이오스) 5각만 사용",
        "traditional_planets_only": True,
        "outer_planets_included": False,
        "minor_aspects_included": False,
        "sign_exit_utc": end_dt.isoformat(),
        "sign_exit_local": _iso_local(end_dt, timezone_name),
        "hours_to_sign_exit": round(hours_to_exit, 4),
        "last_major_separating_aspect": last,
        "next_major_applying_aspect": next_row,
        "next_applying_before_sign_change": bool(next_row),
        "next_aspects": future_rows[:6],
    }


def _strict_warning_flags(houses, planets, moon_course):
    warnings = []
    asc_degree = float(houses["asc"]) % 30.0
    if asc_degree < 3.0:
        warnings.append({
            "code": "early_asc", "level": "caution", "invalidates_chart": False,
            "text_ko": "ASC(상승점)가 0°~3° 초도수입니다. 질문이 너무 이르거나 상황이 아직 형성 중인지 점검하는 보조 경고이며 차트를 무효화하지 않습니다.",
        })
    if asc_degree >= 27.0:
        warnings.append({
            "code": "late_asc", "level": "caution", "invalidates_chart": False,
            "text_ko": "ASC(상승점)가 27°~30° 말도수입니다. 상황이 이미 상당 부분 진행되었거나 질문자가 모르는 결론이 형성됐을 가능성을 점검하는 보조 경고이며 자동 NO·차트 무효 사유가 아닙니다.",
        })
    if int(planets["Saturn"].get("house") or 0) == 7:
        warnings.append({
            "code": "saturn_in_7", "level": "caution", "invalidates_chart": False,
            "text_ko": "Saturn(토성)이 7하우스에 있습니다. 해석의 지연·오류 가능성을 점검하는 전통적 고려사항이며 단독으로 차트를 폐기하지 않습니다.",
        })
    moon_lon = float(planets["Moon"]["longitude"])
    if 195.0 <= moon_lon <= 225.0:
        warnings.append({
            "code": "moon_via_combusta", "level": "caution", "invalidates_chart": False,
            "text_ko": "Moon(달)이 Via Combusta(비아 콤부스타·연소의 길)에 있습니다. 정서적 혼란·불안정성을 점검하는 보조 고려사항입니다.",
        })
    if moon_course.get("void_of_course"):
        warnings.append({
            "code": "void_moon", "level": "caution", "invalidates_chart": False,
            "text_ko": "Moon(달)이 현재 별자리를 떠나기 전 전통 7행성과 완성하는 주요 Ptolemaic 적용각이 없습니다. 외행성·노드·소행성·포인트는 VOC 판정에서 제외했습니다.",
        })
    return warnings


def _pair_axis(label, a_name, a_row, b_name, b_row, dt_utc, timezone_name):
    if not a_name or not b_name or not a_row or not b_row:
        return None
    if a_name == b_name:
        return {
            "label": label, "a": a_name, "b": b_name, "shared_ruler": True,
            "aspect_state": None,
            "perfection": {"perfects": False, "indeterminate": True, "reason": "same_significator", "reason_ko": "같은 주인행성을 공유해 두 행성 직접각으로 판정하지 않습니다."},
            "reception": None,
        }
    state = _strict_aspect_state(a_name, a_row, b_name, b_row)
    perfection = _strict_perfection_candidate(a_name, a_row, b_name, b_row, dt_utc, timezone_name)
    reception = core._horary_reception(a_name, a_row, b_name, b_row)
    return {
        "label": label, "a": a_name, "b": b_name, "shared_ruler": False,
        "aspect_state": state, "perfection": perfection, "reception": reception,
    }


def _axis_with_reception(data, label, a_name, a_row, b_name, b_row, dt_utc, timezone_name):
    row = _pair_axis(label, a_name, a_row, b_name, b_row, dt_utc, timezone_name)
    if not row or row.get("shared_ruler"):
        return row
    try:
        day_chart = bool(v31._is_day_chart(data))
        row["reception"] = v31._extended_reception(a_name, a_row, b_name, b_row, day_chart)
    except Exception:
        pass
    return row


def _build_traditional_core(data, timezone_name):
    sig = data.get("significators") or {}
    j = data.get("judgment_support") or {}
    q = sig.get("querent") or {}
    t = sig.get("quesited") or {}
    event = sig.get("event") or None
    dt_utc = _parse_utc((data.get("moment") or {}).get("utc_iso"))
    qn, tn = q.get("ruler"), t.get("ruler")
    qr, tr = q.get("planet"), t.get("planet")

    direct = _axis_with_reception(data, "quesited_to_querent", tn, tr, qn, qr, dt_utc, timezone_name) if qn and tn and qr and tr else None
    event_axes = {}
    if event and event.get("ruler") and event.get("planet"):
        en, er = event.get("ruler"), event.get("planet")
        event_axes["quesited_to_event"] = _axis_with_reception(data, "quesited_to_event", tn, tr, en, er, dt_utc, timezone_name)
        event_axes["event_to_querent"] = _axis_with_reception(data, "event_to_querent", en, er, qn, qr, dt_utc, timezone_name)

    balance31 = j.get("balance_v31") or {}
    indirect = balance31.get("indirect_perfection") or {}
    translation = indirect.get("translation_of_light") or []
    collection = indirect.get("collection_of_light") or []
    confirmed = balance31.get("confirmed_obstructions") or {}
    interventions = confirmed.get("prohibition_or_frustration") or []
    strict_refranation = confirmed.get("refranation")

    direct_perfects = bool((direct or {}).get("perfection", {}).get("perfects"))
    event_perfects = any(bool((row or {}).get("perfection", {}).get("perfects")) for row in event_axes.values())
    reception = (direct or {}).get("reception") or {}
    reception_present = bool(reception.get("grade") not in {None, "none"} or reception.get("has_reception") or reception.get("has_minor_reception"))
    indirect_present = bool(translation or collection)

    if direct_perfects:
        grade, grade_ko = "A", "A등급 · 주 시그니피케이터 직접 적용 성사"
    elif indirect_present:
        grade, grade_ko = "B", "B등급 · Translation/Collection 간접 성사"
    elif event_perfects:
        grade, grade_ko = "C", "C등급 · 파생 사건축 보조 연결"
    elif reception_present:
        grade, grade_ko = "D", "D등급 · 리셉션만 존재"
    else:
        grade, grade_ko = "NONE", "직접·간접 성사 근거 없음"

    moon = j.get("moon_course") or {}
    warning_codes = [w.get("code") for w in (j.get("warnings") or [])]
    contact_meta = None
    if str((data.get("question") or {}).get("topic")) == "contact":
        contact_meta = {
            "target_person_house": 7,
            "target_message_house": 9,
            "derivation": "3rd from 7th = radical 9H",
            "note_ko": "특정 상대의 연락은 상대=7H, 상대가 보내는 메시지=7H의 3H인 radical 9H로 고정합니다.",
        }

    direct_label = "있음" if direct_perfects else "없음"
    secondary_label = "있음" if (indirect_present or event_perfects) else "없음"
    moon_label = "없음 · VOC" if moon.get("void_of_course") else "있음"
    reception_label = reception.get("label_ko") or ("부분 있음" if reception_present else "없음")
    intervention_label = "있음" if (interventions or strict_refranation) else "없음"

    if direct_perfects:
        overall = "주 시그니피케이터 간 유효 적용 성사각이 확인됩니다."
    elif indirect_present:
        overall = "직접 성사각은 없지만 Translation/Collection의 간접 연결이 있습니다."
    elif event_perfects:
        overall = "직접 성사각은 없고 파생 사건축에만 보조 행동 신호가 있습니다."
    elif reception_present:
        overall = "호의·수용성 신호는 있으나 사건 성립을 대체할 직접·간접 성사 근거는 부족합니다."
    else:
        overall = "현재 차트에서는 주 시그니피케이터의 직접 성사 근거와 확인된 간접 성사 근거가 부족합니다."

    return {
        "version": VERSION,
        "policy": "strict_traditional_core",
        "traditional_planets": list(core.HORARY_PLANETS),
        "traditional_aspects": list(core.HORARY_ASPECTS),
        "chart_invalid": False,
        "direct_axis": direct,
        "derived_event_axes": event_axes,
        "derived_house_policy": contact_meta,
        "evidence_grade": grade,
        "evidence_grade_ko": grade_ko,
        "reception_role": "support_only_not_perfection_substitute",
        "dignity_role": "action_capacity_quality_not_event_yes_no",
        "moon": moon,
        "indirect_perfection": {"translation_of_light": translation, "collection_of_light": collection},
        "interventions": {"prohibition_or_frustration": interventions, "refranation": strict_refranation},
        "considerations": {
            "warnings": j.get("warnings") or [],
            "early_asc": "early_asc" in warning_codes,
            "late_asc": "late_asc" in warning_codes,
            "chart_invalid": False,
        },
        "staged_judgment": {
            "direct_perfection": direct_label,
            "secondary_perfection": secondary_label,
            "moon_support": moon_label,
            "reception": reception_label,
            "intervention": intervention_label,
            "considerations": [w.get("text_ko") for w in (j.get("warnings") or [])],
            "overall_ko": overall,
        },
        "time_debug": {
            "local_iso": (data.get("moment") or {}).get("local_iso"),
            "timezone": (data.get("moment") or {}).get("timezone"),
            "utc_iso": (data.get("moment") or {}).get("utc_iso"),
            "latitude": (data.get("moment") or {}).get("latitude"),
            "longitude": (data.get("moment") or {}).get("longitude"),
        },
    }


def _modern_supplemental(data):
    moment = data.get("moment") or {}
    dt_utc = _parse_utc(moment.get("utc_iso"))
    cusps = data.get("cusps") or []
    rows = {}
    for body in ("Uranus", "Neptune", "Pluto"):
        try:
            lon, speed, direction = core.planet_motion(body, dt_utc)
            sd = core.sign_data(lon)
            rows[body] = {
                **sd,
                "name_ko": core.PLANET_KO.get(body, body),
                "house": core.cusp_house(lon, cusps) if len(cusps) == 12 else None,
                "speed_deg_per_day": round(float(speed), 6),
                "direction": direction,
                "retrograde": direction == "역행",
            }
        except Exception as exc:
            rows[body] = {"error": f"{type(exc).__name__}: {exc}"}
    return {
        "used_in_traditional_core": False,
        "planets": rows,
        "excluded_from_voc_perfection_translation_collection_reception": True,
        "other_excluded_points": ["Node", "South Node", "Chiron", "Lilith", "Vertex", "PartOfFortune"],
        "note_ko": "외행성과 현대 포인트는 Modern Supplemental(현대 보조정보)로만 분리하며 전통 VOC·성사·빛의 전달/수집·리셉션 계산에는 사용하지 않습니다.",
    }


def _strict_refranation_pattern(data):
    p = ((data.get("judgment_support") or {}).get("perfection") or {})
    if p.get("reason") != "refranation_station_before_perfection":
        return None
    station = p.get("station") or p.get("first_event") or {}
    return {
        "type": "refranation",
        "classification": "confirmed_pattern",
        "body": station.get("body"),
        "body_ko": station.get("body_ko"),
        "station_utc": station.get("utc"),
        "days_from_question": station.get("days_from_question"),
        "note_ko": "유효 적용각이 존재한 뒤 정확각 이전의 실제 station/direction change가 적용을 깨뜨린 경우에만 Refranation으로 분류합니다.",
    }


def _postprocess(data, timezone_name):
    if not isinstance(data, dict) or data.get("schema") != "LUNEA_HORARY_V1":
        return data
    j = data.setdefault("judgment_support", {})
    sig = data.get("significators") or {}
    q = sig.get("querent") or {}
    t = sig.get("quesited") or {}
    dt_utc = _parse_utc((data.get("moment") or {}).get("utc_iso"))

    if q.get("ruler") and t.get("ruler") and q.get("planet") and t.get("planet"):
        if q.get("ruler") != t.get("ruler"):
            j["primary_connection"] = _strict_aspect_state(q["ruler"], q["planet"], t["ruler"], t["planet"])
        else:
            j["primary_connection"] = None
        j["perfection"] = _strict_perfection_candidate(q["ruler"], q["planet"], t["ruler"], t["planet"], dt_utc, timezone_name)

    j["moon_course"] = _strict_moon_course(data.get("planets") or {}, dt_utc, timezone_name)
    houses = {"asc": ((data.get("angles") or {}).get("ASC") or {}).get("longitude", 0.0)}
    j["warnings"] = _strict_warning_flags(houses, data.get("planets") or {}, j["moon_course"])

    balance31 = j.get("balance_v31")
    if isinstance(balance31, dict):
        confirmed = balance31.setdefault("confirmed_obstructions", {})
        confirmed["refranation"] = _strict_refranation_pattern(data)
        balance31["interpretation_note_ko"] = (
            "Strict V6 gate 적용: 현재 유효 오브 안의 applying/exact 주요각만 직접 Perfection 파이프라인에 들어갑니다. "
            "유효 오브 밖의 기하학적 각은 직접 성사로 채택하지 않으며, sign ingress 중단과 station 기반 Refranation을 구분합니다."
        )
        balance31["supporting_evidence_ko"] = [
            x for x in (balance31.get("supporting_evidence_ko") or [])
            if "현재 오브 밖에서 시작하지만" not in str(x)
        ]

    j["traditional_core_v6"] = _build_traditional_core(data, timezone_name)
    j["modern_supplemental_v6"] = _modern_supplemental(data)

    meta = data.setdefault("meta", {})
    meta["horary_engine"] = VERSION
    meta["traditional_core_policy"] = {
        "direct_perfection_requires": "within_moiety_orb_and_applying_or_exact",
        "out_of_orb_direct_perfection": False,
        "applying_method": "actual_ephemeris_short_step_error",
        "voc": "traditional_7_planets_ptolemaic_before_moon_sign_ingress",
        "reception_substitutes_perfection": False,
        "outer_planets_in_core": False,
    }
    meta["house_calculation"] = {
        "system": "Regiomontanus",
        "engine": "Swiss Ephemeris houses_ex",
        "flags": 0,
        "zodiac": "tropical",
        "coordinate_source": "request latitude/longitude",
        "elevation_used": False,
    }
    return data


def _compute_horary_v6(*args, **kwargs):
    timezone_name = kwargs.get("timezone_name", "Asia/Seoul")
    question_iso = kwargs.get("question_iso")
    if question_iso is None and len(args) >= 2:
        question_iso = args[1]
    try:
        _, dt_utc = core._horary_local_to_utc(question_iso, timezone_name)
    except Exception:
        dt_utc = None

    token = _CONTEXT_DT_UTC.set(dt_utc)
    try:
        data = _ORIGINAL_COMPUTE_HORARY(*args, **kwargs)
        return _postprocess(data, timezone_name)
    finally:
        _CONTEXT_DT_UTC.reset(token)


core._horary_aspect_state = _strict_aspect_state
core._horary_perfection_candidate = _strict_perfection_candidate
core._horary_moon_course = _strict_moon_course
core._horary_warning_flags = _strict_warning_flags
v3._balanced_perfection_candidate = _strict_perfection_candidate
v31._refranation_pattern = _strict_refranation_pattern

if not getattr(v31.compute_horary, "_lunea_engine_v6", False):
    _compute_horary_v6._lunea_engine_v6 = True
    v31.compute_horary = _compute_horary_v6
