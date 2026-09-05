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
     horary_topic_routes_v3.py horary_engine_v5.py horary_engine_v6.py ./

RUN python -c "from astro_core import load_ephemeris; x=load_ephemeris(); print('Ephemeris:', x[5])"
RUN python -c "import astro_api; print('Astro API import OK, version =', astro_api.app.version, 'transit max days =', astro_api.MAX_TRANSIT_DAYS)"
RUN python - <<'PY'
import horary_topic_routes_v3  # noqa: F401
import horary_balance_v31 as v31

d = v31.compute_horary(
    question_text='A는 2026년 9월 30일까지 나에게 먼저 사적인 연락을 해올까요?',
    question_iso='2026-09-05T18:11:00+09:00',
    topic='contact',
    timezone_name='Asia/Seoul',
    place='현재 위치',
    lat=34.7594,
    lon=127.6530,
)
j = d['judgment_support']
assert d['meta']['horary_engine'] == 'LUNEA_HORARY_ENGINE_V6_STRICT_TRADITIONAL_CORE'
assert j['perfection']['perfects'] is False
assert j['perfection']['reason'] == 'out_of_orb_no_active_perfection'
assert j['primary_connection']['traditional_valid_aspect'] is None
assert j['moon_course']['void_of_course'] is True
assert j['traditional_core_v6']['derived_house_policy']['target_message_house'] == 9
assert j['traditional_core_v6']['chart_invalid'] is False
print('Horary V6 deployment smoke OK')
PY

ENV PORT=10000
EXPOSE 10000

CMD ["sh", "-c", "uvicorn astro_api:app --host 0.0.0.0 --port ${PORT:-10000}"]
