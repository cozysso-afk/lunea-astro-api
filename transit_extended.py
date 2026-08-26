from __future__ import annotations

from datetime import timedelta

import numpy as np

import astro_core as core


MAX_TRANSIT_DAYS = 365


def scan_transits_extended(
    natal,
    topic="general",
    start_iso=None,
    days=30,
    timezone_name="Asia/Seoul",
):
    """LUNEA Transit Scanner extended to one year.

    This intentionally reuses the tested scoring/refinement helpers from
    astro_core. For ranges longer than 45 days the existing adaptive grid is
    already 24 hours, so extending 120 -> 365 days remains bounded while the
    near-exact refinement still uses the core's body-specific grid.
    """
    days = int(days)
    if days < 1 or days > MAX_TRANSIT_DAYS:
        raise ValueError(f"트랜짓 스캔 기간은 1~{MAX_TRANSIT_DAYS}일이어야 합니다.")

    topic_key, spec = core._topic_spec(topic)
    targets, asc_lon, placidus_cusps = core._natal_payload_parts(natal)

    start_dt = core._as_aware_utc(start_iso)
    end_dt = start_dt + timedelta(days=days)
    step_hours = core._adaptive_step_hours(days)
    sample_times = core._sample_datetimes(start_dt, end_dt, step_hours)

    body_rows = {}
    for body in core._transit_bodies_for_topic(spec):
        now, past, future, speed = core._motion_arrays(body, sample_times)
        body_rows[body] = {
            "now": now,
            "past": past,
            "future": future,
            "speed": speed,
        }

    samples = []
    for idx, dt in enumerate(sample_times):
        scored = core._score_sample(
            topic_key,
            spec,
            targets,
            asc_lon,
            placidus_cusps,
            body_rows,
            idx,
        )
        samples.append({"dt_utc": dt, **scored})

    max_activation = max((s["activation"] for s in samples), default=0)
    percentile75 = (
        float(np.percentile([s["activation"] for s in samples], 75))
        if samples
        else 0
    )
    peak_threshold = max(
        45.0,
        min(float(max_activation), max(percentile75, max_activation * 0.72)),
    )
    if max_activation < 45:
        peak_threshold = max_activation + 1

    peak_windows = core._windowize(
        samples,
        peak_threshold,
        step_hours,
        timezone_name,
        caution=False,
    )
    caution_threshold = max(40.0, max_activation * 0.60)
    caution_windows = core._windowize(
        samples,
        caution_threshold,
        step_hours,
        timezone_name,
        caution=True,
    )

    strongest_samples = sorted(
        samples,
        key=lambda x: (x["activation"], x["favorability"]),
        reverse=True,
    )[:5]

    exact_hits = core._find_exact_hits(
        spec,
        targets,
        asc_lon,
        start_dt,
        end_dt,
        days,
        timezone_name,
    )

    timeline = [
        {
            "time": core._iso_local(s["dt_utc"], timezone_name),
            "activation": s["activation"],
            "favorability": s["favorability"],
        }
        for s in samples
    ]

    overall = {
        "max_activation": max_activation,
        "average_activation": (
            int(round(np.mean([s["activation"] for s in samples])))
            if samples
            else 0
        ),
        "average_favorability": (
            int(round(np.mean([s["favorability"] for s in samples])))
            if samples
            else 50
        ),
        "strong_signal": bool(max_activation >= 45),
    }

    top_points = [
        {
            "time": core._iso_local(s["dt_utc"], timezone_name),
            "activation": s["activation"],
            "favorability": s["favorability"],
            "evidence": core._summarize_evidence(s["evidence"]),
        }
        for s in strongest_samples
    ]

    return {
        "schema": "LUNEA_TRANSIT_SCAN_V1",
        "topic": topic_key,
        "topic_label": spec["label"],
        "range": {
            "start": core._iso_local(start_dt, timezone_name),
            "end": core._iso_local(end_dt, timezone_name),
            "days": days,
            "timezone": timezone_name,
            "sample_step_hours": step_hours,
        },
        "overall": overall,
        "peak_windows": peak_windows[:5],
        "caution_windows": caution_windows[:4],
        "exact_hits": exact_hits,
        "top_points": top_points,
        "timeline": timeline,
        "rules": {
            "zodiac": "tropical",
            "house_primary": "whole_sign",
            "house_secondary": "placidus",
            "note": (
                "Transit activation is a timing/activation signal, "
                "not a guaranteed event outcome."
            ),
        },
    }
