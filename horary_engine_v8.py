from __future__ import annotations

from copy import deepcopy

import astro_core as core
import horary_balance_v31 as v31
import horary_engine_v7 as v7


# LUNEA HORARY ENGINE V8
# ----------------------
# Judgment-hierarchy calibration after the V1/V2 bias audits.
#
# Goals:
# - keep V6/V7 direct, derived-event, Translation/Collection and obstruction
#   calculations authoritative
# - stop treating every non-perfection chart as a single undifferentiated
#   negative state
# - recognize the Moon as a traditional co-significator only when its actual
#   next major applying aspect reaches the quesited ruler or routed event ruler
# - keep reception as intention/receptivity testimony, never as a substitute
#   for event perfection
# - expose question-specific action/intention states for interpretation layers
#
# This does NOT target a chosen positive/negative percentage. It adds a missing
# evidence distinction while preserving the existing A/B/C/D/NONE hierarchy.

VERSION = "LUNEA_HORARY_ENGINE_V8_JUDGMENT_HIERARCHY"
_ORIGINAL_COMPUTE_HORARY = v31.compute_horary


def _band(value) -> str:
    text = str(value or "NONE")
    if text.startswith("A"):
        return "A"
    if text.startswith("B"):
        return "B"
    if text.startswith("C"):
        return "C"
    if text.startswith("D"):
        return "D"
    return "NONE"


def _reception_state(core_v7: dict) -> dict:
    direct = core_v7.get("direct_axis") or {}
    reception = direct.get("reception") or {}
    grade = str(reception.get("grade") or "none")
    if grade in {"mutual_major", "mutual_mixed"}:
        state = "mutual_strong"
        label = "상호 수용성 강함"
    elif grade == "mutual_minor":
        state = "mutual_minor"
        label = "상호 수용성은 있으나 약식"
    elif grade.startswith("one_way_"):
        state = "one_way"
        label = "한쪽 수용성"
    elif reception.get("same_significator"):
        state = "shared_ruler"
        label = "같은 주인행성 공유"
    else:
        state = "none"
        label = "유의미한 리셉션 없음"
    return {
        "state": state,
        "label_ko": label,
        "grade": grade,
        "weight": reception.get("weight"),
        "raw": reception,
    }


def _event_axis_state(core_v7: dict) -> dict:
    rows = core_v7.get("derived_event_axes") or {}
    perfected = []
    receptive = []
    for key, row in rows.items():
        row = row or {}
        if bool((row.get("perfection") or {}).get("perfects")):
            perfected.append(key)
        reception = row.get("reception") or {}
        if str(reception.get("grade") or "none") != "none" or reception.get("has_reception") or reception.get("has_minor_reception"):
            receptive.append(key)
    return {
        "perfected_axes": perfected,
        "receptive_axes": receptive,
        "has_perfection": bool(perfected),
        "has_reception": bool(receptive),
    }


def _indirect_state(core_v7: dict) -> dict:
    indirect = core_v7.get("indirect_perfection") or {}
    translations = [x for x in (indirect.get("translation_of_light") or []) if (x or {}).get("classification") in {None, "confirmed_pattern"}]
    collections = [x for x in (indirect.get("collection_of_light") or []) if (x or {}).get("classification") in {None, "confirmed_pattern"}]
    return {
        "translation_count": len(translations),
        "collection_count": len(collections),
        "present": bool(translations or collections),
    }


def _moon_event_testimony(data: dict, core_v7: dict) -> dict:
    j = data.get("judgment_support") or {}
    moon = j.get("moon_relevance_v7") or core_v7.get("moon_relevance_v7") or {}
    next_aspect = moon.get("next_aspect") or {}
    body = next_aspect.get("body")
    aspect = next_aspect.get("aspect")
    tone = moon.get("tone") or (v31._aspect_tone(aspect) if aspect else None)

    sig = data.get("significators") or {}
    querent = sig.get("querent") or {}
    quesited = sig.get("quesited") or {}
    event = sig.get("event") or {}
    q_ruler = querent.get("ruler")
    t_ruler = quesited.get("ruler")
    e_ruler = event.get("ruler") if event else None

    target_role = None
    if body and t_ruler and body == t_ruler:
        target_role = "quesited"
    elif body and e_ruler and body == e_ruler:
        target_role = "event"
    elif body and q_ruler and body == q_ruler:
        target_role = "querent"

    confirmed = bool(
        moon.get("question_relevant")
        and body
        and target_role in {"quesited", "event"}
        and aspect in core.HORARY_ASPECTS
        and moon.get("status") in {"relevant_supportive", "relevant_frictional"}
    )

    if not confirmed:
        if target_role == "querent":
            reason = "moon_applies_to_querent_only"
            label = "Moon의 다음 적용각이 질문자 주인행성으로 향해 사건 상대/사건축 성사 근거로 승격하지 않음"
        elif moon.get("question_relevant"):
            reason = "question_relevant_but_not_event_target"
            label = "Moon 진행은 질문 관련성이 있으나 대상/사건 주인행성 성사 근거는 아님"
        else:
            reason = "not_question_relevant"
            label = "Moon의 다음 적용각이 질문 사건축과 직접 연결되지 않음"
        return {
            "confirmed": False,
            "target_role": target_role,
            "body": body,
            "aspect": aspect,
            "tone": tone,
            "reason": reason,
            "label_ko": label,
            "raw": moon,
        }

    role_ko = "대상 주인행성" if target_role == "quesited" else "파생 사건 주인행성"
    friction = tone == "frictional"
    return {
        "confirmed": True,
        "target_role": target_role,
        "body": body,
        "aspect": aspect,
        "tone": tone,
        "reason": "moon_co_significator_applies_to_event_target",
        "label_ko": f"Moon 공동 시그니피케이터가 {role_ko}으로 실제 다음 주요 적용각을 형성" + (" · 마찰성" if friction else ""),
        "raw": moon,
    }


def _topic_action_state(topic: str, band: str, event_axes: dict, moon_event: dict) -> dict:
    if band == "A":
        return {"state": "direct_perfection", "label_ko": "주 시그니피케이터 직접 성사 근거 있음"}
    if band == "B":
        return {"state": "indirect_perfection", "label_ko": "Translation/Collection 간접 성사 근거 있음"}
    if event_axes.get("has_perfection"):
        if topic == "contact":
            return {"state": "contact_event_perfection", "label_ko": "연락 파생 사건축의 실제 성사 근거 있음"}
        if topic == "reconciliation":
            return {"state": "reconciliation_event_perfection", "label_ko": "재회 보조 사건축의 실제 성사 근거 있음"}
        return {"state": "derived_event_perfection", "label_ko": "파생 사건축의 실제 성사 근거 있음"}
    if moon_event.get("confirmed"):
        if topic == "contact":
            return {"state": "lunar_contact_testimony", "label_ko": "Moon 공동 시그니피케이터가 연락 대상/사건축으로 적용"}
        if topic == "reconciliation":
            return {"state": "lunar_reconciliation_testimony", "label_ko": "Moon 공동 시그니피케이터가 재회 대상/사건축으로 적용"}
        return {"state": "lunar_event_testimony", "label_ko": "Moon 공동 시그니피케이터의 사건축 적용 근거 있음"}
    return {"state": "not_perfected", "label_ko": "확인된 사건 성사각 없음"}


def _judgment_v8(data: dict, core_v7: dict) -> dict:
    topic = str((data.get("question") or {}).get("topic") or "general")
    legacy_grade = core_v7.get("qualified_evidence_grade_v7") or core_v7.get("evidence_grade") or "NONE"
    legacy_band = _band(legacy_grade)
    reception = _reception_state(core_v7)
    event_axes = _event_axis_state(core_v7)
    indirect = _indirect_state(core_v7)
    moon_event = _moon_event_testimony(data, core_v7)
    obstruction_count = int(core_v7.get("confirmed_obstruction_count_v7") or 0)

    grade = legacy_grade
    grade_ko = core_v7.get("qualified_evidence_grade_ko_v7") or core_v7.get("evidence_grade_ko") or str(legacy_grade)
    source = "v7_preserved"

    # Missing layer found by Bias Audit V2: V7 reports Moon relevance but never
    # lets a genuine Moon-to-quesited/event application enter the event-evidence
    # hierarchy. V8 adds that narrowly as a C-level co-significator testimony.
    if legacy_band in {"D", "NONE"} and moon_event.get("confirmed"):
        suffix = "FRICTIONAL" if moon_event.get("tone") == "frictional" else "CLEAR"
        role = "EVENT" if moon_event.get("target_role") == "event" else "TARGET"
        grade = f"C_MOON_{role}_{suffix}"
        grade_ko = "C등급 · Moon 공동 시그니피케이터의 사건축 적용" + (" · 마찰성" if suffix == "FRICTIONAL" else "")
        source = "moon_co_significator_event_testimony"

    band = _band(grade)
    action = _topic_action_state(topic, band, event_axes, moon_event)

    if band in {"A", "B", "C"}:
        overall_state = "event_supported"
        overall_ko = "사건 성사 쪽에 실제 적용/성사 근거가 있음"
    elif reception["state"] in {"mutual_strong", "mutual_minor", "one_way", "shared_ruler"}:
        overall_state = "receptive_but_unperfected"
        overall_ko = "수용성·의향 근거는 있으나 사건 성사각은 확인되지 않음"
    else:
        overall_state = "insufficient_event_evidence"
        overall_ko = "현재 차트에서 사건 성사를 뒷받침할 적용 근거가 충분하지 않음"

    if obstruction_count and band in {"A", "B", "C"}:
        overall_state = "event_supported_with_obstruction"
        overall_ko += " · 확인된 선행 방해 별도"

    return {
        "version": VERSION,
        "topic": topic,
        "legacy_grade_v7": legacy_grade,
        "legacy_band_v7": legacy_band,
        "qualified_evidence_grade_v8": grade,
        "qualified_evidence_grade_ko_v8": grade_ko,
        "grade_band_v8": band,
        "grade_source_v8": source,
        "overall_state_v8": overall_state,
        "overall_ko_v8": overall_ko,
        "action_state_v8": action,
        "intention_reception_v8": reception,
        "event_axes_v8": event_axes,
        "indirect_v8": indirect,
        "moon_event_testimony_v8": moon_event,
        "confirmed_obstruction_count_v8": obstruction_count,
        "interpretation_contract_v8": {
            "d_is_not_automatic_no": True,
            "reception_is_intention_not_event": True,
            "moon_to_querent_only_is_not_event_perfection": True,
            "moon_to_quesited_or_event_can_be_c_level_testimony": True,
            "direct_and_indirect_perfection_keep_priority": True,
            "no_target_positive_ratio": True,
        },
    }


def _postprocess(data: dict) -> dict:
    if not isinstance(data, dict) or data.get("schema") != "LUNEA_HORARY_V1":
        return data

    j = data.setdefault("judgment_support", {})
    core_v7 = j.get("traditional_core_v7") or j.get("traditional_core_v6") or {}
    if not core_v7:
        return data

    hierarchy = _judgment_v8(data, core_v7)
    core_v8 = deepcopy(core_v7)
    core_v8["version"] = VERSION
    core_v8["qualified_evidence_grade_v8"] = hierarchy["qualified_evidence_grade_v8"]
    core_v8["qualified_evidence_grade_ko_v8"] = hierarchy["qualified_evidence_grade_ko_v8"]
    core_v8["grade_band_v8"] = hierarchy["grade_band_v8"]
    core_v8["overall_state_v8"] = hierarchy["overall_state_v8"]
    core_v8["overall_ko_v8"] = hierarchy["overall_ko_v8"]
    core_v8["action_state_v8"] = hierarchy["action_state_v8"]
    core_v8["intention_reception_v8"] = hierarchy["intention_reception_v8"]
    core_v8["moon_event_testimony_v8"] = hierarchy["moon_event_testimony_v8"]
    core_v8["interpretation_contract_v8"] = hierarchy["interpretation_contract_v8"]

    staged = deepcopy(core_v8.get("staged_judgment") or {})
    staged["qualified_evidence_v8"] = hierarchy["qualified_evidence_grade_ko_v8"]
    staged["action_state_v8"] = hierarchy["action_state_v8"]["label_ko"]
    staged["intention_state_v8"] = hierarchy["intention_reception_v8"]["label_ko"]
    staged["overall_ko_v8"] = hierarchy["overall_ko_v8"]
    core_v8["staged_judgment"] = staged

    j["judgment_hierarchy_v8"] = hierarchy
    j["traditional_core_v8"] = core_v8
    j["bias_guard_v8"] = {
        "preserves_v7_direct_indirect_derived_priority": True,
        "promotes_only_confirmed_moon_event_target_application": True,
        "reception_only_remains_unperfected": True,
        "d_state_must_not_be_worded_as_automatic_no": True,
    }

    # V8 is a judgment layer over the V7 calculation engine. Keep the existing
    # calculation-engine identity for compatibility and expose V8 separately.
    meta = data.setdefault("meta", {})
    meta["judgment_hierarchy"] = VERSION
    return data


def _compute_horary_v8(*args, **kwargs):
    return _postprocess(_ORIGINAL_COMPUTE_HORARY(*args, **kwargs))


if not getattr(v31.compute_horary, "_lunea_engine_v8", False):
    _compute_horary_v8._lunea_engine_v8 = True
    v31.compute_horary = _compute_horary_v8
