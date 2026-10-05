FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

COPY requirements.txt .

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -r requirements.txt

COPY astro_core.py astro_api.py transit_extended.py astro_performance_v2.py \
     astro_jobs_v1.py astro_job_api.py saju_core.py profile_auto_api.py vedic_core.py vedic_api.py \
     prashna_core.py prashna_api.py cross_interpretation_v2.py cross_interpretation_v5_compat.py cross_interpretation_api_v2.py \
     horary_balance_v2.py horary_balance_v3.py horary_balance_v31.py \
     horary_topic_routes_v3.py horary_engine_v5.py horary_engine_v6.py horary_engine_v7.py horary_engine_v8.py \
     horary_future_window_v2.py horary_future_window_v21.py horary_judgment_v2.py \
     horary_performance_v2.py horary_performance_v1.py ./
COPY tests/test_horary_engine_v7.py tests/test_horary_engine_v8.py tests/test_horary_patterns_real_v7.py \
     tests/test_horary_future_window_v2.py tests/test_horary_judgment_v2.py \
     tests/test_horary_performance_v2.py tests/test_horary_performance_v1.py \
     tests/test_horary_v5_fastpath_rollback.py tests/test_cross_interpretation_v5_compat.py \
     tests/test_saju_core_v1.py tests/test_vedic_core_v1.py tests/test_prashna_core_v1.py \
     tests/test_cross_interpretation_v2.py ./tests/

RUN python -c "from astro_core import load_ephemeris; x=load_ephemeris(); print('Ephemeris:', x[5])"
RUN python -c "import astro_job_api; print('Astro API+jobs import OK, version =', astro_job_api.app.version)"
RUN python - <<'PY'
import time
import horary_topic_routes_v3  # noqa: F401 - installs production V5 fast path
import horary_balance_v31 as v31
from cross_interpretation_v5_compat import build_cross_interpretation_compat

LAT = 34.7594
LON = 127.6530

def calc(iso, question='호라리 배포 검산', topic='general'):
    return v31.compute_horary(
        question_text=question,
        question_iso=iso,
        topic=topic,
        timezone_name='Asia/Seoul',
        place='현재 위치',
        lat=LAT,
        lon=LON,
    )

started = time.perf_counter()
d = calc(
    '2026-10-05T18:25:23+09:00',
    question='A는 2026년 10월 31일까지 나에게 먼저 사적인 연락을 해올까요?',
    topic='contact',
)
elapsed = time.perf_counter() - started
j = d['judgment_support']
assert d['schema'] == 'LUNEA_HORARY_V1'
assert d['meta']['horary_engine'] == 'LUNEA_HORARY_ENGINE_V5_MOIETY_SECT'
assert 'balance_v31' in j
assert 'traditional_core_v6' not in j
assert 'traditional_core_v8' not in j
assert 'horary_v2' not in j
assert elapsed < 15.0, elapsed

prashna = {
    'schema': 'LUNEA_PRASHNA_V1',
    'judgment_support': {
        'rule_set': 'DOCKER_SENTINEL',
        'support_band': 'neutral',
        'support_band_ko': '중립',
        'support_score': 0,
        'binary_outcome_generated': False,
        'factors': [],
        'confidence_flags': [],
        'route': {},
    },
}
cross = build_cross_interpretation_compat(d, prashna)
assert cross['schema'] == 'LUNEA_HORARY_PRASHNA_CROSS_V2'
assert cross['horary']['conclusion']['band'] == 'NONE'
assert cross['independence_contract']['v5_fastpath_compat'] is True
print(f'Horary V5 production fast-path sentinel OK: {elapsed:.3f}s + Cross compat')
PY

# Keep newer Horary modules regression-tested explicitly even while production
# stops at V5. These tests import the advanced layers themselves; production
# route installation above does not auto-enable them.
RUN python -m unittest -v \
    tests.test_horary_engine_v7 \
    tests.test_horary_engine_v8 \
    tests.test_horary_patterns_real_v7 \
    tests.test_horary_future_window_v2 \
    tests.test_horary_judgment_v2 \
    tests.test_horary_performance_v2 \
    tests.test_horary_performance_v1 \
    tests.test_saju_core_v1 \
    tests.test_vedic_core_v1 \
    tests.test_prashna_core_v1 \
    tests.test_cross_interpretation_v2

RUN python -m pytest -q \
    tests/test_horary_v5_fastpath_rollback.py \
    tests/test_cross_interpretation_v5_compat.py

ENV PORT=10000
EXPOSE 10000

CMD ["sh", "-c", "uvicorn astro_job_api:app --host 0.0.0.0 --port ${PORT:-10000}"]
