from __future__ import annotations

import time
from unittest.mock import patch

import astro_jobs_v1 as jobs
from astro_job_api import app


def _seed(job_id: str, kind: str = "horary") -> None:
    now = time.time()
    jobs._jobs[job_id] = {
        "job_id": job_id,
        "kind": kind,
        "status": "queued",
        "created_at": jobs._now_iso(),
        "created_ts": now,
        "updated_ts": now,
        "started_at": None,
        "finished_at": None,
        "result": None,
        "error": None,
    }


def test_job_routes_are_installed():
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/v1/jobs/astro" in paths
    assert "/v1/jobs/astro/{job_id}" in paths


def test_job_success_keeps_result_for_reconnect():
    job_id = "unit-success"
    _seed(job_id)
    with patch.object(jobs, "_compute", return_value={"schema": "OK", "value": 7}):
        jobs._run(job_id, "horary", {"question_text": "테스트"})
    row = jobs._jobs[job_id]
    assert row["status"] == "done"
    assert row["result"] == {"schema": "OK", "value": 7}
    assert row["error"] is None


def test_job_failure_keeps_error_for_reconnect():
    job_id = "unit-error"
    _seed(job_id, "return")
    with patch.object(jobs, "_compute", side_effect=ValueError("bad payload")):
        jobs._run(job_id, "return", {})
    row = jobs._jobs[job_id]
    assert row["status"] == "error"
    assert "ValueError: bad payload" in row["error"]
    assert row["result"] is None
