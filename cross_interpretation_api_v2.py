from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException
from pydantic import BaseModel

from cross_interpretation_v5_compat import build_cross_interpretation_compat


class CrossInterpretationRequest(BaseModel):
    horary: Optional[dict[str, Any]] = None
    prashna: Optional[dict[str, Any]] = None


def install_cross_interpretation_api(app) -> None:
    if getattr(app.state, "lunea_horary_prashna_cross_v2", False):
        return
    app.state.lunea_horary_prashna_cross_v2 = True

    @app.post("/v1/horary-prashna/cross-interpretation")
    def cross_interpretation(req: CrossInterpretationRequest):
        try:
            return build_cross_interpretation_compat(req.horary, req.prashna)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
