from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional

from cross_interpretation_v2 import (
    SCHEMA,
    _cross_summary,
    _fact,
    _prashna_summary,
    build_cross_interpretation as _build_v8_cross,
)


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _v5_horary_summary(horary: dict) -> dict:
    support = _as_dict(horary.get("judgment_support"))
    balance = _as_dict(support.get("balance_v31") or support.get("balance_v3"))
    primary = _as_dict(support.get("perfection"))
    reception = _as_dict(balance.get("reception_v31") or support.get("reception"))
    indirect = _as_dict(balance.get("indirect_perfection"))
    obstructions = _as_dict(balance.get("confirmed_obstructions"))
    moon = _as_dict(support.get("moon_course"))

    event_evidence = []
    if primary.get("perfects"):
        event_evidence.append(_fact(
            "direct_perfection",
            "event",
            "support",
            "V5 질문시각 계산에서 직접 성사 경로가 확인됨",
            "horary_v5",
        ))
    elif indirect.get("best"):
        event_evidence.append(_fact(
            "indirect_perfection",
            "event",
            "support",
            "V5 계산에서 Translation/Collection 간접 연결 근거가 확인됨",
            "horary_v5",
        ))

    intention = []
    if str(reception.get("grade") or "none") != "none":
        intention.append(_fact(
            "reception",
            "disposition",
            "support",
            reception.get("label_ko") or "V5 리셉션 근거",
            "horary_v5",
        ))

    moon_evidence = []
    if moon:
        moon_evidence.append(_fact(
            "moon_course",
            "timing",
            "uncertain",
            "V5 Moon course 계산값 존재",
            "horary_v5",
        ))

    obstruction_rows = list(obstructions.get("prohibition_or_frustration") or [])
    refranation = obstructions.get("refranation")
    if refranation:
        obstruction_rows.append(refranation)
    counterevidence = []
    if obstruction_rows:
        counterevidence.append(_fact(
            "confirmed_obstruction",
            "obstruction",
            "counter",
            f"V5에서 확인된 방해 패턴 {len(obstruction_rows)}건",
            "horary_v5",
        ))

    meta = _as_dict(horary.get("meta"))
    tier = str(balance.get("tier") or "v5_ungraded")
    headline = str(balance.get("headline_ko") or "V5 빠른 계산 결과")
    uncertainty = [
        "V5 빠른 경로에는 V8 evidence grade가 없으므로 Cross V2가 임의 등급을 생성하거나 승격하지 않습니다."
    ]

    return {
        "schema": horary.get("schema"),
        "engine_version": meta.get("horary_engine") or "LUNEA_HORARY_ENGINE_V5_MOIETY_SECT",
        "conclusion": {
            "grade": "V5",
            "band": "NONE",
            "state": tier,
            "label_ko": headline,
        },
        "event_perfection_evidence": event_evidence,
        "intention_disposition": intention,
        "moon_timing_evidence": moon_evidence,
        "counterevidence": counterevidence,
        "uncertainty": uncertainty,
        "authoritative_snapshot": {
            "legacy_tier": tier,
            "primary_perfection": deepcopy(primary),
            "reception": deepcopy(reception),
            "indirect_perfection": deepcopy(indirect),
            "confirmed_obstructions": deepcopy(obstructions),
            "v8_grade_available": False,
        },
    }


def build_cross_interpretation_compat(
    horary: Optional[dict] = None,
    prashna: Optional[dict] = None,
) -> dict:
    """Use the normal V8 Cross contract when available; degrade conservatively on V5.

    The V5 fallback never invents an A/B/C/D grade. It preserves V5 facts and
    marks the Horary band as NONE so Cross cannot promote a legacy result.
    """
    if isinstance(horary, dict):
        if horary.get("schema") != "LUNEA_HORARY_V1":
            return _build_v8_cross(horary, prashna)
        support = _as_dict(horary.get("judgment_support"))
        has_v8 = bool(support.get("judgment_hierarchy_v8") or support.get("traditional_core_v8"))
        if has_v8:
            return _build_v8_cross(horary, prashna)
        horary_summary = _v5_horary_summary(horary)
    else:
        horary_summary = None

    prashna_summary = _prashna_summary(prashna)
    return {
        "schema": SCHEMA,
        "horary": horary_summary,
        "prashna": prashna_summary,
        "cross": _cross_summary(horary_summary, prashna_summary),
        "independence_contract": {
            "horary_grade_preserved": True,
            "prashna_support_preserved": True,
            "score_combination_performed": False,
            "weighted_average_performed": False,
            "majority_vote_performed": False,
            "comparison_layer_only": True,
            "v5_fastpath_compat": True,
        },
        "ai_contract": {
            "allowed": ["authoritative_fact_summary", "agreement_explanation", "conflict_explanation", "uncertainty_explanation"],
            "forbidden": ["invented_aspect", "invented_house", "invented_reception", "invented_prashna_factor", "probability", "exact_timing", "combined_verdict", "preferred_system", "invented_v8_grade"],
        },
    }
