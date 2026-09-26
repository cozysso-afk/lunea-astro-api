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
     prashna_core.py prashna_api.py \
     horary_balance_v2.py horary_balance_v3.py horary_balance_v31.py \
     horary_topic_routes_v3.py horary_engine_v5.py horary_engine_v6.py horary_engine_v7.py horary_engine_v8.py ./
COPY tests/test_horary_engine_v7.py tests/test_horary_engine_v8.py tests/test_horary_patterns_real_v7.py \
     tests/test_saju_core_v1.py tests/test_vedic_core_v1.py tests/test_prashna_core_v1.py ./tests/

RUN python -c "from astro_core import load_ephemeris; x=load_ephemeris(); print('Ephemeris:', x[5])"
RUN python -c "import astro_job_api; print('Astro API+jobs import OK, version =', astro_job_api.app.version)"
RUN python - <<'PY'
import horary_topic_routes_v3  # noqa: F401
import horary_balance_v31 as v31

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

# Negative sentinel: an out-of-orb geometric trine is not direct perfection.
d = calc(
    '2026-09-05T18:11:00+09:00',
    question='A는 2026년 9월 30일까지 나에게 먼저 사적인 연락을 해올까요?',
    topic='contact',
)
j = d['judgment_support']
assert d['meta']['horary_engine'] == 'LUNEA_HORARY_ENGINE_V7_BALANCE_GUARDS'
assert d['meta']['judgment_hierarchy'] == 'LUNEA_HORARY_ENGINE_V8_JUDGMENT_HIERARCHY'
assert j['perfection']['perfects'] is False
assert j['perfection']['reason'] == 'out_of_orb_no_active_perfection'
assert j['primary_connection']['traditional_valid_aspect'] is None
assert j['moon_course']['void_of_course'] is True
assert j['traditional_core_v6']['derived_house_policy']['target_message_house'] == 9
assert j['traditional_core_v6']['chart_invalid'] is False
assert j['route_contract_v7']['matches_spec'] is True
assert len(j['essential_dignities_v7']) == 7
assert j['bias_guard_v7']['direct_perfection_can_be_positive'] is True
assert j['bias_guard_v7']['mixed_dignity_debility_preserved'] is True
assert 'traditional_core_v8' in j
assert 'judgment_hierarchy_v8' in j
assert j['bias_guard_v8']['reception_only_remains_unperfected'] is True
assert j['bias_guard_v8']['d_state_must_not_be_worded_as_automatic_no'] is True

# Positive soft-aspect sentinel: prevents an always-negative engine.
soft = calc('2026-09-04T15:00:00+09:00')
sp = soft['judgment_support']['perfection']
sc = soft['judgment_support']['traditional_core_v8']
assert sp['perfects'] is True
assert sp['perfection_check_started'] is True
assert sp['started_within_orb'] is True
assert sp['aspect']['traditional_valid_aspect'] == 'sextile'
assert sp['aspect']['traditional_state'] == 'valid_applying'
assert str(sc['qualified_evidence_grade_v8']).startswith('A')

# Positive hard-aspect sentinel: a square can perfect; friction is not auto-NO.
hard = calc('2026-09-06T15:00:00+09:00')
hp = hard['judgment_support']['perfection']
hc = hard['judgment_support']['traditional_core_v8']
assert hp['perfects'] is True
assert hp['aspect']['traditional_valid_aspect'] == 'square'
assert hp['aspect']['traditional_state'] == 'valid_applying'
assert str(hc['qualified_evidence_grade_v8']).startswith('A')
assert hc['direct_aspect_tone_v7'] == 'frictional'

# Separating sentinel: within-orb geometry is not a fresh perfection.
sep = calc('2026-09-05T01:00:00+09:00')
sj = sep['judgment_support']
assert sj['primary_connection']['within_orb'] is True
assert sj['primary_connection']['traditional_state'] == 'valid_separating'
assert sj['perfection']['perfects'] is False
assert sj['perfection']['reason'] == 'no_valid_applying_aspect'
assert not str(sj['traditional_core_v8']['qualified_evidence_grade_v8']).startswith('A_')

# Moon movement must not be promoted merely because it is not VOC; V8 only
# promotes an actual next major application to the quesited/event ruler.
assert 'moon_relevance_v7' in soft['judgment_support']
assert 'question_relevant' in soft['judgment_support']['moon_relevance_v7']
assert 'moon_event_testimony_v8' in soft['judgment_support']['traditional_core_v8']

print('Horary V8 deployment sentinels OK: V7 core + V8 hierarchy / negative / soft-positive / hard-positive / separating / Moon event distinction')
PY

# Production builds execute Horary V7/V8 plus the independent Saju / Vedic / Prashna contracts.
RUN python -m unittest -v \
    tests.test_horary_engine_v7 \
    tests.test_horary_engine_v8 \
    tests.test_horary_patterns_real_v7 \
    tests.test_saju_core_v1 \
    tests.test_vedic_core_v1 \
    tests.test_prashna_core_v1

ENV PORT=10000
EXPOSE 10000

CMD ["sh", "-c", "uvicorn astro_job_api:app --host 0.0.0.0 --port ${PORT:-10000}"]
