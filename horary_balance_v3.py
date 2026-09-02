from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

import astro_core as core


# LUNEA HORARY BALANCE V3
# -----------------------
# V3 keeps the deterministic traditional Horary core, but fixes the largest
# systematic negative-bias sources left in V2:
#
# 1) A future perfection can be valid even when the significators are not yet
#    inside the current aspect orb. V2 stopped immediately unless the current
#    pair was already applying/exact. V3 searches ALL five Ptolemaic aspects
#    until the first significator changes sign (max 180 days).
# 2) Hard aspects that actually perfect are treated as "perfection with
#    friction", not as a disguised automatic no.
# 3) Reception is graded (mutual major / one-way major / none) so a one-sided
#    reception is not presented as equivalent to mutual reception.
# 4) Moon/event contacts are movement/secondary evidence, while hard Moon
#    contacts remain frictional rather than being counted as purely positive.
# 5) potential_prohibition rows are explicitly potential-only and cannot by
#    themselves overturn a direct perfection.
# 6) Reconciliation gets the 5th-house romance/event axis as SECONDARY evidence;
#    the primary 1st/7th relationship axis is unchanged.
#
# V3 does not try to force a 50/50 positive distribution. Strong negative
# testimony (sign change before perfection, void Moon, no reception/support)
# remains visible. The goal is to stop missing legitimate positive/mixed
# evidence, not to make charts optimistic.


try:
    if "reconciliation" in core.HORARY_TOPIC_SPECS:
        core.HORARY_TOPIC_SPECS["reconciliation"] = {
            **core.HORARY_TOPIC_SPECS["reconciliation"],
            "event_house": 5,
            "note": "질문자와 특정 상대의 1–7하우스 관계축을 우선하고, 5하우스는 재회 후 연애 전개를 보조로 봅니다.",
        }
except Exception:
    pass


def _iso_local(dt_utc, timezone_name):
    return core._iso_local(dt_utc, timezone_name)


def _aspect_snapshot(body_a, row_a, body_b, row_b, aspect_key):
    spec = core.HORARY_ASPECTS[aspect_key]
    sep = core.angular_separation(row_a["longitude"], row_b["longitude"])
    orb = abs(float(sep) - float(spec["angle"]))
    try:
        limit = float(core._horary_aspect_limit(body_a, body_b, aspect_key))
    except Exception:
        limit = 8.0
    return {
        "a": body_a,
        "a_ko": core.PLANET_KO.get(body_a, body_a),
        "b": body_b,
        "b_ko": core.PLANET_KO.get(body_b, body_b),
        "aspect": aspect_key,
        "aspect_ko": spec.get("label_ko", aspect_key),
        "angle": float(spec["angle"]),
        "orb": round(float(orb), 4),
        "max_orb": round(float(limit), 2),
        "phase": "future_applying",
        "phase_ko": "향후 적용",
        "within_orb": bool(orb <= limit),
        "relative_speed_deg_per_day": round(
            abs(float(row_a.get("speed_deg_per_day") or 0.0) - float(row_b.get("speed_deg_per_day") or 0.0)),
            6,
        ),
    }


def _first_sign_change_cut(a_lons, b_lons, row_a, row_b):
    start_a_sign = int(float(row_a["longitude"]) // 30)
    start_b_sign = int(float(row_b["longitude"]) // 30)
    cut = min(len(a_lons), len(b_lons))
    sign_change_body = None
    for i in range(1, cut):
        if int(float(a_lons[i]) // 30) != start_a_sign:
            return i, "a"
        if int(float(b_lons[i]) // 30) != start_b_sign:
            return i, "b"
    return cut, sign_change_body



def _sample_until_first_sign_change(body_a, row_a, body_b, row_b, dt_utc, horizon_days, step_hours):
    """Sample in chunks and stop as soon as either significator leaves its sign."""
    end_dt = dt_utc + timedelta(days=float(horizon_days))
    max_speed = max(
        abs(float(row_a.get("speed_deg_per_day") or 0.0)),
        abs(float(row_b.get("speed_deg_per_day") or 0.0)),
    )
    chunk_days = 3.0 if "Moon" in {body_a, body_b} else 10.0 if max_speed >= 0.45 else 30.0
    start_a_sign = int(float(row_a["longitude"]) // 30)
    start_b_sign = int(float(row_b["longitude"]) // 30)
    all_times, all_a, all_b = [], [], []
    cursor = dt_utc

    while cursor < end_dt:
        chunk_end = min(end_dt, cursor + timedelta(days=chunk_days))
        chunk_times = list(core._sample_datetimes(cursor, chunk_end, step_hours))
        if all_times and chunk_times and chunk_times[0] == all_times[-1]:
            chunk_times = chunk_times[1:]
        if not chunk_times:
            break
        a_chunk = np.asarray(core.get_tropical_ecliptic_lons(body_a, chunk_times), dtype=float)
        b_chunk = np.asarray(core.get_tropical_ecliptic_lons(body_b, chunk_times), dtype=float)
        for t, a_lon, b_lon in zip(chunk_times, a_chunk, b_chunk):
            if int(float(a_lon) // 30) != start_a_sign:
                return all_times, np.asarray(all_a, dtype=float), np.asarray(all_b, dtype=float), body_a
            if int(float(b_lon) // 30) != start_b_sign:
                return all_times, np.asarray(all_a, dtype=float), np.asarray(all_b, dtype=float), body_b
            all_times.append(t)
            all_a.append(float(a_lon))
            all_b.append(float(b_lon))
        cursor = chunk_end

    return all_times, np.asarray(all_a, dtype=float), np.asarray(all_b, dtype=float), None


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

    initial = core._horary_aspect_state(body_a, row_a, body_b, row_b)
    if initial.get("phase") == "exact":
        return {
            "perfects": True,
            "indeterminate": False,
            "reason": "exact_now",
            "reason_ko": "질문 시각에 두 주인행성의 각이 이미 정확합니다.",
            "aspect": initial,
            "exact_utc": dt_utc.isoformat(),
            "exact_local": _iso_local(dt_utc, timezone_name),
            "days_from_question": 0.0,
            "before_sign_change": True,
            "search_horizon_days": 0.0,
            "started_within_orb": True,
        }

    rel_speed = abs(float(row_a.get("speed_deg_per_day") or 0.0) - float(row_b.get("speed_deg_per_day") or 0.0))
    if rel_speed < 0.003:
        return {
            "perfects": False,
            "indeterminate": True,
            "reason": "relative_motion_too_slow",
            "reason_ko": (
                "두 주인행성의 상대 운동이 매우 느려 직접 성사 시각을 안정적으로 잡기 어렵습니다. "
                "이를 자동 불성사로 보지 않고 리셉션·Moon·사건축을 함께 봅니다."
            ),
            "aspect": initial,
        }

    horizon_days = 180.0
    if "Moon" in {body_a, body_b}:
        step_hours = 1.0
    elif max(abs(float(row_a.get("speed_deg_per_day") or 0.0)), abs(float(row_b.get("speed_deg_per_day") or 0.0))) >= 0.45:
        step_hours = 2.0
    elif rel_speed >= 0.18:
        step_hours = 3.0
    elif rel_speed >= 0.05:
        step_hours = 6.0
    else:
        step_hours = 8.0

    valid_times, valid_a, valid_b, sign_change_body = _sample_until_first_sign_change(
        body_a, row_a, body_b, row_b, dt_utc, horizon_days, step_hours
    )
    start_a_sign = int(float(row_a["longitude"]) // 30)
    start_b_sign = int(float(row_b["longitude"]) // 30)
    if len(valid_times) < 2:
        return {
            "perfects": False,
            "indeterminate": False,
            "reason": "sign_change_before_perfection",
            "reason_ko": "정확한 주요각을 만들기 전에 주인행성이 별자리를 바꿉니다.",
            "aspect": initial,
            "before_sign_change": False,
            "sign_change_body": sign_change_body,
            "search_horizon_days": round(horizon_days, 3),
        }

    seps = np.abs((valid_a - valid_b + 180.0) % 360.0 - 180.0)
    candidates = []

    for aspect_key, spec in core.HORARY_ASPECTS.items():
        angle = float(spec["angle"])
        orbs = np.abs(seps - angle)
        idx = int(np.argmin(orbs))
        minimum = float(orbs[idx])

        bracket_limit = 0.75 if step_hours <= 2 else 1.0 if step_hours <= 3 else 1.35
        if minimum > bracket_limit:
            continue

        left = valid_times[max(0, idx - 1)]
        right = valid_times[min(len(valid_times) - 1, idx + 1)]
        if right <= left:
            continue
        try:
            exact_dt, exact_orb = core._horary_refine_pair(body_a, body_b, angle, left, right)
        except Exception:
            continue

        days_from = (exact_dt - dt_utc).total_seconds() / 86400.0
        if days_from < -1e-6:
            continue

        try:
            a_exact = core.get_tropical_ecliptic_lon(body_a, core.sf_time(exact_dt))
            b_exact = core.get_tropical_ecliptic_lon(body_b, core.sf_time(exact_dt))
        except Exception:
            continue
        before_sign_change = (
            int(float(a_exact) // 30) == start_a_sign
            and int(float(b_exact) // 30) == start_b_sign
        )
        if not before_sign_change or float(exact_orb) > 0.15:
            continue

        snapshot = _aspect_snapshot(body_a, row_a, body_b, row_b, aspect_key)
        if snapshot["orb"] <= 0.05:
            snapshot["phase"] = "exact"
            snapshot["phase_ko"] = "정확"
        elif snapshot["within_orb"]:
            snapshot["phase"] = "applying"
            snapshot["phase_ko"] = "적용"

        candidates.append({
            "perfects": True,
            "indeterminate": False,
            "reason": "perfects" if snapshot["within_orb"] else "future_perfection_from_out_of_orb",
            "reason_ko": (
                "두 주인행성의 적용각이 별자리 변경 전에 정확해집니다."
                if snapshot["within_orb"]
                else "현재 유효 오브 밖이지만 두 주인행성이 별자리 변경 전에 주요각을 정확히 완성합니다."
            ),
            "aspect": snapshot,
            "exact_utc": exact_dt.isoformat(),
            "exact_local": _iso_local(exact_dt, timezone_name),
            "exact_orb": round(float(exact_orb), 6),
            "days_from_question": round(float(days_from), 4),
            "before_sign_change": True,
            "search_horizon_days": round(horizon_days, 3),
            "started_within_orb": bool(snapshot["within_orb"]),
        })

    if candidates:
        candidates.sort(key=lambda row: (float(row.get("days_from_question") or 0.0), float(row.get("exact_orb") or 99.0)))
        return candidates[0]

    if sign_change_body:
        return {
            "perfects": False,
            "indeterminate": False,
            "reason": "sign_change_before_perfection",
            "reason_ko": "주요각이 정확해지기 전에 주인행성이 별자리를 바꿉니다.",
            "aspect": initial,
            "before_sign_change": False,
            "sign_change_body": sign_change_body,
            "search_horizon_days": round(horizon_days, 3),
        }

    return {
        "perfects": False,
        "indeterminate": True,
        "reason": "extended_horizon_no_perfection",
        "reason_ko": (
            "확장 탐색 범위에서 직접 정확각 성사가 확인되지 않았습니다. "
            "이 결과만으로 자동 불성사로 단정하지 않고 보조 근거를 함께 봅니다."
        ),
        "aspect": initial,
        "before_sign_change": None,
        "search_horizon_days": round(horizon_days, 3),
    }


core._horary_perfection_candidate = _balanced_perfection_candidate


def _reception_grade(reception):
    r = reception or {}
    if r.get("same_significator"):
        return {"grade": "shared", "weight": 0.8, "label_ko": "같은 주인행성 공유"}
    if r.get("mutual_reception"):
        return {"grade": "mutual_major", "weight": 2.4, "label_ko": "상호 주요 리셉션"}
    if r.get("has_reception"):
        return {"grade": "one_way_major", "weight": 1.35, "label_ko": "한쪽 주요 리셉션"}
    return {"grade": "none", "weight": 0.0, "label_ko": "주요 리셉션 없음"}


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
            "reception_grade": {"grade": "shared", "weight": 0.8, "label_ko": "같은 주인행성 공유"},
        }
    reception = core._horary_reception(a_name, a_row, b_name, b_row)
    return {
        "label": label,
        "a": a_name,
        "b": b_name,
        "shared_ruler": False,
        "perfection": _balanced_perfection_candidate(a_name, a_row, b_name, b_row, dt_utc, timezone_name),
        "reception": reception,
        "reception_grade": _reception_grade(reception),
    }


def _aspect_tone(aspect_key):
    if aspect_key in {"conjunction", "sextile", "trine"}:
        return "supportive"
    if aspect_key in {"square", "opposition"}:
        return "frictional"
    return "neutral"


def _build_balance(data, timezone_name):
    sig = data.get("significators") or {}
    j = data.get("judgment_support") or {}
    primary = j.get("perfection") or {}
    reception = j.get("reception") or {}
    moon = j.get("moon_course") or {}

    q = sig.get("querent") or {}
    t = sig.get("quesited") or {}
    event = sig.get("event") or None
    dt_utc = datetime.fromisoformat(str(data["moment"]["utc_iso"]).replace("Z", "+00:00"))

    secondary = []
    if event:
        for row in (
            _pair_evidence(
                "querent_to_event",
                q.get("ruler"), q.get("planet"),
                event.get("ruler"), event.get("planet"),
                dt_utc, timezone_name,
            ),
            _pair_evidence(
                "quesited_to_event",
                t.get("ruler"), t.get("planet"),
                event.get("ruler"), event.get("planet"),
                dt_utc, timezone_name,
            ),
        ):
            if row:
                secondary.append(row)

    relevant = {q.get("ruler"), t.get("ruler")}
    if event:
        relevant.add(event.get("ruler"))
    relevant.discard(None)
    moon_relevant = [x for x in (moon.get("next_aspects") or []) if x.get("body") in relevant][:4]
    moon_soft = [x for x in moon_relevant if x.get("aspect") in {"conjunction", "sextile", "trine"}]
    moon_hard = [x for x in moon_relevant if x.get("aspect") in {"square", "opposition"}]

    shared_primary = bool(
        reception.get("same_significator")
        or primary.get("shared_ruler")
        or (q.get("ruler") and q.get("ruler") == t.get("ruler"))
    )
    reception_grade = _reception_grade(reception)

    event_perfections = [row for row in secondary if (row.get("perfection") or {}).get("perfects")]
    event_receptions = [row for row in secondary if (row.get("reception") or {}).get("has_reception")]

    primary_aspect = (primary.get("aspect") or {})
    primary_aspect_key = primary_aspect.get("aspect") or (j.get("primary_connection") or {}).get("aspect")
    primary_tone = _aspect_tone(primary_aspect_key)

    support = []
    constraints = []
    movement = []
    support_score = 0.0
    constraint_score = 0.0

    if primary.get("perfects"):
        if primary.get("reason") == "future_perfection_from_out_of_orb":
            support.append("현재 오브 밖에서 시작하지만 별자리 변경 전 직접 정확각이 완성됨")
        else:
            support.append("질문자와 대상 주인행성의 직접 정확각 성사")
        support_score += 4.0

    if reception_grade["grade"] == "mutual_major":
        support.append("질문자·대상 사이 상호 주요 리셉션")
        support_score += reception_grade["weight"]
    elif reception_grade["grade"] == "one_way_major":
        support.append("질문자·대상 사이 한쪽 주요 리셉션")
        support_score += reception_grade["weight"]

    if shared_primary:
        support.append("질문자와 대상이 같은 주인행성을 공유")
        support_score += 0.8

    if event_perfections:
        hard_event = any(
            _aspect_tone(((row.get("perfection") or {}).get("aspect") or {}).get("aspect")) == "frictional"
            for row in event_perfections
        )
        support.append("사건 보조 주인행성과의 정확각 연결" + ("(마찰 포함)" if hard_event else ""))
        support_score += 1.8
    elif event_receptions:
        support.append("사건 보조 주인행성과의 주요 리셉션")
        support_score += 0.9

    if moon_soft:
        movement.append("Moon(달)이 관련 주인행성으로 합/육십분위/삼분위 다음 적용각을 형성")
        support_score += 0.9
    if moon_hard:
        movement.append("Moon(달)이 관련 주인행성으로 사분위/충 다음 적용각을 형성 — 움직임은 있으나 마찰성")
        support_score += 0.35
        constraint_score += 0.65

    if primary.get("perfects") and primary_tone == "frictional":
        constraints.append("직접 정확각은 성사되지만 사분위/충이라 노력·마찰·조건이 큼")
        constraint_score += 1.5
    if primary.get("reason") == "sign_change_before_perfection":
        constraints.append("직접 정확각 완성 전 주인행성 별자리 변경")
        constraint_score += 3.0
    if moon.get("void_of_course"):
        constraints.append("Moon(달) 보이드 오브 코스 — 전개 동력이 약하거나 지연될 수 있음")
        constraint_score += 1.2

    potential_rows = [
        x for x in (j.get("potential_prohibition") or [])
        if x.get("classification") == "potential_only"
    ]
    if potential_rows:
        constraints.append("주 성사각보다 앞설 수 있는 잠재 개입각 후보(확정 prohibition 아님)")
        constraint_score += 0.55

    if primary.get("reason") in {"extended_horizon_no_perfection", "relative_motion_too_slow"}:
        constraints.append("직접 정확각은 현재 계산에서 확정되지 않음 — 자동 불성사 근거로는 사용하지 않음")
        constraint_score += 0.45

    if primary.get("perfects"):
        if primary_tone == "frictional":
            if reception_grade["grade"] == "mutual_major" or support_score >= 5.5:
                tier = "direct_friction_supported"
                headline = "직접 성사각이 있고 수용 근거도 있음 — 성사는 열려 있으나 과정의 마찰이 큼"
            else:
                tier = "direct_with_friction"
                headline = "직접 성사각은 확인됨 — 다만 사분위/충의 마찰·조건을 통과해야 함"
        elif reception_grade["grade"] == "mutual_major" or support_score >= 5.5:
            tier = "strong_support"
            headline = "직접 성사각과 보조 근거가 겹쳐 성사 쪽 증거가 강함"
        else:
            tier = "direct_support"
            headline = "주인행성 사이 직접 성사각이 확인됨"
    elif event_perfections and (reception_grade["weight"] > 0 or moon_relevant or shared_primary):
        tier = "secondary_support"
        headline = "직접각은 없지만 사건축·리셉션·달에서 보조 성사 근거가 겹침"
    elif event_perfections:
        tier = "secondary_support"
        headline = "직접각 대신 사건 보조축에서 실제 연결이 확인됨"
    elif shared_primary:
        tier = "shared_ruler_open"
        headline = "같은 주인행성 공유 — 단순 예/아니오보다 달·사건축으로 전개를 판단해야 함"
    elif reception_grade["weight"] > 0 or event_receptions or moon_relevant:
        tier = "mixed_support"
        headline = "직접 성사각은 없지만 수용·사건축·달의 움직임이 남아 있어 조건부로 열려 있음"
    elif primary.get("indeterminate"):
        tier = "open_indeterminate"
        headline = "직접 판정이 유보됨 — 현재 근거만으로 성사·불성사를 단정하기 어려움"
    elif primary.get("reason") == "sign_change_before_perfection":
        tier = "blocked_direct"
        headline = "직접 성사 흐름은 별자리 변경으로 끊김 — 보조 근거가 없다면 현재는 약한 편"
    else:
        tier = "weak_evidence"
        headline = "현재 차트의 성사 지지 근거가 약함 — ‘자동 NO’가 아니라 증거 부족에 가까움"

    return {
        "version": "LUNEA_HORARY_BALANCE_V3",
        "tier": tier,
        "headline_ko": headline,
        "supporting_evidence_ko": support,
        "movement_evidence_ko": movement,
        "constraints_ko": constraints,
        "support_score": round(support_score, 2),
        "constraint_score": round(constraint_score, 2),
        "score_note_ko": "점수는 확률이 아니라 근거의 상대적 강도 표시입니다.",
        "shared_primary_ruler": shared_primary,
        "primary_perfection": primary,
        "primary_aspect_tone": primary_tone,
        "reception_grade": reception_grade,
        "event_connections": secondary,
        "moon_relevant_next_aspects": moon_relevant,
        "potential_interventions": potential_rows,
        "interpretation_note_ko": (
            "현재 오브 안의 직접각만으로 예/아니오를 결정하지 않습니다. 별자리 변경 전 미래 정확각, "
            "리셉션 강도, 사건 보조축, Moon의 다음 적용각과 마찰성, 잠재 개입 후보를 분리해 평가합니다."
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
    balance = _build_balance(data, timezone_name)
    j["balance_v3"] = balance
    j["balance_v2"] = balance
    data.setdefault("meta", {})["horary_balance"] = "LUNEA_HORARY_BALANCE_V3"
    return data
