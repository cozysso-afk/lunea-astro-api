from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional


SCHEMA = "LUNEA_HORARY_PRASHNA_CROSS_V2"

_PRASHNA_DISPOSITION_CODES = {
    "subject_lord_dignity",
    "subject_lord_dusthana",
}
_PRASHNA_EVENT_CODES = {
    "event_lord_dignity",
    "subject_lord_in_event_house",
    "event_lord_in_subject_house",
    "shared_lord",
    "mutual_graha_drishti",
    "one_way_graha_drishti",
    "moon_in_event_house",
    "moon_aspects_event_house",
    "jupiter_benefic_event_aspect",
    "venus_benefic_event_aspect",
    "event_lord_dusthana",
    "mars_malefic_event_aspect",
    "saturn_malefic_event_aspect",
}
_PRASHNA_OBSTRUCTION_CODES = {
    "subject_lord_dusthana",
    "event_lord_dusthana",
    "mars_malefic_event_aspect",
    "saturn_malefic_event_aspect",
}


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _fact(code: str, domain: str, direction: str, label: str, source: str) -> dict:
    return {
        "code": code,
        "domain": domain,
        "direction": direction,
        "label_ko": str(label or code),
        "source": source,
    }


def _horary_summary(horary: Optional[dict]) -> Optional[dict]:
    if not isinstance(horary, dict):
        return None
    if horary.get("schema") != "LUNEA_HORARY_V1":
        raise ValueError("Horary 응답 schema가 LUNEA_HORARY_V1이 아닙니다.")

    support = _as_dict(horary.get("judgment_support"))
    v8 = _as_dict(support.get("judgment_hierarchy_v8"))
    if not v8:
        v8 = _as_dict(support.get("traditional_core_v8"))
    if not v8:
        raise ValueError("Horary V8 judgment hierarchy가 필요합니다.")

    grade = str(v8.get("qualified_evidence_grade_v8") or "NONE")
    band = str(v8.get("grade_band_v8") or "NONE")
    action = _as_dict(v8.get("action_state_v8"))
    reception = _as_dict(v8.get("intention_reception_v8"))
    event_axes = _as_dict(v8.get("event_axes_v8"))
    indirect = _as_dict(v8.get("indirect_v8"))
    moon = _as_dict(v8.get("moon_event_testimony_v8"))
    obstruction_count = int(v8.get("confirmed_obstruction_count_v8") or 0)

    event_evidence = []
    if band == "A":
        event_evidence.append(_fact("direct_perfection", "event", "support", action.get("label_ko"), "horary_v8"))
    elif band == "B":
        event_evidence.append(_fact("indirect_perfection", "event", "support", action.get("label_ko"), "horary_v8"))
    elif event_axes.get("has_perfection"):
        event_evidence.append(_fact("derived_event_perfection", "event", "support", action.get("label_ko"), "horary_v8"))
    elif moon.get("confirmed"):
        event_evidence.append(_fact("moon_event_testimony", "timing", "support", moon.get("label_ko"), "horary_v8"))

    intention = []
    if str(reception.get("state") or "none") != "none":
        intention.append(_fact("reception", "disposition", "support", reception.get("label_ko"), "horary_v8"))

    moon_evidence = []
    if moon:
        moon_evidence.append(_fact(
            "moon_event_testimony" if moon.get("confirmed") else "moon_limit",
            "timing",
            "support" if moon.get("confirmed") else "uncertain",
            moon.get("label_ko"),
            "horary_v8",
        ))

    counterevidence = []
    if obstruction_count:
        counterevidence.append(_fact(
            "confirmed_obstruction",
            "obstruction",
            "counter",
            f"확인된 선행 방해 {obstruction_count}건",
            "horary_v8",
        ))

    uncertainty = []
    if band in {"D", "NONE"}:
        uncertainty.append("확인된 사건 성사 근거가 충분하지 않으며 D/NONE은 자동 부정을 뜻하지 않습니다.")
    if event_evidence and obstruction_count:
        uncertainty.append("사건 연결 근거와 확인된 방해가 함께 있어 진행 과정이 단순하지 않습니다.")

    return {
        "schema": horary.get("schema"),
        "engine_version": v8.get("version"),
        "conclusion": {
            "grade": grade,
            "band": band,
            "state": v8.get("overall_state_v8"),
            "label_ko": v8.get("overall_ko_v8"),
        },
        "event_perfection_evidence": event_evidence,
        "intention_disposition": intention,
        "moon_timing_evidence": moon_evidence,
        "counterevidence": counterevidence,
        "uncertainty": uncertainty,
        "authoritative_snapshot": {
            "grade": grade,
            "band": band,
            "grade_source": v8.get("grade_source_v8"),
            "action_state": deepcopy(action),
            "reception_state": deepcopy(reception),
            "event_axes": deepcopy(event_axes),
            "indirect": deepcopy(indirect),
            "moon_event_testimony": deepcopy(moon),
            "confirmed_obstruction_count": obstruction_count,
        },
    }


def _prashna_summary(prashna: Optional[dict]) -> Optional[dict]:
    if not isinstance(prashna, dict):
        return None
    if prashna.get("schema") != "LUNEA_PRASHNA_V1":
        raise ValueError("Prashna 응답 schema가 LUNEA_PRASHNA_V1이 아닙니다.")

    support = _as_dict(prashna.get("judgment_support"))
    factors = _as_list(support.get("factors"))
    supporting = []
    counter = []
    domain_scores = {"disposition": 0, "event": 0, "obstruction": 0}
    for row in factors:
        item = _as_dict(row)
        code = str(item.get("code") or "")
        score = int(item.get("score") or 0)
        if code in _PRASHNA_DISPOSITION_CODES:
            domain = "disposition"
        elif code in _PRASHNA_EVENT_CODES:
            domain = "obstruction" if code in _PRASHNA_OBSTRUCTION_CODES and score < 0 else "event"
        else:
            domain = "context"
        if domain in domain_scores:
            domain_scores[domain] += score
        fact = _fact(code or "prashna_factor", domain, "support" if score > 0 else "counter", item.get("detail_ko") or item.get("label_ko"), "prashna_v1")
        fact["score"] = score
        (supporting if score > 0 else counter).append(fact)

    flags = _as_list(support.get("confidence_flags"))
    uncertainty = [str(_as_dict(row).get("detail_ko") or "").strip() for row in flags]
    uncertainty = [row for row in uncertainty if row]
    if not factors:
        uncertainty.append("Prashna 구조 근거가 제공되지 않았습니다.")

    return {
        "schema": prashna.get("schema"),
        "rule_set": support.get("rule_set"),
        "conclusion": {
            "support_band": support.get("support_band"),
            "support_band_ko": support.get("support_band_ko"),
            "binary_outcome_generated": bool(support.get("binary_outcome_generated")),
            "label_ko": f"구조적 지원 {support.get('support_band_ko') or '미정'}",
        },
        "supporting_evidence": supporting,
        "counterevidence": counter,
        "uncertainty": uncertainty,
        "domain_scores": domain_scores,
        "authoritative_snapshot": {
            "support_score": support.get("support_score"),
            "support_band": support.get("support_band"),
            "route": deepcopy(_as_dict(support.get("route"))),
            "factors": deepcopy(factors),
            "confidence_flags": deepcopy(flags),
        },
    }


def _cross_summary(horary: Optional[dict], prashna: Optional[dict]) -> dict:
    if not horary or not prashna:
        missing = "Horary" if not horary else "Prashna"
        return {
            "relationship": "insufficient",
            "agreements": [],
            "conflicts": [],
            "explanation": f"{missing} 결과가 없어 두 독립 체계의 의미 영역을 비교하지 않았습니다.",
            "uncertainty": [f"{missing} 결과가 추가되기 전에는 교차 판정을 확정할 수 없습니다."],
            "domains": [],
        }

    h_band = str(_as_dict(horary.get("conclusion")).get("band") or "NONE")
    h_event = h_band in {"A", "B", "C"}
    h_disposition = bool(horary.get("intention_disposition"))
    h_obstruction = bool(horary.get("counterevidence"))
    p_scores = _as_dict(prashna.get("domain_scores"))
    p_event_score = int(p_scores.get("event") or 0)
    p_disposition_score = int(p_scores.get("disposition") or 0)
    p_obstruction_score = int(p_scores.get("obstruction") or 0)
    p_event = p_event_score >= 1
    p_disposition = p_disposition_score >= 1
    p_strong_obstruction = p_obstruction_score <= -2

    agreements = []
    conflicts = []
    domains = []

    if h_disposition and p_disposition:
        agreements.append("두 체계 모두 의향·지원 조건의 긍정 근거를 보여줍니다.")
        domains.append({"domain": "disposition", "horary": "support", "prashna": "support", "relationship": "agreement"})
    elif h_disposition or p_disposition:
        domains.append({"domain": "disposition", "horary": "support" if h_disposition else "insufficient", "prashna": "support" if p_disposition else "insufficient", "relationship": "insufficient"})

    if h_event and p_event:
        agreements.append("두 체계 모두 실제 사건 진행과 연결되는 독립 근거를 보여줍니다.")
        domains.append({"domain": "event", "horary": "support", "prashna": "support", "relationship": "agreement"})
    elif h_event and p_strong_obstruction:
        conflicts.append("Horary는 사건 연결을 보여주지만 Prashna는 진행 과정의 강한 장애를 강조합니다.")
        domains.append({"domain": "event", "horary": "support", "prashna": "counter", "relationship": "conflict"})
    elif h_event or p_event:
        domains.append({"domain": "event", "horary": "support" if h_event else "insufficient", "prashna": "support" if p_event else ("counter" if p_strong_obstruction else "insufficient"), "relationship": "insufficient"})

    if h_obstruction and p_strong_obstruction:
        agreements.append("두 체계 모두 진행상의 방해·지연 근거를 별도로 보여줍니다.")
        domains.append({"domain": "obstruction", "horary": "counter", "prashna": "counter", "relationship": "agreement"})

    if conflicts:
        relationship = "conflict"
        explanation = "두 체계의 결론을 합치지 않고, 사건 연결과 장애 근거의 충돌을 그대로 유지합니다."
    elif agreements and any(row.get("domain") == "event" and row.get("relationship") == "agreement" for row in domains) and all(row.get("relationship") == "agreement" for row in domains):
        relationship = "agreement"
        explanation = "비교 가능한 의미 영역에서 두 독립 체계가 같은 방향의 근거를 보입니다."
    elif agreements or domains:
        relationship = "partial_agreement"
        explanation = "일부 의미 영역은 일치하지만 사건 성사·의향·장애를 같은 결론으로 합치지 않습니다."
    else:
        relationship = "insufficient"
        explanation = "비교 가능한 의미 영역의 근거가 충분하지 않습니다."

    uncertainty = []
    if h_band in {"D", "NONE"} and (p_event or p_disposition):
        uncertainty.append("Prashna의 지원 근거는 Horary D/NONE 등급을 승격하지 않습니다.")
    if h_event and not p_event:
        uncertainty.append("Prashna의 약하거나 불충분한 근거는 Horary 사건 등급을 낮추지 않습니다.")
    if h_disposition and not h_event:
        uncertainty.append("의향·수용성의 일치는 실제 사건 성사 합의가 아닙니다.")
    uncertainty.extend(horary.get("uncertainty") or [])
    uncertainty.extend(prashna.get("uncertainty") or [])

    return {
        "relationship": relationship,
        "agreements": agreements,
        "conflicts": conflicts,
        "explanation": explanation,
        "uncertainty": list(dict.fromkeys(uncertainty)),
        "domains": domains,
    }


def build_cross_interpretation(horary: Optional[dict] = None, prashna: Optional[dict] = None) -> dict:
    """Compare authoritative outputs without recalculating or mutating either engine."""
    horary_summary = _horary_summary(horary)
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
        },
        "ai_contract": {
            "allowed": ["authoritative_fact_summary", "agreement_explanation", "conflict_explanation", "uncertainty_explanation"],
            "forbidden": ["invented_aspect", "invented_house", "invented_reception", "invented_prashna_factor", "probability", "exact_timing", "combined_verdict", "preferred_system"],
        },
    }
