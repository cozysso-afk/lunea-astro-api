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
}

core.HORARY_TOPIC_SPECS.update(EXTRA_HORARY_TOPIC_SPECS)
