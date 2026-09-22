from __future__ import annotations

"""Resumable long-running Astro jobs for LUNEA.

The browser starts a calculation quickly, stores the returned job id, and then
polls this API. The calculation continues on the server even while iOS suspends
the PWA. Results are kept in memory long enough for the client to reconnect.

Long Transit / Return scans are CPU-bound on the current Render plan. Running
several of them in parallel can saturate the service and starve interactive
Horary requests, so background jobs are intentionally serialized here.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import re
import secrets
import threading
import time
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field

from astro_core import calculate_return_context
import horary_topic_routes_v3  # noqa: F401 - installs the production Horary chain
from horary_balance_v31 import compute_horary
from transit_extended import MAX_TRANSIT_DAYS, scan_transits_extended


JOB_TTL_SECONDS = 60 * 45
MAX_JOBS = 64
# Keep exactly one background calculation active on this CPU-limited service.
# Interactive Horary now uses /v1/horary directly and must not be starved by
# three simultaneous background scans.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lunea-astro-job")
_lock = threading.RLock()
_jobs: dict[str, dict[str, Any]] = {}
_router = APIRouter()
_installed = False


class AstroJobRequest(BaseModel):
    kind: str = Field(..., min_length=3, max_length=16)
    payload: dict[str, Any]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coordinates_from_place(place: Any) -> tuple[float | None, float | None]:
    """Recover coordinates from labels such as '현재 위치 (34.7594, 127.6530)'."""
    raw = str(place or "").strip()
    if not raw:
        return None, None
    match = re.search(
        r"\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)",
        raw,
    )
    if not match:
        return None, None
    lat = float(match.group(1))
    lon = float(match.group(2))
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None, None
    return lat, lon


def _cleanup_locked() -> None:
    now = time.time()
    expired = [
        job_id for job_id, row in _jobs.items()
        if now - float(row.get("updated_ts") or row.get("created_ts") or now) > JOB_TTL_SECONDS
    ]
    for job_id in expired:
        _jobs.pop(job_id, None)

    if len(_jobs) > MAX_JOBS:
        removable = sorted(
            _jobs.items(),
            key=lambda item: float(item[1].get("updated_ts") or item[1].get("created_ts") or 0),
        )
        for job_id, row in removable:
            if len(_jobs) <= MAX_JOBS:
                break
            if row.get("status") in {"done", "error"}:
                _jobs.pop(job_id, None)


def _compute(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind == "horary":
        question_text = str(payload.get("question_text") or "").strip()
        question_iso = str(payload.get("question_iso") or "").strip()
        if len(question_text) < 2:
            raise ValueError("질문 원문이 비어 있습니다.")
        if not question_iso:
            raise ValueError("질문 시각이 비어 있습니다.")

        lat = payload.get("lat")
        lon = payload.get("lon")
        if lat is None or lon is None:
            parsed_lat, parsed_lon = _coordinates_from_place(payload.get("place"))
            if lat is None:
                lat = parsed_lat
            if lon is None:
                lon = parsed_lon

        return compute_horary(
            question_text=question_text,
            question_iso=question_iso,
            topic=str(payload.get("topic") or "general"),
            timezone_name=str(payload.get("timezone") or "Asia/Seoul"),
            place=payload.get("place"),
            lat=lat,
            lon=lon,
        )

    if kind == "transit":
        natal = payload.get("natal")
        if not isinstance(natal, dict) or not natal:
            raise ValueError("출생차트 정보가 비어 있습니다.")
        days = int(payload.get("days") or 30)
        if days < 1 or days > MAX_TRANSIT_DAYS:
            raise ValueError(f"트랜짓 기간은 1~{MAX_TRANSIT_DAYS}일이어야 합니다.")
        return scan_transits_extended(
            natal=natal,
            topic=str(payload.get("topic") or "general"),
            start_iso=payload.get("start_iso"),
            days=days,
            timezone_name=str(payload.get("timezone") or "Asia/Seoul"),
        )

    if kind == "return":
        natal = payload.get("natal")
        if not isinstance(natal, dict) or not natal:
            raise ValueError("출생차트 정보가 비어 있습니다.")
        bodies = payload.get("bodies") or ["Sun", "Moon"]
        if not isinstance(bodies, list) or not bodies:
            raise ValueError("리턴 천체를 하나 이상 선택해야 합니다.")
        return calculate_return_context(
            natal=natal,
            bodies=[str(body) for body in bodies],
            center_iso=payload.get("center_iso"),
            timezone_name=str(payload.get("timezone") or "Asia/Seoul"),
            place=payload.get("place"),
            lat=payload.get("lat"),
            lon=payload.get("lon"),
        )

    raise ValueError(f"지원하지 않는 Astro job 종류입니다: {kind}")


def _run(job_id: str, kind: str, payload: dict[str, Any]) -> None:
    with _lock:
        row = _jobs.get(job_id)
        if not row:
            return
        row["status"] = "running"
        row["started_at"] = _now_iso()
        row["updated_ts"] = time.time()

    try:
        result = _compute(kind, payload)
        with _lock:
            row = _jobs.get(job_id)
            if not row:
                return
            row["status"] = "done"
            row["result"] = result
            row["error"] = None
            row["finished_at"] = _now_iso()
            row["updated_ts"] = time.time()
    except Exception as exc:
        with _lock:
            row = _jobs.get(job_id)
            if not row:
                return
            row["status"] = "error"
            row["result"] = None
            row["error"] = f"{type(exc).__name__}: {exc}"
            row["finished_at"] = _now_iso()
            row["updated_ts"] = time.time()


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": row["job_id"],
        "kind": row["kind"],
        "status": row["status"],
        "created_at": row["created_at"],
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "result": row.get("result") if row.get("status") == "done" else None,
        "error": row.get("error") if row.get("status") == "error" else None,
    }


@_router.post("/v1/jobs/astro", status_code=202)
def create_astro_job(req: AstroJobRequest):
    kind = str(req.kind or "").strip().lower()
    if kind not in {"horary", "transit", "return"}:
        raise HTTPException(status_code=422, detail="지원하지 않는 Astro job 종류입니다.")

    job_id = secrets.token_urlsafe(12)
    now = time.time()
    row = {
        "job_id": job_id,
        "kind": kind,
        "status": "queued",
        "created_at": _now_iso(),
        "created_ts": now,
        "updated_ts": now,
        "started_at": None,
        "finished_at": None,
        "result": None,
        "error": None,
    }
    with _lock:
        _cleanup_locked()
        _jobs[job_id] = row

    _executor.submit(_run, job_id, kind, dict(req.payload))
    return _public(row)


@_router.get("/v1/jobs/astro/{job_id}")
def get_astro_job(job_id: str):
    with _lock:
        _cleanup_locked()
        row = _jobs.get(job_id)
        if not row:
            raise HTTPException(status_code=404, detail="계산 작업을 찾지 못했습니다. 다시 계산해 주세요.")
        return _public(row)


def install_astro_jobs(app: FastAPI) -> FastAPI:
    global _installed
    if _installed:
        return app
    app.include_router(_router)
    _installed = True
    return app
