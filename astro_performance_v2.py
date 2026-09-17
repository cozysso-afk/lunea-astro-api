from __future__ import annotations

"""LUNEA Astro Core performance hotfix V2.

Reduces repeated ephemeris work without reducing the calculation search space:
- Transit motion vectors are evaluated in one Skyfield vector batch per body
  instead of three separate batches (past / now / future).
- Return search density is deliberately left untouched so retrograde/stationary
  edge cases retain the original detection coverage.
"""

from datetime import timedelta

import numpy as np

import astro_core as core


def _motion_arrays_batched(body, sample_times):
    h = 0.25 if body == "Moon" else 1.0 if body in {"Sun", "Mercury", "Venus", "Mars"} else 6.0
    n = len(sample_times)
    if not n:
        empty = np.array([], dtype=float)
        return empty, empty, empty, empty

    past_times = [d - timedelta(hours=h) for d in sample_times]
    future_times = [d + timedelta(hours=h) for d in sample_times]

    # One vectorized Skyfield observation is materially cheaper on small CPU
    # instances than three separate observations of the same body. The exact
    # same timestamps are evaluated; only the call batching changes.
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
    # Performance-only patch: do not alter RETURN_CONFIG_V1 or any search grid.
    core._motion_arrays = _motion_arrays_batched


install()
