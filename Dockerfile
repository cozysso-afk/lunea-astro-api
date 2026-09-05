FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

COPY requirements.txt .

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -r requirements.txt

COPY astro_core.py astro_api.py transit_extended.py \
     horary_balance_v2.py horary_balance_v3.py horary_balance_v31.py \
     horary_topic_routes_v3.py horary_engine_v5.py horary_engine_v6.py horary_engine_v7.py ./

RUN python -c "from astro_core import load_ephemeris; x=load_ephemeris(); print('Ephemeris:', x[5])"
RUN python -c "import astro_api; print('Astro API import OK, version =', astro_api.app.version, 'transit max days =', astro_api.MAX_TRANSIT_DAYS)"
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
assert j['perfection']['perfects'] is False
assert j['perfection']['reason'] == 'out_of_orb_no_active_perfection'
assert j['primary_connection']['traditional_valid_aspect'] is None
assert j['moon_course']['void_of_course'] is True
assert j['traditional_core_v6']['derived_house_policy']['target_message_house'] == 9
assert j['traditional_core_v6']['chart_invalid'] is False
assert j['route_contract_v7']['matches_spec'] is True
assert len(j['essential_dignities_v7']) == 7
assert j['bias_guard_v7']['direct_perfection_can_be_positive'] is True

# Positive soft-aspect sentinel: prevents an always-negative engine.
soft = calc('2026-09-04T15:00:00+09:00')
sp = soft['judgment_support']['perfection']
sc = soft['judgment_support']['traditional_core_v7']
assert sp['perfects'] is True
assert sp['perfection_check_started'] is True
assert sp['started_within_orb'] is True
assert sp['aspect']['traditional_valid_aspect'] == 'sextile'
assert sp['aspect']['traditional_state'] == 'valid_applying'
assert str(sc['qualified_evidence_grade_v7']).startswith('A')

# Positive hard-aspect sentinel: a square can perfect; friction is not auto-NO.
hard = calc('2026-09-06T15:00:00+09:00')
hp = hard['judgment_support']['perfection']
hc = hard['judgment_support']['traditional_core_v7']
assert hp['perfects'] is True
assert hp['aspect']['traditional_valid_aspect'] == 'square'
assert hp['aspect']['traditional_state'] == 'valid_applying'
assert str(hc['qualified_evidence_grade_v7']).startswith('A')
assert hc['direct_aspect_tone_v7'] == 'frictional'

# Separating sentinel: within-orb geometry is not a fresh perfection.
sep = calc('2026-09-05T01:00:00+09:00')
sj = sep['judgment_support']
assert sj['primary_connection']['within_orb'] is True
assert sj['primary_connection']['traditional_state'] == 'valid_separating'
assert sj['perfection']['perfects'] is False
assert sj['perfection']['reason'] == 'no_valid_applying_aspect'
assert not str(sj['traditional_core_v7']['qualified_evidence_grade_v7']).startswith('A_')

# Moon movement must not be promoted to question support merely because it is not VOC.
assert 'moon_relevance_v7' in soft['judgment_support']
assert 'question_relevant' in soft['judgment_support']['moon_relevance_v7']

print('Horary V7 deployment sentinels OK: negative / soft-positive / hard-positive / separating / Moon relevance / dignity')
PY

ENV PORT=10000
EXPOSE 10000

CMD ["sh", "-c", "uvicorn astro_api:app --host 0.0.0.0 --port ${PORT:-10000}"]
