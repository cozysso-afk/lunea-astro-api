from __future__ import annotations

from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from astro_core import compute_natal, KOREA_BIRTHPLACES

app = FastAPI(
    title="LUNEA Astro Core",
    version="1.0.0",
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
    return {"ok": True, "service": "LUNEA Astro Core", "version": "1.0.0"}

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
