from __future__ import annotations

"""Process-isolated Horary V6 canary execution.

Importing Horary V6 mutates module-level calculation hooks. Production V5 must
therefore never import V6 in the API worker. This helper launches V6 in a child
Python interpreter and returns only the child's JSON result.
"""

import json
import subprocess
import sys
from threading import Lock
from typing import Any


_CANARY_LOCK = Lock()


def compute_horary_v6_canary(payload: dict[str, Any], timeout_seconds: float = 90.0) -> dict:
    try:
        with _CANARY_LOCK:
            proc = subprocess.run(
                [sys.executable, "-m", "horary_canary_runner_v6"],
                input=json.dumps(payload, ensure_ascii=False),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=float(timeout_seconds),
                check=False,
            )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"V6 canary exceeded {float(timeout_seconds):.1f}s") from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"V6 canary child failed ({proc.returncode}): {detail[-1200:]}")

    lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("V6 canary child returned no JSON")

    try:
        result = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"V6 canary child returned invalid JSON: {lines[-1][-1200:]}") from exc

    if not isinstance(result, dict):
        raise RuntimeError("V6 canary child result must be an object")
    return result
