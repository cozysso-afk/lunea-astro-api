from __future__ import annotations

"""Process-isolated, persistent Horary V6 canary execution.

V6 mutates module-level Horary hooks at import time, so the production API
worker must never import it. A spawned child interpreter owns V6 and stays alive
between canary requests; per-request performance caches are cleared before each
calculation so only process/module/ephemeris warm state is reused.
"""

import atexit
import multiprocessing as mp
import queue
import time
import uuid
from threading import Lock
from typing import Any


_CANARY_LOCK = Lock()
_CTX = mp.get_context("spawn")
_worker = None
_request_queue = None
_response_queue = None


def _worker_main(request_queue, response_queue) -> None:
    # All mutation-heavy Horary imports are deliberately child-only.
    import horary_topic_routes_v3  # noqa: F401
    import horary_engine_v6 as v6
    import horary_balance_v31 as v31
    import horary_performance_v2 as perf2
    import horary_performance_v1 as perf1

    while True:
        item = request_queue.get()
        if item is None:
            return

        request_id, payload = item
        try:
            perf2.clear_caches()
            perf1.clear_caches()
            started = time.perf_counter()
            result = v31.compute_horary(**payload)
            compute_seconds = time.perf_counter() - started
            engine = ((result.get("meta") or {}).get("horary_engine"))
            if engine != v6.VERSION:
                raise RuntimeError(f"unexpected canary engine: {engine!r}")
            response_queue.put(
                {
                    "request_id": request_id,
                    "ok": True,
                    "result": result,
                    "worker_compute_seconds": compute_seconds,
                }
            )
        except Exception as exc:
            response_queue.put(
                {
                    "request_id": request_id,
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )


def _reset_worker() -> None:
    global _worker, _request_queue, _response_queue
    worker = _worker
    _worker = None
    _request_queue = None
    _response_queue = None

    if worker is not None and worker.is_alive():
        worker.terminate()
        worker.join(timeout=2.0)


def _ensure_worker() -> bool:
    global _worker, _request_queue, _response_queue
    if _worker is not None and _worker.is_alive():
        return False

    _reset_worker()
    _request_queue = _CTX.Queue(maxsize=1)
    _response_queue = _CTX.Queue(maxsize=1)
    _worker = _CTX.Process(
        target=_worker_main,
        args=(_request_queue, _response_queue),
        name="lunea-horary-v6-canary",
        daemon=True,
    )
    _worker.start()
    return True


def shutdown_horary_v6_canary_worker() -> None:
    with _CANARY_LOCK:
        _reset_worker()


def compute_horary_v6_canary(payload: dict[str, Any], timeout_seconds: float = 90.0) -> dict:
    with _CANARY_LOCK:
        worker_started = _ensure_worker()
        request_id = uuid.uuid4().hex
        _request_queue.put((request_id, payload))

        try:
            response = _response_queue.get(timeout=float(timeout_seconds))
        except queue.Empty as exc:
            _reset_worker()
            raise TimeoutError(f"V6 canary exceeded {float(timeout_seconds):.1f}s") from exc

        if response.get("request_id") != request_id:
            _reset_worker()
            raise RuntimeError("V6 canary response id mismatch")

        if not response.get("ok"):
            error = response.get("error") or "unknown child error"
            raise RuntimeError(f"V6 canary child failed: {error}")

        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("V6 canary child result must be an object")

        return {
            "result": result,
            "worker_started": worker_started,
            "worker_compute_seconds": float(response.get("worker_compute_seconds") or 0.0),
        }


atexit.register(shutdown_horary_v6_canary_worker)
