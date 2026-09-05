from __future__ import annotations

import astro_core as core


# Missing house routes for questions that previously fell through to
# general=7H ("other person") even when the subject was not another person.
# These are secondary routing additions; existing topic specs stay unchanged.
EXTRA_HORARY_TOPIC_SPECS = {
    "friend": {
        "label_ko": "친구·지인·커뮤니티",
        "quesited_house": 11,
        "event_house": None,
        "note": "친구·지인·모임의 관계는 11하우스를 사용합니다.",
    },
    "travel": {
        "label_ko": "여행·유학·장거리 이동",
        "quesited_house": 9,
        "event_house": None,
        "note": "해외·유학·장거리 여행과 이동은 9하우스를 사용합니다.",
    },
    "contract": {
        "label_ko": "계약·협상",
        "quesited_house": 7,
        "event_house": 3,
        "note": "계약 상대는 7하우스, 문서·서명·소통은 3하우스를 보조로 봅니다.",
    },
    "purchase": {
        "label_ko": "구매·소유",
        "quesited_house": 2,
        "event_house": None,
        "note": "구매할 동산·소유물과 지출 판단은 2하우스를 사용합니다.",
    },
    "communication": {
        "label_ko": "문서·소식·일반 연락",
        "quesited_house": 3,
        "event_house": None,
        "note": "특정 상대 관계축보다 문서·소식 자체가 핵심인 질문은 3하우스를 사용합니다.",
    },
    "lost_object": {
        "label_ko": "분실물·소유물 위치",
        "quesited_house": 2,
        "event_house": None,
        "note": (
            "질문자가 소유한 이동 가능한 분실물·소지품은 2하우스와 그 주인행성을 "
            "핵심 위치 시그니피케이터로 사용합니다. 위치 질문에서는 직접 성사각 부재를 "
            "물건 부재나 위치 부정으로 해석하지 않습니다."
        ),
    },
    "pet": {
        "label_ko": "반려동물·작은 동물",
        "quesited_house": 6,
        "event_house": None,
        "note": "반려동물과 작은 동물은 전통적으로 6하우스와 그 주인행성을 사용합니다.",
    },
    "children": {
        "label_ko": "자녀·임신·출산",
        "quesited_house": 5,
        "event_house": None,
        "note": "자녀·임신·출산·수태 질문은 5하우스와 그 주인행성을 우선합니다.",
    },
    "shared_money": {
        "label_ko": "상속·타인의 돈·공동재산",
        "quesited_house": 8,
        "event_house": None,
        "note": "상속·타인의 재산·배우자 또는 상대의 자금·공동재산은 8하우스를 우선합니다.",
    },
    "hidden": {
        "label_ko": "비밀·숨겨진 일",
        "quesited_house": 12,
        "event_house": None,
        "note": "비밀·은폐·숨겨진 일과 보이지 않는 방해는 12하우스를 우선합니다.",
    },
}

core.HORARY_TOPIC_SPECS.update(EXTRA_HORARY_TOPIC_SPECS)


# HORARY CONDITION ENRICHMENT V4
# ------------------------------
# The base calculation already returns correct traditional planet positions,
# houses, motion, and essential dignity. This additive layer exposes a few
# traditional condition facts that descriptive/location questions need:
# - Cazimi / Combustion / Under the Beams
# - angular / succedent / cadent house strength
# - traditional dispositor and its actual chart placement
# - Part of Fortune with its Regiomontanus house
#
# It does not turn these signals into a deterministic YES/NO score.

def _house_strength(house):
    house = int(house or 0)
    if house in {1, 4, 7, 10}:
        return "angular", "Angular(각진 하우스·행동력/가시성 강함)"
    if house in {2, 5, 8, 11}:
        return "succedent", "Succedent(후속 하우스·지속/유지력 보통)"
    if house in {3, 6, 9, 12}:
        return "cadent", "Cadent(쇠약 하우스·행동력/가시성 약함)"
    return "unknown", "하우스 강도 미확인"


def _solar_condition(body, row, sun_row):
    if body == "Sun":
        return "sun", "Sun(태양 자체)"
    sep = core.angular_separation(float(row["longitude"]), float(sun_row["longitude"]))
    if sep <= (17.0 / 60.0):
        return "cazimi", "Cazimi(카지미·태양 심장부)"
    if sep < 8.5:
        return "combust", "Combustion(컴버스트·태양 연소)"
    if sep < 17.0:
        return "under_beams", "Under the Beams(태양 광선 아래)"
    return "free_of_beams", "태양 광선 영향권 밖"


def _enrich_horary_payload(data):
    if not isinstance(data, dict) or data.get("schema") != "LUNEA_HORARY_V1":
        return data

    planets = data.get("planets") or {}
    sun = planets.get("Sun") or {}
    conditions = {}

    for body in core.HORARY_PLANETS:
        row = planets.get(body)
        if not isinstance(row, dict):
            continue
        h_key, h_ko = _house_strength(row.get("house"))
        s_key, s_ko = _solar_condition(body, row, sun) if sun else ("unknown", "태양 상태 미확인")
        sign_index = int(row.get("sign_index") or 0)
        dispositor = core.HORARY_RULER_BY_SIGN[sign_index]

        row["house_strength"] = h_key
        row["house_strength_ko"] = h_ko
        row["solar_condition"] = s_key
        row["solar_condition_ko"] = s_ko
        row["traditional_dispositor"] = dispositor
        row["traditional_dispositor_ko"] = core.PLANET_KO.get(dispositor, dispositor)

        conditions[body] = {
            "body": body,
            "body_ko": core.PLANET_KO.get(body, body),
            "house": row.get("house"),
            "house_strength": h_key,
            "house_strength_ko": h_ko,
            "solar_condition": s_key,
            "solar_condition_ko": s_ko,
            "retrograde": bool(row.get("retrograde")),
            "direction": row.get("direction"),
            "dignity": row.get("dignity"),
            "dignity_ko": row.get("dignity_ko"),
            "traditional_dispositor": dispositor,
            "traditional_dispositor_ko": core.PLANET_KO.get(dispositor, dispositor),
        }

    asc = ((data.get("angles") or {}).get("ASC") or {}).get("longitude")
    sun_lon = sun.get("longitude") if sun else None
    moon_lon = (planets.get("Moon") or {}).get("longitude")
    cusps = data.get("cusps") or []
    if asc is not None and sun_lon is not None and moon_lon is not None and len(cusps) == 12:
        sun_house = int(sun.get("house") or 0)
        day_chart = 7 <= sun_house <= 12
        pof_lon = core.calculate_pof(float(asc), float(sun_lon), float(moon_lon), day_chart)
        pof = {
            **core.sign_data(pof_lon),
            "name_ko": "포르투나",
            "house": core.cusp_house(pof_lon, cusps),
            "formula": "day: ASC+Moon-Sun" if day_chart else "night: ASC+Sun-Moon",
        }
        data.setdefault("points", {})["PartOfFortune"] = pof

    judgment = data.setdefault("judgment_support", {})
    judgment["planet_conditions_v4"] = conditions
    judgment["condition_interpretation_note_ko"] = (
        "Cazimi/Combustion/Under the Beams와 angular/succedent/cadent 상태는 "
        "행동력·가시성·상태 묘사의 보조 근거입니다. 단독으로 성사/불성사 또는 위치를 확정하지 않습니다."
    )
    data.setdefault("meta", {})["horary_enrichment"] = "LUNEA_HORARY_CONDITION_V4"
    return data


# astro_api imports this routing module before importing compute_horary from
# horary_balance_v31. Patch that function once so the API keeps its existing
# import contract and Docker file list while returning the additive V4 fields.
try:
    import horary_balance_v31 as _v31

    if not getattr(_v31.compute_horary, "_lunea_condition_v4", False):
        _base_compute_horary = _v31.compute_horary

        def _compute_horary_v4(*args, **kwargs):
            return _enrich_horary_payload(_base_compute_horary(*args, **kwargs))

        _compute_horary_v4._lunea_condition_v4 = True
        _v31.compute_horary = _compute_horary_v4
except Exception:
    # Keep import-time resilience; the normal CI/runtime import path should patch.
    pass
