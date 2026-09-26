from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import horary_topic_routes_v3  # noqa: E402,F401  # activates V4 -> V5 -> V6 -> V7 -> V8
import horary_balance_v31 as v31  # noqa: E402

VERSION = "LUNEA_HORARY_V8_REALQA_V1"

LOCATIONS = {
    "seoul": {"place": "Seoul", "timezone": "Asia/Seoul", "lat": 37.5665, "lon": 126.9780},
    "london": {"place": "London", "timezone": "Europe/London", "lat": 51.5074, "lon": -0.1278},
}

# Natural-language questions representative of the product's high-use judgment families.
QUESTIONS = {
    "contact": "그 사람이 이번 주 안에 나에게 먼저 연락할까요?",
    "reconciliation": "우리가 다시 연인으로 만날 수 있을까요?",
    "relationship": "이 사람과의 관계가 실제 연애로 이어질까요?",
    "career": "이번 지원에서 이 회사에 실제로 채용될까요?",
    "contract": "이 계약이 실제로 체결될까요?",
}

# Four calendar anchors x two locations = eight real ephemeris moments per topic.
# Hours are deliberately mixed rather than sampling only one local daypart.
MOMENTS = [
    ("2026-01-15", "09:00"),
    ("2026-03-20", "21:00"),
    ("2026-06-10", "14:00"),
    ("2026-09-24", "18:30"),
]


def band(raw) -> str:
    text = str(raw or "NONE")
    for prefix in ("A", "B", "C", "D"):
        if text.startswith(prefix):
            return prefix
    return "NONE"


def compute_cell(topic: str, location_key: str, date_s: str, time_s: str) -> dict:
    loc = LOCATIONS[location_key]
    tz = ZoneInfo(loc["timezone"])
    local_dt = datetime.fromisoformat(f"{date_s}T{time_s}").replace(tzinfo=tz)
    data = v31.compute_horary(
        question_text=QUESTIONS[topic],
        question_iso=local_dt.isoformat(),
        topic=topic,
        timezone_name=loc["timezone"],
        place=loc["place"],
        lat=loc["lat"],
        lon=loc["lon"],
    )
    j = data.get("judgment_support") or {}
    v7 = j.get("traditional_core_v7") or {}
    v8 = j.get("judgment_hierarchy_v8") or {}
    route = j.get("route_contract_v7") or {}

    if not v8:
        raise AssertionError("V8 judgment hierarchy missing from live calculation chain")
    if route and route.get("matches_spec") is not True:
        raise AssertionError(f"route contract mismatch for {topic}: {route}")

    g7 = str(v7.get("qualified_evidence_grade_v7") or v7.get("evidence_grade") or "NONE")
    g8 = str(v8.get("qualified_evidence_grade_v8") or "NONE")
    b7, b8 = band(g7), band(g8)
    moon = v8.get("moon_event_testimony_v8") or {}
    reception = v8.get("intention_reception_v8") or {}
    action = v8.get("action_state_v8") or {}
    source = str(v8.get("grade_source_v8") or "")

    # Regression invariants: V8 may add only the narrow Moon co-significator C channel.
    if b7 in {"A", "B", "C"} and b8 != b7:
        raise AssertionError(f"V8 changed established {b7} evidence: {topic} {g7} -> {g8}")
    if b7 in {"D", "NONE"} and b8 == "C":
        if source != "moon_co_significator_event_testimony":
            raise AssertionError(f"unexpected V8 promotion source: {source}")
        if moon.get("confirmed") is not True:
            raise AssertionError("V8 C promotion without confirmed Moon event testimony")
        if moon.get("target_role") not in {"quesited", "event"}:
            raise AssertionError(f"V8 Moon promotion targeted invalid role: {moon.get('target_role')}")
    if b7 in {"D", "NONE"} and not moon.get("confirmed") and b8 != b7:
        raise AssertionError(f"unconfirmed Moon changed band: {topic} {g7} -> {g8}")
    if moon.get("target_role") == "querent" and b7 in {"D", "NONE"} and b8 == "C":
        raise AssertionError("Moon-to-querent was incorrectly promoted to C")
    if b8 == "D" and str(v8.get("overall_state_v8")) == "event_supported":
        raise AssertionError("D band cannot be presented as confirmed event support")

    direct = bool(((v7.get("direct_axis") or {}).get("perfection") or {}).get("perfects"))
    event_axes = v8.get("event_axes_v8") or {}
    indirect = v8.get("indirect_v8") or {}

    return {
        "topic": topic,
        "question": QUESTIONS[topic],
        "location": location_key,
        "local_iso": local_dt.isoformat(),
        "v7_grade": g7,
        "v7_band": b7,
        "v8_grade": g8,
        "v8_band": b8,
        "promoted": b7 in {"D", "NONE"} and b8 == "C",
        "grade_source_v8": source,
        "direct_perfection": direct,
        "derived_event_perfection": bool(event_axes.get("has_perfection")),
        "indirect_perfection": bool(indirect.get("present")),
        "reception_state": str(reception.get("state") or "none"),
        "moon_confirmed": bool(moon.get("confirmed")),
        "moon_target_role": moon.get("target_role"),
        "moon_tone": moon.get("tone"),
        "action_state": action.get("state"),
        "overall_state": v8.get("overall_state_v8"),
    }


def summarize(rows: list[dict]) -> dict:
    out = {}
    for topic in QUESTIONS:
        xs = [r for r in rows if r["topic"] == topic]
        out[topic] = {
            "n": len(xs),
            "v7_bands": dict(Counter(r["v7_band"] for r in xs)),
            "v8_bands": dict(Counter(r["v8_band"] for r in xs)),
            "v8_promotions": sum(r["promoted"] for r in xs),
            "direct": sum(r["direct_perfection"] for r in xs),
            "derived_event": sum(r["derived_event_perfection"] for r in xs),
            "indirect": sum(r["indirect_perfection"] for r in xs),
            "reception_non_none": sum(r["reception_state"] != "none" for r in xs),
            "moon_confirmed": sum(r["moon_confirmed"] for r in xs),
            "action_states": dict(Counter(str(r["action_state"]) for r in xs)),
            "overall_states": dict(Counter(str(r["overall_state"]) for r in xs)),
        }
    return out


def render(payload: dict) -> str:
    lines = [
        "# HORARY V8 REAL-CHART QA",
        "",
        f"- version: `{payload['version']}`",
        f"- cells: **{payload['meta']['cells']}**",
        "- purpose: compare legacy V7 authoritative bands with V8 on real ephemeris charts while guarding against both negative flattening and artificial optimism.",
        "- this is implementation QA, not an observed-outcome accuracy study and not a target-ratio calibration.",
        "",
        "## V7 → V8 band distribution",
        "",
        "| Topic | N | V7 A/B/C/D/NONE | V8 A/B/C/D/NONE | narrow Moon promotions | direct | derived | indirect | Moon confirmed |",
        "|---|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    for topic, row in payload["summary"].items():
        def fmt(key):
            d = row[key]
            return "/".join(str(d.get(x, 0)) for x in ("A", "B", "C", "D", "NONE"))
        lines.append(
            f"| {topic} | {row['n']} | {fmt('v7_bands')} | {fmt('v8_bands')} | "
            f"{row['v8_promotions']} | {row['direct']} | {row['derived_event']} | {row['indirect']} | {row['moon_confirmed']} |"
        )

    promotions = [r for r in payload["cells"] if r["promoted"]]
    lines += ["", "## V8-only promotions", ""]
    if not promotions:
        lines.append("No D/NONE → C promotions occurred in this fixed matrix.")
    else:
        lines += [
            "Every row below is required by the script to have confirmed Moon testimony targeting only the quesited or routed event ruler.",
            "",
            "| Topic | Location | Local time | V7 | V8 | Moon target | tone |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in promotions:
            lines.append(
                f"| {r['topic']} | {r['location']} | {r['local_iso']} | {r['v7_grade']} | {r['v8_grade']} | "
                f"{r['moon_target_role']} | {r['moon_tone']} |"
            )

    lines += [
        "",
        "## Guardrails exercised",
        "",
        "- Existing V7 A/B/C evidence may not be downgraded or replaced by V8.",
        "- D/NONE may become C only through confirmed Moon co-significator application to the quesited/event ruler.",
        "- Moon applying only to the querent cannot promote the result.",
        "- Unconfirmed/irrelevant Moon movement cannot alter a D/NONE band.",
        "- D remains unperfected and cannot be labeled as confirmed event support.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    rows: list[dict] = []
    failures: list[str] = []
    total = len(QUESTIONS) * len(LOCATIONS) * len(MOMENTS)
    done = 0
    for topic in QUESTIONS:
        for location in LOCATIONS:
            for date_s, time_s in MOMENTS:
                done += 1
                try:
                    rows.append(compute_cell(topic, location, date_s, time_s))
                except Exception as exc:
                    failures.append(f"{topic}/{location}/{date_s}T{time_s}: {type(exc).__name__}: {exc}")
                print(f"REALQA_PROGRESS {done}/{total}", flush=True)

    if failures:
        raise AssertionError("\n".join(failures))

    payload = {
        "version": VERSION,
        "meta": {
            "cells": len(rows),
            "topics": list(QUESTIONS),
            "locations": list(LOCATIONS),
            "moments": [f"{d}T{t}" for d, t in MOMENTS],
        },
        "summary": summarize(rows),
        "cells": rows,
    }
    out = Path("audit-output")
    out.mkdir(exist_ok=True)
    (out / "horary-v8-realqa.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report = render(payload)
    (out / "horary-v8-realqa.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
