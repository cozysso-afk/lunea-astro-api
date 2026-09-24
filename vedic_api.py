from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

from vedic_core import compute_vedic_profile


class VedicProfileRequest(BaseModel):
    birth_date: str = Field(..., examples=["1991-03-21"])
    birth_time: str = Field(..., examples=["07:26"])
    place: Optional[str] = Field(default=None, examples=["여수"])
    timezone: str = Field(default="Asia/Seoul")
    lat: Optional[float] = None
    lon: Optional[float] = None


def install_vedic_api(app) -> None:
    if getattr(app.state, "lunea_vedic_v1", False):
        return
    app.state.lunea_vedic_v1 = True

    @app.post("/v1/vedic/profile")
    def vedic_profile(req: VedicProfileRequest):
        try:
            return compute_vedic_profile(
                birth_date=req.birth_date,
                birth_time=req.birth_time,
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
                detail=f"Vedic Profile 계산 실패: {type(exc).__name__}: {exc}",
            )
