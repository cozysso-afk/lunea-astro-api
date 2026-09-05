from __future__ import annotations

from copy import deepcopy

import astro_core as core
import horary_balance_v31 as v31
import horary_engine_v6 as v6


# LUNEA HORARY ENGINE V7
# ----------------------
# Bias/interpretation hardening over Strict V6:
# - minor essential dignities are surfaced so a planet is not called peregrine
#   when it actually holds triplicity / term / face dignity
# - Moon motion is separated from question-relevant Moon testimony
# - direct perfection with a confirmed obstruction is qualified, never silently
#   flattened into either automatic YES or automatic NO
# - route/debug metadata exposes the selected radical/derived house contract

VERSION = "LUNEA_HORARY_ENGINE_V7_BALANCE_GUARDS"
_ORIGINAL_COMPUTE_HORARY = v31.compute_horary

DIGNITY_ORDER = ("domicile", "exaltation", "triplicity", "term", "face")
DIGNITY_LABEL_KO = {
    "domicile": "도머사일",
    "exaltation": "고양",
    "triplicity": "트리플리시티",
    "term": "텀·바운드",
    "face": "페이스·데칸",
}
DIGNITY_POINTS = {
    "domicile": 5,
    "exaltation": 4,
    "triplicity": 3,
    "term": 2,
    "face": 1,
}
DEBILITY_POINTS = {"detriment": -5, "fall": -4}


def _essential_profile(body: str, row: dict, day_chart: bool) -> dict:
    owners = v31._dignity_owners(row, day_chart)
    held = [name for name in DIGNITY_ORDER if owners.get(name) == body]
    original = str(row.get("dignity") or "peregrine")
    debilities = [original] if original in DEBILITY_POINTS else []
    score = sum(DIGNITY_POINTS[x] for x in held) + sum(DEBILITY_POINTS[x] for x in debilities)

    if held:
        held_ko = [DIGNITY_LABEL_KO[x] for x in held]
        label_ko = "본질적 존귀 · " + " + ".join(held_ko)
        classification = "major_dignity" if held[0] in {"domicile", "exaltation"} else "minor_dignity"
    elif debilities:
        label_ko = row.get("dignity_ko") or ("손상 · 디트리먼트" if original == "detriment" else "손상 · 추락")
        classification = "debility"
    else:
        held_ko = []
        label_ko = "무권위·페레그린"
        classification = "peregrine"

    return {
        "body": body,
        "body_ko": core.PLANET_KO.get(body, body),
        "classification": classification,
        "held_dignities": held,
        "held_dignities_ko": [DIGNITY_LABEL_KO[x] for x in held],
        "debilities": debilities,
        "score": score,
        "label_ko": label_ko,
        "owners": owners,
        "note_ko": "존귀/손상은 행동능력과 상태의 질을 설명하며 Perfection(성사각)을 대체하지 않습니다.",
    }


def _enrich_dignities(data: dict) -> dict:
    planets = data.get("planets") or {}
    day_chart = bool(v31._is_day_chart(data))
    profiles = {}
    for body in core.HORARY_PLANETS:
        row = planets.get(body)
        if not isinstance(row, dict):
            continue
        profile = _essential_profile(body, row, day_chart)
        profiles[body] = profile
        row["essential_dignity_v7"] = profile
        row["dignity_effective"] = profile["classification"]
        row["dignity_ko_original"] = row.get("dignity_ko")
        # Prevent the UI/AI raw chart from calling a planet peregrine when it
        # actually has triplicity/term/face dignity. Machine-level legacy
        # `dignity` is preserved for compatibility.
        if profile["held_dignities"] and str(row.get("dignity")) == "peregrine":
            row["dignity_ko"] = profile["label_ko"]
    data.setdefault("judgment_support", {})["essential_dignities_v7"] = profiles
    return profiles


def _relevant_roles(data: dict) -> dict[str, list[str]]:
    sig = data.get("significators") or {}
    roles: dict[str, list[str]] = {}
    for key, label in (("querent", "질문자"), ("quesited", "대상"), ("event", "파생 사건")):
        row = sig.get(key) or {}
        ruler = row.get("ruler")
        if ruler:
            roles.setdefault(ruler, []).append(label)
    return roles


def _moon_relevance(data: dict) -> dict:
    j = data.get("judgment_support") or {}
    moon = j.get("moon_course") or {}
    roles = _relevant_roles(data)
    next_row = moon.get("next_major_applying_aspect") or None

    if moon.get("void_of_course"):
        return {
            "status": "voc",
            "question_relevant": False,
            "movement_present": False,
            "label_ko": "없음 · VOC",
            "relevant_rulers": roles,
            "next_aspect": None,
        }
    if not next_row:
        return {
            "status": "no_next_major",
            "question_relevant": False,
            "movement_present": False,
            "label_ko": "다음 주요 적용각 확인 안 됨",
            "relevant_rulers": roles,
            "next_aspect": None,
        }

    body = next_row.get("body")
    aspect = next_row.get("aspect")
    tone = v31._aspect_tone(aspect) if aspect else "neutral"
    relevant = body in roles
    if relevant:
        if tone == "frictional":
            label = f"질문축 적용각 있음 · {core.PLANET_KO.get(body, body)} · 마찰성"
            status = "relevant_frictional"
        else:
            label = f"질문축 적용각 있음 · {core.PLANET_KO.get(body, body)} · 지원/연결성"
            status = "relevant_supportive"
    else:
        label = "Moon 진행은 있으나 질문자·대상·사건 주인행성과 직접 연결되지 않음"
        status = "movement_only"

    return {
        "status": status,
        "question_relevant": relevant,
        "movement_present": True,
        "tone": tone,
        "label_ko": label,
        "relevant_rulers": roles,
        "next_aspect": next_row,
        "note_ko": "VOC가 아니라는 사실 자체를 질문 관련 지원으로 간주하지 않습니다.",
    }


def _confirmed_obstructions(core_v6: dict) -> list[dict]:
    interventions = core_v6.get("interventions") or {}
    rows = [
        row for row in (interventions.get("prohibition_or_frustration") or [])
        if (row or {}).get("classification") == "confirmed_pattern"
    ]
    refranation = interventions.get("refranation")
    if refranation and refranation.get("classification") == "confirmed_pattern":
        rows.append(refranation)
    return rows


def _qualify_core(data: dict, moon_rel: dict) -> dict:
    j = data.get("judgment_support") or {}
    core_v6 = j.get("traditional_core_v6") or {}
    if not core_v6:
        return {}

    direct = core_v6.get("direct_axis") or {}
    p = direct.get("perfection") or j.get("perfection") or {}
    state = direct.get("aspect_state") or p.get("aspect") or j.get("primary_connection") or {}
    direct_perfects = bool(p.get("perfects"))
    obstruction_rows = _confirmed_obstructions(core_v6)
    obstruction_present = bool(obstruction_rows)
    aspect_key = state.get("traditional_valid_aspect") or state.get("aspect")
    aspect_tone = v31._aspect_tone(aspect_key) if aspect_key else None

    raw_grade = core_v6.get("evidence_grade") or "NONE"
    if direct_perfects and obstruction_present:
        qualified = "A_WITH_CONFIRMED_OBSTRUCTION"
        qualified_ko = "A등급 직접 성사 + 확인된 선행 방해"
    elif direct_perfects and aspect_tone == "frictional":
        qualified = "A_FRICTIONAL"
        qualified_ko = "A등급 직접 성사 · 마찰성 각"
    elif direct_perfects:
        qualified = "A_CLEAR"
        qualified_ko = "A등급 직접 성사 · 확인된 선행 방해 없음"
    else:
        qualified = raw_grade
        qualified_ko = core_v6.get("evidence_grade_ko") or raw_grade

    staged = deepcopy(core_v6.get("staged_judgment") or {})
    staged["moon_support"] = moon_rel.get("label_ko")
    staged["qualified_evidence"] = qualified_ko

    if direct_perfects and obstruction_present:
        staged["direct_perfection"] = "있음 · 단, 확인된 선행 방해 별도"
        staged["overall_ko"] = (
            "주 시그니피케이터 간 유효 적용 성사각은 존재하지만, 그보다 앞서거나 성사를 교란하는 "
            "확인된 방해 패턴이 있어 단순 YES로 압축하지 않습니다. 직접 성사 사실과 방해 사실을 함께 봅니다."
        )
    elif direct_perfects and aspect_tone == "frictional":
        staged["direct_perfection"] = "있음 · 마찰성 각"
        staged["overall_ko"] = (
            "주 시그니피케이터 간 직접 성사는 확인됩니다. 다만 사분위/충 같은 마찰성 각이면 "
            "과정의 난도·충돌을 함께 읽어야 하며, 어려운 각이라는 이유만으로 자동 NO로 바꾸지 않습니다."
        )
    elif direct_perfects:
        staged["direct_perfection"] = "있음"
        staged["overall_ko"] = "주 시그니피케이터 간 유효 적용 성사각이 확인됩니다."

    core_v6["moon_relevance_v7"] = moon_rel
    core_v6["confirmed_obstruction_count_v7"] = len(obstruction_rows)
    core_v6["confirmed_obstructions_v7"] = obstruction_rows
    core_v6["qualified_evidence_grade_v7"] = qualified
    core_v6["qualified_evidence_grade_ko_v7"] = qualified_ko
    core_v6["direct_aspect_tone_v7"] = aspect_tone
    core_v6["staged_judgment"] = staged
    return core_v6


def _route_contract(data: dict) -> dict:
    q = data.get("question") or {}
    topic = str(q.get("topic") or "general")
    spec = core.HORARY_TOPIC_SPECS.get(topic, core.HORARY_TOPIC_SPECS.get("general", {}))
    sig = data.get("significators") or {}
    return {
        "topic": topic,
        "label_ko": spec.get("label_ko"),
        "quesited_house_expected": spec.get("quesited_house"),
        "event_house_expected": spec.get("event_house"),
        "quesited_house_actual": (sig.get("quesited") or {}).get("house"),
        "event_house_actual": (sig.get("event") or {}).get("house") if sig.get("event") else None,
        "matches_spec": (
            (sig.get("quesited") or {}).get("house") == spec.get("quesited_house")
            and ((sig.get("event") or {}).get("house") if sig.get("event") else None) == spec.get("event_house")
        ),
    }


def _postprocess(data: dict) -> dict:
    if not isinstance(data, dict) or data.get("schema") != "LUNEA_HORARY_V1":
        return data

    _enrich_dignities(data)
    moon_rel = _moon_relevance(data)
    core_v6 = _qualify_core(data, moon_rel)
    route = _route_contract(data)

    j = data.setdefault("judgment_support", {})
    j["moon_relevance_v7"] = moon_rel
    j["route_contract_v7"] = route
    j["bias_guard_v7"] = {
        "direct_perfection_can_be_positive": True,
        "hard_aspect_is_not_automatic_no": True,
        "voc_is_not_automatic_no": True,
        "dignity_is_not_event_yes_no": True,
        "reception_is_not_perfection": True,
        "moon_movement_is_not_automatically_question_support": True,
    }
    if core_v6:
        j["traditional_core_v7"] = deepcopy(core_v6)
        j["traditional_core_v7"]["version"] = VERSION

    meta = data.setdefault("meta", {})
    meta["horary_engine"] = VERSION
    meta["bias_guard"] = "positive/negative/separating reachability protected by V7 regression sentinels"
    return data


def _compute_horary_v7(*args, **kwargs):
    return _postprocess(_ORIGINAL_COMPUTE_HORARY(*args, **kwargs))


if not getattr(v31.compute_horary, "_lunea_engine_v7", False):
    _compute_horary_v7._lunea_engine_v7 = True
    v31.compute_horary = _compute_horary_v7
