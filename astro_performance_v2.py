from __future__ import annotations

"""LUNEA Astro Core performance hotfix V2.

Keeps calculation semantics intact while reducing repeated ephemeris work:
- Transit motion vectors are evaluated in one Skyfield vector batch per body
  instead of three separate batches (past / now / future).
- Return searches use wider *bracketing* grids. Exact crossing times are still
  refined by the existing bisection/minimum-orb routines after a bracket is
  found, so the final return timestamp precision is unchanged.
"""

from datetime import timedelta

import numpy as np

import astro_core as core


RETURN_STEP_HOURS = {
    "Moon": 4.0,
    "Sun": 24.0,
    "Mercury": 12.0,
    "Venus": 24.0,
    "Mars": 24.0,
    "Jupiter": 96.0,
    "Saturn": 192.0,
}


def _motion_arrays_batched(body, sample_times):
    h = 0.25 if body == "Moon" else 1.0 if body in {"Sun", "Mercury", "Venus", "Mars"} else 6.0
    n = len(sample_times)
    if not n:
        empty = np.array([], dtype=float)
        return empty, empty, empty, empty

    past_times = [d - timedelta(hours=h) for d in sample_times]
    future_times = [d + timedelta(hours=h) for d in sample_times]

    # One vectorized Skyfield observation is materially cheaper on Render's
    # small CPU instances than three separate observations of the same body.
    combined = past_times + list(sample_times) + future_times
    values = np.ravel(core.get_tropical_ecliptic_lons(body, combined))
    if values.size != n * 3:
        raise ValueError(
            f"{body} transit vector size mismatch: combined={values.size}, samples={n}"
        )

    past = values[:n]
    now = values[n : 2 * n]
    future = values[2 * n :]

    speed = (future - past + 180.0) % 360.0 - 180.0
    speed = np.ravel(speed / ((2 * h) / 24.0))
    return now, past, future, speed


def install():
    core._motion_arrays = _motion_arrays_batched
    for body, step_hours in RETURN_STEP_HOURS.items():
        if body in core.RETURN_CONFIG_V1:
            core.RETURN_CONFIG_V1[body]["step_hours"] = float(step_hours)


install()
