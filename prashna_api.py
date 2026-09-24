from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

from prashna_core import compute_prashna


class PrashnaRequest(BaseModel):
    question_text: str = Field(..., min_length=1)
    question_iso: str = Field(..., examples=["2026-09-24T15:09:00"])
    topic: str = Field(default="general")
    timezone: str = Field(default="Asia/Seoul")
    place: Optional[str] = Field(default=None, examples=["여수"])
    lat: Optional[float] = None
    lon: Optional[float] = None


def install_prashna_api(app) -> None:
    if getattr(app.state, "lunea_prashna_v1", False):
        return
    app.state.lunea_prashna_v1 = True

    @app.post("/v1/prashna")
    def prashna(req: PrashnaRequest):
        try:
            return compute_prashna(
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
                detail=f"Prashna 계산 실패: {type(exc).__name__}: {exc}",
            )
