from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

import astro_core as core


# LUNEA HORARY BALANCE V2
# -----------------------
# This layer keeps the deterministic Horary V1 calculations, but removes a
# UI/decision bias that treated the absence of a very short direct perfection
# window as an automatic negative.  It adds:
# - perfection search out to 180 days, while still refusing perfection after
#   either significator changes sign;
# - same-ruler handling as indeterminate/shared rather than an automatic "no";
# - event-house secondary connections for topics that define an event ruler;
# - Moon-to-significator next-aspect evidence;
# - a non-binary evidence tier for the client/AI to present.
#
# It does NOT turn difficult charts positive.  Direct perfection, sign changes,
# receptions, hard aspects, void Moon and potential intervention stay explicit.


def _iso_local(dt_utc, timezone_name):
    return core._iso_local(dt_utc, timezone_name)


def _balanced_perfection_candidate(body_a, row_a, body_b, row_b, dt_utc, timezone_name):
    if body_a == body_b:
        return {
            "perfects": False,
            "indeterminate": True,
            "shared_ruler": True,
            "reason": "same_significator",
            "reason_ko": (
                "질문자와 대상이 같은 주인행성을 공유합니다. "
                "두 행성 사이의 적용각 부재를 불성사로 보지 않고 Moon(달)과 사건축을 함께 봅니다."
            ),
        }

    aspect = core._horary_aspect_state(body_a, row_a, body_b, row_b)
    if aspect["phase"] not in {"applying", "exact"}:
        return {
            "perfects": False,
            "indeterminate": False,
            "reason": "no_applying_aspect",
            "reason_ko": "현재 유효 오브 안에서 두 주인행성의 적용각이 확인되지 않습니다.",
            "aspect": aspect,
        }

    if aspect["phase"] == "exact":
        return {
            "perfects": True,
            "indeterminate": False,
            "reason": "exact_now",
            "reason_ko": "질문 시각에 두 주인행성의 각이 이미 정확합니다.",
            "aspect": aspect,
            "exact_utc": dt_utc.isoformat(),
            "exact_local": _iso_local(dt_utc, timezone_name),
            "days_from_question": 0.0,
            "before_sign_change": True,
            "search_horizon_days": 0.0,
        }

    rel_speed = float(aspect.get("relative_speed_deg_per_day") or 0.0)
    if rel_speed < 0.01:
        return {
            "perfects": False,
            "indeterminate": True,
            "reason": "relative_motion_too_slow",
            "reason_ko": (
                "현재 상대 속도가 매우 느립니다. 단기 불성사로 단정하지 않고 "
                "Moon(달)·리셉션·사건축 보조 근거를 함께 봅니다."
            ),
            "aspect": aspect,
        }

    rough_days = float(aspect["orb"]) / rel_speed
    # V1 used a hard 30-day cap. Horary timing can involve slower rulers, so
    # search farther but still reject any candidate that requires a sign change.
    horizon_days = min(180.0, max(7.0, rough_days * 2.2 + 3.0))
    if "Moon" in {body_a, body_b}:
        step_hours = 1.0
    elif horizon_days <= 45.0:
        step_hours = 3.0
    elif horizon_days <= 120.0:
        step_hours = 6.0
    else:
        step_hours = 8.0

    times = core._sample_datetimes(dt_utc, dt_utc + timedelta(days=horizon_days), step_hours)
    a_lons = core.get_tropical_ecliptic_lons(body_a, times)
    b_lons = core.get_tropical_ecliptic_lons(body_b, times)

    start_a_sign = int(float(row_a["longitude"]) // 30)
    start_b_sign = int(float(row_b["longitude"]) // 30)
    cut = len(times)
    sign_change_body = None
    for i in range(1, len(times)):
        if int(float(a_lons[i]) // 30) != start_a_sign:
            cut = i
            sign_change_body = body_a
            break
        if int(float(b_lons[i]) // 30) != start_b_sign:
            cut = i
            sign_change_body = body_b
            break

    if cut < 2:
        return {
            "perfects": False,
            "indeterminate": False,
            "reason": "sign_change_before_perfection",
            "reason_ko": "적용각이 완성되기 전에 주인행성이 별자리를 바꿉니다.",
            "aspect": aspect,
            "before_sign_change": False,
            "sign_change_body": sign_change_body,
            "search_horizon_days": round(horizon_days, 3),
        }

    valid_times = times[:cut]
    valid_a = np.asarray(a_lons[:cut], dtype=float)
    valid_b = np.asarray(b_lons[:cut], dtype=float)
    seps = np.abs((valid_a - valid_b + 180.0) % 360.0 - 180.0)
    orbs = np.abs(seps - float(aspect["angle"]))
    idx = int(np.argmin(orbs))
    minimum = float(orbs[idx])

    # The adaptive grid is coarse only for slow pairs.  0.6° is used only to
    # find a bracket; the refinement below decides the actual exactness.
    if minimum > 0.6:
        reached_horizon = cut == len(times)
        return {
            "perfects": False,
            "indeterminate": bool(reached_horizon and horizon_days >= 179.9),
            "reason": "extended_horizon_no_perfection" if reached_horizon else "sign_change_before_perfection",
            "reason_ko": (
                "별자리 변경 전에는 정확각 성사가 확인되지 않습니다."
                if not reached_horizon
                else "확장 탐색 범위 안에서 정확각 성사가 확인되지 않습니다."
            ),
            "aspect": aspect,
            "before_sign_change": False if not reached_horizon else None,
            "sign_change_body": sign_change_body,
            "search_horizon_days": round(horizon_days, 3),
        }

    left = valid_times[max(0, idx - 1)]
    right = valid_times[min(len(valid_times) - 1, idx + 1)]
    exact_dt, exact_orb = core._horary_refine_pair(
        body_a, body_b, float(aspect["angle"]), left, right
    )
    a_exact = core.get_tropical_ecliptic_lon(body_a, core.sf_time(exact_dt))
    b_exact = core.get_tropical_ecliptic_lon(body_b, core.sf_time(exact_dt))
    before_sign_change = (
        int(a_exact // 30) == start_a_sign
        and int(b_exact // 30) == start_b_sign
    )
    days_from = (exact_dt - dt_utc).total_seconds() / 86400.0
    exact_enough = float(exact_orb) <= 0.15
    perfects = bool(before_sign_change and exact_enough and days_from >= -1e-6)

    return {
        "perfects": perfects,
        "indeterminate": False,
        "reason": "perfects" if perfects else "sign_change_before_perfection",
        "reason_ko": (
            "두 주인행성의 적용각이 별자리 변경 전에 정확해집니다."
            if perfects
            else "정확각 후보 전 주인행성의 별자리 변경이 확인되어 단순 성사로 판정하지 않습니다."
        ),
        "aspect": aspect,
        "exact_utc": exact_dt.isoformat(),
        "exact_local": _iso_local(exact_dt, timezone_name),
        "exact_orb": round(float(exact_orb), 6),
        "days_from_question": round(float(days_from), 4),
        "before_sign_change": before_sign_change,
        "search_horizon_days": round(horizon_days, 3),
    }


# Patch the helper used by astro_core.compute_horary.  The service imports this
# module once at process start, so all Horary requests use the balanced search.
core._horary_perfection_candidate = _balanced_perfection_candidate


def _pair_evidence(label, a_name, a_row, b_name, b_row, dt_utc, timezone_name):
    if not a_name or not b_name or not a_row or not b_row:
        return None
    if a_name == b_name:
        return {
            "label": label,
            "a": a_name,
            "b": b_name,
            "shared_ruler": True,
            "perfection": {
                "perfects": False,
                "indeterminate": True,
                "shared_ruler": True,
                "reason": "same_significator",
                "reason_ko": "같은 주인행성을 공유합니다.",
            },
            "reception": None,
        }
    return {
        "label": label,
        "a": a_name,
        "b": b_name,
        "shared_ruler": False,
        "perfection": _balanced_perfection_candidate(
            a_name, a_row, b_name, b_row, dt_utc, timezone_name
        ),
        "reception": core._horary_reception(a_name, a_row, b_name, b_row),
    }


def _build_balance(data, timezone_name):
    sig = data.get("significators") or {}
    j = data.get("judgment_support") or {}
    primary = j.get("perfection") or {}
    reception = j.get("reception") or {}
    primary_connection = j.get("primary_connection") or {}
    moon = j.get("moon_course") or {}

    q = sig.get("querent") or {}
    t = sig.get("quesited") or {}
    event = sig.get("event") or None
    dt_utc = datetime.fromisoformat(str(data["moment"]["utc_iso"]).replace("Z", "+00:00"))

    secondary = []
    if event:
        first = _pair_evidence(
            "querent_to_event",
            q.get("ruler"), q.get("planet"),
            event.get("ruler"), event.get("planet"),
            dt_utc, timezone_name,
        )
        second = _pair_evidence(
            "quesited_to_event",
            t.get("ruler"), t.get("planet"),
            event.get("ruler"), event.get("planet"),
            dt_utc, timezone_name,
        )
        seen = set()
        for row in (first, second):
            if not row:
                continue
            key = tuple(sorted((str(row.get("a")), str(row.get("b"))))) + (str(row.get("label")),)
            if key in seen:
                continue
            seen.add(key)
            secondary.append(row)

    relevant = {q.get("ruler"), t.get("ruler")}
    if event:
        relevant.add(event.get("ruler"))
    relevant.discard(None)
    moon_relevant = [
        x for x in (moon.get("next_aspects") or [])
        if x.get("body") in relevant
    ][:4]

    shared_primary = bool(
        reception.get("same_significator")
        or primary.get("shared_ruler")
        or (q.get("ruler") and q.get("ruler") == t.get("ruler"))
    )
    event_perfections = [
        row for row in secondary
        if (row.get("perfection") or {}).get("perfects")
    ]
    event_receptions = [
        row for row in secondary
        if (row.get("reception") or {}).get("has_reception")
    ]

    support = []
    constraints = []

    if primary.get("perfects"):
        support.append("질문자와 대상 주인행성의 직접 성사각")
    if reception.get("has_reception"):
        support.append("질문자·대상 사이 주요 리셉션")
    if shared_primary:
        support.append("질문자와 대상이 같은 주인행성을 공유")
    if event_perfections:
        support.append("사건 보조 주인행성과의 성사 연결")
    elif event_receptions:
        support.append("사건 보조 주인행성과의 리셉션")
    if moon_relevant:
        support.append("Moon(달)이 관련 주인행성으로 다음 적용각을 형성")

    aspect_key = primary_connection.get("aspect")
    if primary.get("perfects") and aspect_key in {"square", "opposition"}:
        constraints.append("직접 성사각은 있으나 사분위/충이라 마찰·조건이 큼")
    if primary.get("reason") == "sign_change_before_perfection":
        constraints.append("직접 적용각 완성 전 주인행성 별자리 변경")
    if primary.get("reason") == "no_applying_aspect":
        constraints.append("질문자·대상 사이 직접 적용각 부재")
    if moon.get("void_of_course"):
        constraints.append("Moon(달) 보이드 오브 코스")
    if j.get("potential_prohibition"):
        constraints.append("주 성사각보다 앞서는 잠재 개입각 후보")

    if primary.get("perfects"):
        if aspect_key in {"square", "opposition"}:
            tier = "direct_with_friction"
            headline = "성사 연결은 있으나 마찰·조건이 큰 차트"
        elif reception.get("has_reception") or event_perfections or moon_relevant:
            tier = "strong_support"
            headline = "성사 근거가 여러 층에서 겹쳐 확인됨"
        else:
            tier = "direct_support"
            headline = "주인행성 사이 직접 성사 연결이 확인됨"
    elif event_perfections and (reception.get("has_reception") or moon_relevant or shared_primary):
        tier = "secondary_support"
        headline = "직접각은 약하지만 사건축·달의 보조 성사 근거가 있음"
    elif event_perfections:
        tier = "secondary_support"
        headline = "직접각 대신 사건 보조축에서 성사 연결이 확인됨"
    elif shared_primary:
        tier = "shared_ruler_open"
        headline = "같은 주인행성 공유 — 단순 예/아니오보다 달·사건축을 함께 봐야 함"
    elif reception.get("has_reception") or event_receptions or moon_relevant:
        tier = "mixed_support"
        headline = "직접 성사각은 없지만 보조 연결이 남아 있어 조건부로 열려 있음"
    elif primary.get("indeterminate"):
        tier = "open_indeterminate"
        headline = "직접 판정이 유보됨 — 현재 근거만으로 불성사를 단정하기 어려움"
    else:
        tier = "weak_direct_support"
        headline = "현재 차트에서는 직접 성사 근거가 약함"

    return {
        "version": "LUNEA_HORARY_BALANCE_V2",
        "tier": tier,
        "headline_ko": headline,
        "supporting_evidence_ko": support,
        "constraints_ko": constraints,
        "shared_primary_ruler": shared_primary,
        "event_connections": secondary,
        "moon_relevant_next_aspects": moon_relevant,
        "interpretation_note_ko": (
            "직접 성사각 부재만으로 자동 부정하지 않습니다. 같은 주인행성, 사건 보조축, "
            "Moon(달)의 다음 적용각, 리셉션, 별자리 변경과 개입각을 함께 보되 현실 사건을 보장하지 않습니다."
        ),
    }


def compute_horary(
    question_text: str,
    question_iso: str,
    topic: str = "general",
    timezone_name: str = "Asia/Seoul",
    place: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
):
    data = core.compute_horary(
        question_text=question_text,
        question_iso=question_iso,
        topic=topic,
        timezone_name=timezone_name,
        place=place,
        lat=lat,
        lon=lon,
    )
    j = data.setdefault("judgment_support", {})
    j["balance_v2"] = _build_balance(data, timezone_name)
    data.setdefault("meta", {})["horary_balance"] = "LUNEA_HORARY_BALANCE_V2"
    return data
