from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta

import astro_core as core
import horary_balance_v3 as v3


# LUNEA HORARY BALANCE V3.1
# -------------------------
# Additive traditional layer over V3:
# - Translation of Light
# - Collection of Light
# - Reception tiers through triplicity / Egyptian term / face
# - Confirmed computational patterns for prohibition / frustration / refranation
#
# Important boundary:
# These are deterministic chart-pattern classifications, not guarantees of
# real-world outcomes. Minor dignities are deliberately weighted below major
# domicile/exaltation reception so V3.1 does not manufacture optimism.

VERSION = "LUNEA_HORARY_BALANCE_V3_1"

# Dorothean triplicity rulers: day, night, participating.
TRIPLICITY_RULERS = {
    0: ("Sun", "Jupiter", "Saturn"),      # Fire
    1: ("Venus", "Moon", "Mars"),        # Earth
    2: ("Saturn", "Mercury", "Jupiter"), # Air
    3: ("Venus", "Mars", "Moon"),        # Water
}

# Egyptian bounds/terms. Each tuple is (end_degree_exclusive, ruler).
EGYPTIAN_TERMS = {
    0: ((6, "Jupiter"), (12, "Venus"), (20, "Mercury"), (25, "Mars"), (30, "Saturn")),
    1: ((8, "Venus"), (14, "Mercury"), (22, "Jupiter"), (27, "Saturn"), (30, "Mars")),
    2: ((6, "Mercury"), (12, "Jupiter"), (17, "Venus"), (24, "Mars"), (30, "Saturn")),
    3: ((7, "Mars"), (13, "Venus"), (19, "Mercury"), (26, "Jupiter"), (30, "Saturn")),
    4: ((6, "Jupiter"), (11, "Venus"), (18, "Saturn"), (24, "Mercury"), (30, "Mars")),
    5: ((7, "Mercury"), (17, "Venus"), (21, "Jupiter"), (28, "Mars"), (30, "Saturn")),
    6: ((6, "Saturn"), (14, "Mercury"), (21, "Jupiter"), (28, "Venus"), (30, "Mars")),
    7: ((7, "Mars"), (11, "Venus"), (19, "Mercury"), (24, "Jupiter"), (30, "Saturn")),
    8: ((12, "Jupiter"), (17, "Venus"), (21, "Mercury"), (26, "Saturn"), (30, "Mars")),
    9: ((7, "Mercury"), (14, "Jupiter"), (22, "Venus"), (26, "Saturn"), (30, "Mars")),
    10: ((7, "Mercury"), (13, "Venus"), (20, "Jupiter"), (25, "Mars"), (30, "Saturn")),
    11: ((12, "Venus"), (16, "Jupiter"), (19, "Mercury"), (28, "Mars"), (30, "Saturn")),
}

# Chaldean faces/decans, Aries 0° onward.
FACE_RULERS = {
    0: ("Mars", "Sun", "Venus"),
    1: ("Mercury", "Moon", "Saturn"),
    2: ("Jupiter", "Mars", "Sun"),
    3: ("Venus", "Mercury", "Moon"),
    4: ("Saturn", "Jupiter", "Mars"),
    5: ("Sun", "Venus", "Mercury"),
    6: ("Moon", "Saturn", "Jupiter"),
    7: ("Mars", "Sun", "Venus"),
    8: ("Mercury", "Moon", "Saturn"),
    9: ("Jupiter", "Mars", "Sun"),
    10: ("Venus", "Mercury", "Moon"),
    11: ("Saturn", "Jupiter", "Mars"),
}

DIGNITY_STRENGTH = {
    "domicile": 5,
    "exaltation": 4,
    "triplicity": 3,
    "term": 2,
    "face": 1,
}

DIGNITY_LABEL_KO = {
    "domicile": "도머사일",
    "exaltation": "고양",
    "triplicity": "트리플리시티",
    "term": "텀·바운드",
    "face": "페이스·데칸",
}


def _aspect_tone(key):
    return v3._aspect_tone(key)


def _is_day_chart(data):
    sun = (data.get("planets") or {}).get("Sun") or {}
    house = int(sun.get("house") or 0)
    return 7 <= house <= 12


def _term_ruler(sign_index, degree_in_sign):
    degree = max(0.0, min(29.999999, float(degree_in_sign)))
    for end, ruler in EGYPTIAN_TERMS[int(sign_index)]:
        if degree < float(end):
            return ruler
    return EGYPTIAN_TERMS[int(sign_index)][-1][1]


def _face_ruler(sign_index, degree_in_sign):
    decan = min(2, int(max(0.0, min(29.999999, float(degree_in_sign))) // 10.0))
    return FACE_RULERS[int(sign_index)][decan]


def _active_triplicity_ruler(sign_index, day_chart):
    rulers = TRIPLICITY_RULERS[int(sign_index) % 4]
    return rulers[0] if day_chart else rulers[1]


def _dignity_owners(row, day_chart):
    sign = int(row["sign_index"])
    degree = float(row["longitude"]) % 30.0
    return {
        "domicile": core.HORARY_RULER_BY_SIGN[sign],
        "exaltation": core.HORARY_EXALTATION_BY_SIGN[sign],
        "triplicity": _active_triplicity_ruler(sign, day_chart),
        "triplicity_participating": TRIPLICITY_RULERS[sign % 4][2],
        "term": _term_ruler(sign, degree),
        "face": _face_ruler(sign, degree),
    }


def _reception_side(guest_body, guest_row, receiver_body, day_chart):
    owners = _dignity_owners(guest_row, day_chart)
    dignities = [
        name for name in ("domicile", "exaltation", "triplicity", "term", "face")
        if owners.get(name) == receiver_body
    ]
    strongest = max((DIGNITY_STRENGTH[x] for x in dignities), default=0)
    points = sum(DIGNITY_STRENGTH[x] for x in dignities)
    return {
        "guest": guest_body,
        "receiver": receiver_body,
        "dignities": dignities,
        "dignities_ko": [DIGNITY_LABEL_KO[x] for x in dignities],
        "strongest": strongest,
        "points": points,
        "owners": owners,
    }


def _extended_reception(body_a, row_a, body_b, row_b, day_chart):
    if body_a == body_b:
        return {
            "a": body_a,
            "b": body_b,
            "same_significator": True,
            "grade": "shared",
            "weight": 0.8,
            "label_ko": "같은 주인행성 공유",
            "a_received_by_b": None,
            "b_received_by_a": None,
        }

    a_by_b = _reception_side(body_a, row_a, body_b, day_chart)
    b_by_a = _reception_side(body_b, row_b, body_a, day_chart)
    a_strength = int(a_by_b["strongest"])
    b_strength = int(b_by_a["strongest"])
    mutual = a_strength > 0 and b_strength > 0
    major_a = a_strength >= 4
    major_b = b_strength >= 4

    if major_a and major_b:
        grade, weight, label = "mutual_major", 2.4, "상호 주요 리셉션"
    elif mutual and (major_a or major_b):
        grade, weight, label = "mutual_mixed", 2.0, "상호 혼합 리셉션"
    elif mutual:
        grade, weight, label = "mutual_minor", 1.45, "상호 약식 리셉션"
    else:
        strongest = max(a_strength, b_strength)
        if strongest >= 4:
            grade, weight, label = "one_way_major", 1.35, "한쪽 주요 리셉션"
        elif strongest == 3:
            grade, weight, label = "one_way_triplicity", 0.75, "한쪽 트리플리시티 리셉션"
        elif strongest == 2:
            grade, weight, label = "one_way_term", 0.45, "한쪽 텀 리셉션"
        elif strongest == 1:
            grade, weight, label = "one_way_face", 0.25, "한쪽 페이스 리셉션"
        else:
            grade, weight, label = "none", 0.0, "리셉션 없음"

    # Multiple dignities on the same side modestly strengthen the testimony,
    # but never elevate minor dignity to major reception by itself.
    if weight and max(a_by_b["points"], b_by_a["points"]) >= 6:
        weight = min(2.6, weight + 0.15)

    return {
        "a": body_a,
        "b": body_b,
        "same_significator": False,
        "grade": grade,
        "weight": round(weight, 2),
        "label_ko": label,
        "mutual": mutual,
        "a_received_by_b": a_by_b,
        "b_received_by_a": b_by_a,
        # Compatibility: major flags keep their old meaning.
        "mutual_reception": bool(major_a and major_b),
        "has_reception": bool(major_a or major_b),
        "has_minor_reception": bool((a_strength or b_strength) and not (major_a or major_b)),
    }


def _eligible_future(perfection, current_state):
    if not (perfection or {}).get("perfects"):
        return False
    if float((perfection or {}).get("days_from_question") or 0.0) < -1e-6:
        return False
    return bool(
        (perfection or {}).get("started_within_orb")
        or (current_state or {}).get("phase") in {"applying", "exact"}
    )


def _translation_candidates(data, timezone_name):
    planets = data.get("planets") or {}
    sig = data.get("significators") or {}
    q = sig.get("querent") or {}
    t = sig.get("quesited") or {}
    qn, tn = q.get("ruler"), t.get("ruler")
    qr, tr = q.get("planet"), t.get("planet")
    if not qn or not tn or qn == tn or not qr or not tr:
        return []

    dt_utc = datetime.fromisoformat(str(data["moment"]["utc_iso"]).replace("Z", "+00:00"))
    q_speed = abs(float(qr.get("speed_deg_per_day") or 0.0))
    t_speed = abs(float(tr.get("speed_deg_per_day") or 0.0))
    rows = []

    for third, third_row in planets.items():
        if third not in core.HORARY_PLANETS or third in {qn, tn}:
            continue
        third_speed = abs(float(third_row.get("speed_deg_per_day") or 0.0))
        if third_speed <= max(q_speed, t_speed) + 0.02:
            continue

        state_q = core._horary_aspect_state(third, third_row, qn, qr)
        state_t = core._horary_aspect_state(third, third_row, tn, tr)
        possibilities = [
            (qn, qr, state_q, tn, tr, state_t),
            (tn, tr, state_t, qn, qr, state_q),
        ]
        for source_name, source_row, source_state, target_name, target_row, target_state in possibilities:
            if source_state.get("phase") != "separating":
                continue
            future = v3._balanced_perfection_candidate(
                third, third_row, target_name, target_row, dt_utc, timezone_name
            )
            if not _eligible_future(future, target_state):
                continue
            aspect_future = (future.get("aspect") or {}).get("aspect")
            hard = any(
                _aspect_tone(key) == "frictional"
                for key in (source_state.get("aspect"), aspect_future)
                if key
            )
            rows.append({
                "type": "translation_of_light",
                "translator": third,
                "translator_ko": core.PLANET_KO.get(third, third),
                "from": source_name,
                "from_ko": core.PLANET_KO.get(source_name, source_name),
                "to": target_name,
                "to_ko": core.PLANET_KO.get(target_name, target_name),
                "separating_aspect": source_state,
                "applying_perfection": future,
                "days_to_delivery": round(float(future.get("days_from_question") or 0.0), 4),
                "frictional": hard,
                "classification": "confirmed_pattern",
                "note_ko": "더 빠른 제3행성이 한 주인행성에서 분리된 뒤 다른 주인행성으로 적용해 빛을 전달하는 패턴입니다.",
            })

    rows.sort(key=lambda x: (x["days_to_delivery"], x["frictional"]))
    return rows[:4]


def _collection_candidates(data, timezone_name):
    planets = data.get("planets") or {}
    sig = data.get("significators") or {}
    q = sig.get("querent") or {}
    t = sig.get("quesited") or {}
    qn, tn = q.get("ruler"), t.get("ruler")
    qr, tr = q.get("planet"), t.get("planet")
    if not qn or not tn or qn == tn or not qr or not tr:
        return []

    dt_utc = datetime.fromisoformat(str(data["moment"]["utc_iso"]).replace("Z", "+00:00"))
    q_speed = abs(float(qr.get("speed_deg_per_day") or 0.0))
    t_speed = abs(float(tr.get("speed_deg_per_day") or 0.0))
    rows = []

    for third, third_row in planets.items():
        if third not in core.HORARY_PLANETS or third in {qn, tn}:
            continue
        third_speed = abs(float(third_row.get("speed_deg_per_day") or 0.0))
        if third_speed + 0.02 >= min(q_speed, t_speed):
            continue

        state_q = core._horary_aspect_state(qn, qr, third, third_row)
        state_t = core._horary_aspect_state(tn, tr, third, third_row)
        pq = v3._balanced_perfection_candidate(qn, qr, third, third_row, dt_utc, timezone_name)
        pt = v3._balanced_perfection_candidate(tn, tr, third, third_row, dt_utc, timezone_name)
        if not (_eligible_future(pq, state_q) and _eligible_future(pt, state_t)):
            continue

        dq = float(pq.get("days_from_question") or 0.0)
        dt = float(pt.get("days_from_question") or 0.0)
        if max(dq, dt) > 60.0:
            continue
        aq = ((pq.get("aspect") or {}).get("aspect"))
        at = ((pt.get("aspect") or {}).get("aspect"))
        hard = any(_aspect_tone(x) == "frictional" for x in (aq, at) if x)
        rows.append({
            "type": "collection_of_light",
            "collector": third,
            "collector_ko": core.PLANET_KO.get(third, third),
            "querent_perfection": pq,
            "quesited_perfection": pt,
            "days_to_querent_contact": round(dq, 4),
            "days_to_quesited_contact": round(dt, 4),
            "span_days": round(abs(dq - dt), 4),
            "frictional": hard,
            "classification": "confirmed_pattern",
            "note_ko": "두 주인행성이 모두 더 느린 제3행성으로 적용해 빛이 한 행성에 모이는 패턴입니다.",
        })

    rows.sort(key=lambda x: (max(x["days_to_querent_contact"], x["days_to_quesited_contact"]), x["frictional"]))
    return rows[:4]


def _main_applicant(qn, qr, tn, tr):
    q_speed = abs(float(qr.get("speed_deg_per_day") or 0.0))
    t_speed = abs(float(tr.get("speed_deg_per_day") or 0.0))
    if q_speed >= t_speed:
        return qn, qr, tn, tr
    return tn, tr, qn, qr


def _confirmed_interventions(data, timezone_name):
    sig = data.get("significators") or {}
    j = data.get("judgment_support") or {}
    main = j.get("perfection") or {}
    if not main.get("perfects"):
        return []
    main_days = float(main.get("days_from_question") or 0.0)
    if main_days <= 1e-6:
        return []

    q = sig.get("querent") or {}
    t = sig.get("quesited") or {}
    qn, tn = q.get("ruler"), t.get("ruler")
    qr, tr = q.get("planet"), t.get("planet")
    planets = data.get("planets") or {}
    if not qn or not tn or qn == tn or not qr or not tr:
        return []

    applicant_name, applicant_row, target_name, target_row = _main_applicant(qn, qr, tn, tr)
    applicant_speed = abs(float(applicant_row.get("speed_deg_per_day") or 0.0))
    target_speed = abs(float(target_row.get("speed_deg_per_day") or 0.0))
    dt_utc = datetime.fromisoformat(str(data["moment"]["utc_iso"]).replace("Z", "+00:00"))
    out = []

    for third, third_row in planets.items():
        if third not in core.HORARY_PLANETS or third in {qn, tn}:
            continue
        state = core._horary_aspect_state(third, third_row, target_name, target_row)
        p = v3._balanced_perfection_candidate(
            third, third_row, target_name, target_row, dt_utc, timezone_name
        )
        if not _eligible_future(p, state):
            continue
        days = float(p.get("days_from_question") or 0.0)
        if not (1e-6 < days < main_days - 1e-6):
            continue

        third_speed = abs(float(third_row.get("speed_deg_per_day") or 0.0))
        if third_speed > max(applicant_speed, target_speed) + 0.02:
            kind = "prohibition"
            note = "더 빠른 제3행성이 주 성사각보다 먼저 상대 주인행성에 정확각을 완성하는 금지 패턴입니다."
        elif target_speed > third_speed + 0.02:
            kind = "frustration"
            note = "주 성사각의 상대 주인행성이 먼저 제3행성과 정확각을 완성하는 좌절 패턴입니다."
        else:
            # Speeds too close: retain as reviewed intervention, not confirmed block.
            continue

        out.append({
            "type": kind,
            "classification": "confirmed_pattern",
            "intervening": third,
            "intervening_ko": core.PLANET_KO.get(third, third),
            "main_applicant": applicant_name,
            "main_target": target_name,
            "intervening_perfection": p,
            "days_before_main": round(main_days - days, 4),
            "note_ko": note,
        })

    out.sort(key=lambda x: (float((x.get("intervening_perfection") or {}).get("days_from_question") or 999.0), x["type"]))
    return out[:4]


def _direction_sign(speed):
    speed = float(speed)
    if speed > 0.002:
        return 1
    if speed < -0.002:
        return -1
    return 0


def _refranation_pattern(data):
    sig = data.get("significators") or {}
    j = data.get("judgment_support") or {}
    primary = j.get("perfection") or {}
    connection = j.get("primary_connection") or {}
    if primary.get("perfects") or connection.get("phase") != "applying":
        return None

    q = sig.get("querent") or {}
    t = sig.get("quesited") or {}
    qn, tn = q.get("ruler"), t.get("ruler")
    qr, tr = q.get("planet"), t.get("planet")
    if not qn or not tn or qn == tn or not qr or not tr:
        return None

    rel = float(connection.get("relative_speed_deg_per_day") or 0.0)
    orb = float(connection.get("orb") or 0.0)
    rough_days = orb / rel if rel > 0.005 else 20.0
    horizon = max(2.0, min(30.0, rough_days * 1.8 + 2.0))
    start = datetime.fromisoformat(str(data["moment"]["utc_iso"]).replace("Z", "+00:00"))

    for body, row in ((qn, qr), (tn, tr)):
        start_sign = _direction_sign(row.get("speed_deg_per_day") or 0.0)
        if start_sign == 0:
            continue
        step_hours = 6 if body in {"Moon", "Mercury"} else 12
        steps = max(1, int(horizon * 24 / step_hours))
        for i in range(1, steps + 1):
            dt = start + timedelta(hours=i * step_hours)
            try:
                _, speed, direction = core.planet_motion(body, dt)
            except Exception:
                continue
            sign = _direction_sign(speed)
            if sign == 0 or sign != start_sign:
                return {
                    "type": "refranation",
                    "classification": "confirmed_pattern",
                    "body": body,
                    "body_ko": core.PLANET_KO.get(body, body),
                    "station_utc": dt.isoformat(),
                    "days_from_question": round((dt - start).total_seconds() / 86400.0, 4),
                    "direction_after": direction,
                    "note_ko": "적용 중이던 주인행성이 정확각 완성 전에 정지·역행 전환해 적용에서 물러나는 refranation 패턴입니다.",
                }
    return None


def _append_once(rows, text):
    if text not in rows:
        rows.append(text)


def _build_balance_v31(data, timezone_name):
    j = data.get("judgment_support") or {}
    base = deepcopy(j.get("balance_v3") or v3._build_balance(data, timezone_name))
    sig = data.get("significators") or {}
    q = sig.get("querent") or {}
    t = sig.get("quesited") or {}
    qn, tn = q.get("ruler"), t.get("ruler")
    qr, tr = q.get("planet"), t.get("planet")
    day_chart = _is_day_chart(data)

    reception = (
        _extended_reception(qn, qr, tn, tr, day_chart)
        if qn and tn and qr and tr else {"grade": "none", "weight": 0.0, "label_ko": "리셉션 없음"}
    )
    translations = _translation_candidates(data, timezone_name)
    collections = _collection_candidates(data, timezone_name)
    interventions = _confirmed_interventions(data, timezone_name)
    refranation = _refranation_pattern(data)

    support = list(base.get("supporting_evidence_ko") or [])
    movement = list(base.get("movement_evidence_ko") or [])
    constraints = list(base.get("constraints_ko") or [])
    support_score = float(base.get("support_score") or 0.0)
    constraint_score = float(base.get("constraint_score") or 0.0)

    old_reception_weight = float((base.get("reception_grade") or {}).get("weight") or 0.0)
    reception_delta = max(0.0, float(reception.get("weight") or 0.0) - old_reception_weight)
    if reception.get("grade") in {"mutual_mixed", "mutual_minor"}:
        _append_once(support, reception["label_ko"] + " — major만 보던 V3에서 놓치던 약식 상호 수용")
    elif reception.get("grade") in {"one_way_triplicity", "one_way_term", "one_way_face"}:
        _append_once(support, reception["label_ko"] + " — 약한 수용 근거로만 반영")
    support_score += reception_delta

    indirect = []
    if translations:
        best = translations[0]
        indirect.append(best)
        _append_once(support, "Translation of Light(빛의 전달) 간접 성사 패턴 확인")
        support_score += 2.2 if not best.get("frictional") else 1.55
        if best.get("frictional"):
            _append_once(constraints, "빛의 전달은 확인되지만 사분위/충이 포함돼 간접 성사 과정에 마찰이 큼")
            constraint_score += 0.6
    if collections:
        best = collections[0]
        indirect.append(best)
        _append_once(support, "Collection of Light(빛의 수집) 간접 성사 패턴 확인")
        support_score += 2.0 if not best.get("frictional") else 1.4
        if best.get("frictional"):
            _append_once(constraints, "빛의 수집은 확인되지만 사분위/충이 포함돼 조정 비용이 큼")
            constraint_score += 0.6

    if interventions:
        kinds = {x.get("type") for x in interventions}
        if "prohibition" in kinds:
            _append_once(constraints, "확정 규칙에 맞는 Prohibition(금지) 선행 패턴 확인")
        if "frustration" in kinds:
            _append_once(constraints, "확정 규칙에 맞는 Frustration(좌절) 선행 패턴 확인")
        constraint_score += 2.6
    if refranation:
        _append_once(constraints, "Refranation(적용 철회): 정확각 전 정지·역행 전환 패턴 확인")
        constraint_score += 3.0

    primary = j.get("perfection") or {}
    primary_tone = base.get("primary_aspect_tone") or "neutral"
    has_indirect = bool(indirect)
    has_obstruction = bool(interventions or refranation)

    if primary.get("perfects") and has_obstruction:
        tier = "direct_obstructed"
        headline = "직접 성사각은 있으나 그보다 앞선 실제 방해 패턴이 확인됨 — 성사는 열려 있어도 지연·조건 변경 위험이 큼"
    elif not primary.get("perfects") and refranation:
        tier = "refranated"
        headline = "직접 적용 흐름이 정확각 전에 철회됨 — 현재 직접 성사는 약하지만 다른 간접 연결 여부를 함께 봐야 함"
    elif not primary.get("perfects") and has_indirect:
        friction = any(x.get("frictional") for x in indirect)
        if friction:
            tier = "indirect_friction_supported"
            headline = "직접각은 없지만 빛의 전달·수집으로 간접 성사 구조가 확인됨 — 다만 마찰성 조건이 큼"
        else:
            tier = "indirect_support"
            headline = "직접각은 없지만 Translation/Collection으로 간접 성사 구조가 확인됨"
    elif primary.get("perfects") and primary_tone == "frictional" and reception.get("grade") in {"mutual_mixed", "mutual_minor"}:
        tier = "direct_friction_supported"
        headline = "직접 성사각에 상호 수용이 더해짐 — 과정은 거칠어도 성사 근거는 유지됨"
    else:
        tier = base.get("tier") or "weak_evidence"
        headline = base.get("headline_ko") or "현재 근거를 종합해 판단합니다."

    return {
        **base,
        "version": VERSION,
        "tier": tier,
        "headline_ko": headline,
        "supporting_evidence_ko": support,
        "movement_evidence_ko": movement,
        "constraints_ko": constraints,
        "support_score": round(support_score, 2),
        "constraint_score": round(constraint_score, 2),
        "reception_v31": reception,
        "indirect_perfection": {
            "translation_of_light": translations,
            "collection_of_light": collections,
            "best": indirect,
        },
        "confirmed_obstructions": {
            "prohibition_or_frustration": interventions,
            "refranation": refranation,
        },
        "interpretation_note_ko": (
            "V3의 직접 미래 성사각을 유지하면서 Translation/Collection, domicile·exaltation·triplicity·term·face 리셉션, "
            "그리고 potential-only 개입각과 구분된 prohibition/frustration/refranation 패턴을 별도로 평가합니다. "
            "약한 dignities와 간접 연결은 직접 성사각보다 낮은 가중치로 반영합니다."
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
    data = v3.compute_horary(
        question_text=question_text,
        question_iso=question_iso,
        topic=topic,
        timezone_name=timezone_name,
        place=place,
        lat=lat,
        lon=lon,
    )
    j = data.setdefault("judgment_support", {})
    balance31 = _build_balance_v31(data, timezone_name)
    j["balance_v31"] = balance31
    # Keep V3 untouched for explicit regression comparison during rollout.
    data.setdefault("meta", {})["horary_balance"] = VERSION
    data["meta"]["horary_balance_v3_compat"] = True
    return data
