from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

from saju_core import compute_four_pillars


class FourPillarsRequest(BaseModel):
    birth_date: str = Field(..., examples=["1991-03-21"])
    birth_time: str = Field(..., examples=["07:26"])
    place: Optional[str] = Field(default=None, examples=["여수"])
    timezone: str = Field(default="Asia/Seoul")


def install_profile_auto(app) -> None:
    if getattr(app.state, "lunea_profile_auto_v1", False):
        return
    app.state.lunea_profile_auto_v1 = True

    @app.post("/v1/profile/four-pillars")
    def four_pillars(req: FourPillarsRequest):
        try:
            return compute_four_pillars(
                birth_date=req.birth_date,
                birth_time=req.birth_time,
                timezone_name=req.timezone,
                place=req.place,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Four Pillars 계산 실패: {type(exc).__name__}: {exc}",
            )
