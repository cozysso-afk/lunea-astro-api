from __future__ import annotations

from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from astro_core import (
    compute_natal,
    calculate_return_context,
    calculate_thai_taksa,
    KOREA_BIRTHPLACES,
)
from horary_balance_v2 import compute_horary
from transit_extended import scan_transits_extended, MAX_TRANSIT_DAYS

app = FastAPI(
    title="LUNEA Astro Core",
    version="1.5.0",
    description="Deterministic Western astrology calculation service for LUNEA."
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
        "version": "1.5.0",
        "horary": True,
        "horary_balance_v2": True,
        "transit_scan": True,
        "transit_scan_max_days": MAX_TRANSIT_DAYS,
        "returns": True,
        "thai_taksa": True,
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
