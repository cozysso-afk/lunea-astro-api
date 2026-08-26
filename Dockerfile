FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

COPY requirements.txt .

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -r requirements.txt

COPY astro_core.py astro_api.py transit_extended.py ./

RUN python -c "from astro_core import load_ephemeris; x=load_ephemeris(); print('Ephemeris:', x[5])"
RUN python -c "import astro_api; print('Astro API import OK, transit max days =', astro_api.MAX_TRANSIT_DAYS)"

ENV PORT=10000
EXPOSE 10000

CMD ["sh", "-c", "uvicorn astro_api:app --host 0.0.0.0 --port ${PORT:-10000}"]
