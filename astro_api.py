from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from astro_core import (
    compute_natal,
    calculate_return_context,
    calculate_thai_taksa,
    KOREA_BIRTHPLACES,
)
import horary_topic_routes_v3  # noqa: F401  # patches extra Horary house routes
from horary_balance_v31 import compute_horary
from transit_extended import scan_transits_extended, MAX_TRANSIT_DAYS

THAI_TAKSA_RANGE_MAX_DAYS = 90

app = FastAPI(
    title="LUNEA Astro Core",
    version="1.8.0",
    description="Deterministic Western astrology and Thai Taksa calculation service for LUNEA."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://cozysso-afk.github.io",
        "http://localhost",
        "http://localhost:8000",
        "http://127.0.0.1:5500",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

class NatalRequest(BaseModel):
    birth_date: str = Field(..., examples=["1991-03-21"])
    birth_time: str = Field(..., examples=["07:26"])
    place: Optional[str] = Field(default=None, examples=["여수"])
    timezone: str = Field(default="Asia/Seoul")
    lat: Optional[float] = None
    lon: Optional[float] = None

@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "LUNEA Astro Core",
        "version": "1.8.0",
        "build": "thai-range-v1-20260902",
        "horary": True,
        "horary_balance_v31": True,
        "horary_balance_v3_compat": True,
        "horary_balance_v2_compat": True,
        "horary_topic_routes_v3": True,
        "transit_scan": True,
        "transit_scan_max_days": MAX_TRANSIT_DAYS,
        "returns": True,
        "thai_taksa": True,
        "thai_taksa_range": True,
        "thai_taksa_range_max_days": THAI_TAKSA_RANGE_MAX_DAYS,
    }

@app.get("/v1/locations")
def locations():
    return {
        "timezone_default": "Asia/Seoul",
        "locations": [
            {"name": name, "lat": lat, "lon": lon}
            for name, (lat, lon) in KOREA_BIRTHPLACES.items()
        ]
    }

@app.post("/v1/natal")
def natal(req: NatalRequest):
    try:
        return compute_natal(
            birth_date=req.birth_date,
            birth_time=req.birth_time,
            place=req.place,
            timezone_name=req.timezone,
            lat=req.lat,
            lon=req.lon,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Natal 계산 실패: {type(exc).__name__}: {exc}"
        )

class HoraryRequest(BaseModel):
    question_text: str = Field(..., min_length=2)
    question_iso: str = Field(..., examples=["2026-08-25T22:30"])
    topic: str = Field(default="general")
    timezone: str = Field(default="Asia/Seoul")
    place: Optional[str] = Field(default=None, examples=["여수"])
    lat: Optional[float] = None
    lon: Optional[float] = None

@app.post("/v1/horary")
def horary(req: HoraryRequest):
    try:
        return compute_horary(
            question_text=req.question_text,
            question_iso=req.question_iso,
            topic=req.topic,
            timezone_name=req.timezone,
            place=req.place,
            lat=req.lat,
            lon=req.lon,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Horary 계산 실패: {type(exc).__name__}: {exc}"
        )

class TransitScanRequest(BaseModel):
    natal: dict
    topic: str = Field(default="general")
    start_iso: Optional[str] = None
    days: int = Field(default=30, ge=1, le=MAX_TRANSIT_DAYS)
    timezone: str = Field(default="Asia/Seoul")

@app.post("/v1/transits/scan")
def transit_scan(req: TransitScanRequest):
    try:
        return scan_transits_extended(
            natal=req.natal,
            topic=req.topic,
            start_iso=req.start_iso,
            days=req.days,
            timezone_name=req.timezone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Transit 스캔 실패: {type(exc).__name__}: {exc}"
        )

class ReturnContextRequest(BaseModel):
    natal: dict
    bodies: list[str] = Field(default_factory=lambda: ["Sun","Moon"])
    center_iso: Optional[str] = None
    timezone: str = Field(default="Asia/Seoul")
    place: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None

@app.post("/v1/returns/context")
def return_context(req: ReturnContextRequest):
    try:
        return calculate_return_context(
            natal=req.natal,
            bodies=req.bodies,
            center_iso=req.center_iso,
            timezone_name=req.timezone,
            place=req.place,
            lat=req.lat,
            lon=req.lon,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Return 계산 실패: {type(exc).__name__}: {exc}"
        )

class ThaiTaksaRequest(BaseModel):
    natal: dict
    topic: str = Field(default="general")
    current_iso: Optional[str] = None
    timezone: str = Field(default="Asia/Seoul")

@app.post("/v1/thai/taksa")
def thai_taksa(req: ThaiTaksaRequest):
    try:
        return calculate_thai_taksa(
            natal=req.natal,
            topic=req.topic,
            current_iso=req.current_iso,
            timezone_name=req.timezone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Thai Taksa 계산 실패: {type(exc).__name__}: {exc}"
        )


class ThaiTaksaRangeRequest(BaseModel):
    natal: dict
    topic: str = Field(default="general")
    start_iso: Optional[str] = None
    days: int = Field(default=14, ge=1, le=THAI_TAKSA_RANGE_MAX_DAYS)
    timezone: str = Field(default="Asia/Seoul")


def _thai_local_start(value: Optional[str], timezone_name: str) -> datetime:
    tz = ZoneInfo(timezone_name or "Asia/Seoul")
    if not value:
        return datetime.now(tz)
    raw = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        try:
            dt = datetime.fromisoformat(f"{raw}T12:00:00")
        except ValueError as exc:
            raise ValueError("Thai 기간 시작일은 ISO 날짜/시각 형식이어야 합니다.") from exc
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def _thai_tone(position: Optional[str]) -> dict:
    if position in {"Sri", "Montri", "Dech"}:
        return {"key": "supportive", "label_ko": "지원"}
    if position == "Kalakini":
        return {"key": "caution", "label_ko": "주의"}
    return {"key": "neutral", "label_ko": "중립"}


def _thai_range_snapshot(result: dict, segment: str) -> dict:
    current = result.get("current_day") or {}
    row = current.get("falls_in_natal_taksa") or {}
    ruler = current.get("ruler") or {}
    focus_positions = set((result.get("question") or {}).get("focus_positions") or [])
    position = row.get("position")
    return {
        "segment": segment,
        "ruler": {
            "key": ruler.get("key"),
            "ko": ruler.get("ko"),
            "planet_number": ruler.get("planet_number"),
        },
        "position": position,
        "position_ko": row.get("position_ko"),
        "position_thai": row.get("position_thai"),
        "meaning_ko": row.get("meaning_ko"),
        "tone": _thai_tone(position),
        "focus_match": bool(position and position in focus_positions),
    }


@app.post("/v1/thai/taksa/range")
def thai_taksa_range(req: ThaiTaksaRangeRequest):
    try:
        tz = ZoneInfo(req.timezone or "Asia/Seoul")
        start = _thai_local_start(req.start_iso, req.timezone)
        first_date = start.date()
        calendar = []
        all_segments = []

        for offset in range(req.days):
            day_date = first_date + timedelta(days=offset)
            # A Taksa calendar day is represented from the 06:00 boundary.
            # Noon captures the normal day ruler; 21:00 captures the special
            # Wednesday-night Rahu rule without pretending this is a transit.
            noon = datetime(
                day_date.year, day_date.month, day_date.day, 12, 0, tzinfo=tz
            )
            evening = datetime(
                day_date.year, day_date.month, day_date.day, 21, 0, tzinfo=tz
            )
            day_result = calculate_thai_taksa(
                natal=req.natal,
                topic=req.topic,
                current_iso=noon.isoformat(),
                timezone_name=req.timezone,
            )
            night_result = calculate_thai_taksa(
                natal=req.natal,
                topic=req.topic,
                current_iso=evening.isoformat(),
                timezone_name=req.timezone,
            )

            daytime = _thai_range_snapshot(day_result, "daytime")
            evening_snap = _thai_range_snapshot(night_result, "evening")
            night_variant = None
            if (
                evening_snap["ruler"].get("key") != daytime["ruler"].get("key")
                or evening_snap.get("position") != daytime.get("position")
            ):
                night_variant = evening_snap

            entry = {
                "date": day_date.isoformat(),
                "taksa_day_window": "06:00-05:59",
                "weekday_label": (day_result.get("current_day") or {}).get("weekday_label"),
                "daytime": daytime,
                "night_variant": night_variant,
            }
            calendar.append(entry)
            all_segments.append({"date": entry["date"], **daytime})
            if night_variant:
                all_segments.append({"date": entry["date"], **night_variant})

        support = [x for x in all_segments if x["tone"]["key"] == "supportive"]
        caution = [x for x in all_segments if x["tone"]["key"] == "caution"]
        focus_hits = [x for x in all_segments if x.get("focus_match")]

        return {
            "schema": "LUNEA_THAI_TAKSA_RANGE_V1",
            "topic": req.topic,
            "timezone": req.timezone,
            "start_date": first_date.isoformat(),
            "days": req.days,
            "calendar": calendar,
            "summary": {
                "supportive_segments": len(support),
                "neutral_segments": len(all_segments) - len(support) - len(caution),
                "caution_segments": len(caution),
                "focus_match_segments": len(focus_hits),
                "supportive_dates": [x["date"] for x in support[:12]],
                "caution_dates": [x["date"] for x in caution[:12]],
                "focus_match_dates": [x["date"] for x in focus_hits[:12]],
            },
            "meta": {
                "calendar_type": "weekday-ruler Taksa calendar; not an astronomical transit scan",
                "day_boundary": "06:00 local time",
                "wednesday_night": "18:00-05:59 uses Rahu when the underlying Taksa calculator indicates it",
                "tone_policy": "Sri/Montri/Dech=supportive, Kalakini=caution, remaining positions=neutral",
                "interpretation_boundary": "Structural timing support only; no deterministic event-date guarantee.",
            },
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Thai Taksa 기간 계산 실패: {type(exc).__name__}: {exc}"
        )
