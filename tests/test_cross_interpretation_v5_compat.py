from __future__ import annotations

import horary_topic_routes_v3  # noqa: F401 - installs the V5 production fast path
import horary_balance_v31 as v31
from cross_interpretation_v5_compat import build_cross_interpretation_compat


def test_v5_fastpath_cross_does_not_require_v8_grade():
    horary = v31.compute_horary(
        question_text='A는 2026년 10월 31일까지 나에게 먼저 사적인 연락을 해올까요?',
        question_iso='2026-10-05T18:25:23+09:00',
        topic='contact',
        timezone_name='Asia/Seoul',
        place='현재 위치',
        lat=34.7594,
        lon=127.6530,
    )
    prashna = {
        'schema': 'LUNEA_PRASHNA_V1',
        'judgment_support': {
            'rule_set': 'TEST',
            'support_band': 'neutral',
            'support_band_ko': '중립',
            'support_score': 0,
            'binary_outcome_generated': False,
            'factors': [],
            'confidence_flags': [],
            'route': {},
        },
    }

    data = build_cross_interpretation_compat(horary, prashna)
    assert data['schema'] == 'LUNEA_HORARY_PRASHNA_CROSS_V2'
    assert data['horary']['engine_version'] == 'LUNEA_HORARY_ENGINE_V5_MOIETY_SECT'
    assert data['horary']['conclusion']['grade'] == 'V5'
    assert data['horary']['conclusion']['band'] == 'NONE'
    assert data['horary']['authoritative_snapshot']['v8_grade_available'] is False
    assert data['independence_contract']['v5_fastpath_compat'] is True
    assert 'invented_v8_grade' in data['ai_contract']['forbidden']
