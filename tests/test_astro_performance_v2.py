from datetime import datetime, timezone

import numpy as np

import astro_core as core
import astro_performance_v2 as perf


def test_transit_motion_uses_one_vector_batch(monkeypatch):
    calls = []

    def fake_lons(body, times):
        calls.append((body, list(times)))
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return np.array([
            ((dt - base).total_seconds() / 86400.0) % 360.0
            for dt in times
        ])

    monkeypatch.setattr(core, "get_tropical_ecliptic_lons", fake_lons)
    samples = [
        datetime(2026, 1, 3, tzinfo=timezone.utc),
        datetime(2026, 1, 4, tzinfo=timezone.utc),
    ]

    now, past, future, speed = perf._motion_arrays_batched("Sun", samples)

    assert len(calls) == 1
    assert len(calls[0][1]) == len(samples) * 3
    assert now.shape == past.shape == future.shape == speed.shape == (2,)
    assert np.allclose(speed, np.array([1.0, 1.0]))


def test_return_grid_keeps_original_full_density():
    expected = {
        "Moon": 1.0,
        "Sun": 12.0,
        "Mercury": 6.0,
        "Venus": 12.0,
        "Mars": 12.0,
        "Jupiter": 48.0,
        "Saturn": 96.0,
    }
    for body, step in expected.items():
        assert core.RETURN_CONFIG_V1[body]["step_hours"] == step

    assert callable(core._bisect_return_crossing)
    assert callable(core._refine_minimum_orb)
