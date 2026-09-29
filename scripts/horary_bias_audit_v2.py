from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import horary_topic_routes_v3  # noqa: F401  # activates current V6/V7 helpers
import horary_balance_v31 as v31

VERSION = "LUNEA_HORARY_BIAS_AUDIT_V2_FULL_EVIDENCE"

LOCATIONS = {
    "seoul": {"place": "Seoul", "timezone": "Asia/Seoul", "lat": 37.5665, "lon": 126.9780},
    "london": {"place": "London", "timezone": "Europe/London", "lat": 51.5074, "lon": -0.1278},
}

QUESTIONS = {
    "general": "이 일은 성사될까요?",
    "contact": "그 사람이 나에게 먼저 연락할까요?",
    "reconciliation": "그 사람과 다시 만날 수 있을까요?",
}


def pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 1) if d else 0.0


def even_dates(start: date, end: date, count: int) -> list[date]:
    if count <= 1:
        return [start + timedelta(days=(end - start).days // 2)]
    span = (end - start).days
    return [start + timedelta(days=round(span * i / (count - 1))) for i in range(count)]


def band(raw) -> str:
    text = str(raw or "NONE")
    if text.startswith("A"):
        return "A"
    return text if text in {"B", "C", "D", "NONE"} else "OTHER"


def axis_perfects(row: dict | None) -> bool:
    return bool(((row or {}).get("perfection") or {}).get("perfects"))


def classify_cell(topic: str, location_key: str, local_dt: datetime) -> dict:
    loc = LOCATIONS[location_key]
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
    c = j.get("traditional_core_v7") or j.get("traditional_core_v6") or {}
    b = j.get("balance_v31") or {}

    direct = bool((j.get("perfection") or {}).get("perfects"))
    derived = c.get("derived_event_axes") or {}
    q_to_event = axis_perfects(derived.get("quesited_to_event"))
    event_to_q = axis_perfects(derived.get("event_to_querent"))
    event_any = bool(q_to_event or event_to_q)

    indirect = b.get("indirect_perfection") or {}
    translations = indirect.get("translation_of_light") or []
    collections = indirect.get("collection_of_light") or []
    indirect_any = bool(translations or collections)

    reception = b.get("reception_v31") or {}
    reception_grade = str(reception.get("grade") or "none")
    reception_any = reception_grade not in {"none", "None", ""}

    moon = j.get("moon_relevance_v7") or c.get("moon_relevance_v7") or {}
    moon_relevant = bool(moon.get("question_relevant"))

    confirmed = b.get("confirmed_obstructions") or {}
    obstruction = bool((confirmed.get("prohibition_or_frustration") or []) or confirmed.get("refranation"))

    grade = c.get("qualified_evidence_grade_v7") or c.get("evidence_grade") or "NONE"
    grade_band = band(grade)

    if direct:
        primary_channel = "direct"
    elif indirect_any:
        primary_channel = "indirect"
    elif event_any:
        primary_channel = "derived_event"
    elif reception_any:
        primary_channel = "reception_only"
    elif moon_relevant:
        primary_channel = "moon_only"
    else:
        primary_channel = "none"

    return {
        "topic": topic,
        "location": location_key,
        "local_iso": local_dt.isoformat(),
        "grade": str(grade),
        "grade_band": grade_band,
        "tier": str(b.get("tier") or "unknown"),
        "direct": direct,
        "derived_quesited_to_event": q_to_event,
        "derived_event_to_querent": event_to_q,
        "derived_any": event_any,
        "translation": bool(translations),
        "collection": bool(collections),
        "indirect_any": indirect_any,
        "reception_grade": reception_grade,
        "reception_any": reception_any,
        "moon_relevant": moon_relevant,
        "confirmed_obstruction": obstruction,
        "primary_channel": primary_channel,
        "direct_negative_rescued_by_BC": (not direct and grade_band in {"B", "C"}),
        "direct_negative_soft_only": (not direct and grade_band == "D"),
        "direct_negative_none": (not direct and grade_band == "NONE"),
    }


def summarize(rows: list[dict], topic: str) -> dict:
    xs = [x for x in rows if x["topic"] == topic]
    n = len(xs)
    direct_n = sum(x["direct"] for x in xs)
    no_direct = n - direct_n
    rescued = sum(x["direct_negative_rescued_by_BC"] for x in xs)
    soft_only = sum(x["direct_negative_soft_only"] for x in xs)
    none = sum(x["direct_negative_none"] for x in xs)
    event_any = sum(x["derived_any"] for x in xs)
    indirect_any = sum(x["indirect_any"] for x in xs)
    reception_any = sum(x["reception_any"] for x in xs)
    moon_relevant = sum(x["moon_relevant"] for x in xs)
    obstruction = sum(x["confirmed_obstruction"] for x in xs)

    return {
        "n": n,
        "grades": dict(Counter(x["grade_band"] for x in xs)),
        "tiers": dict(Counter(x["tier"] for x in xs)),
        "channels": dict(Counter(x["primary_channel"] for x in xs)),
        "direct": direct_n,
        "direct_pct": pct(direct_n, n),
        "no_direct": no_direct,
        "no_direct_pct": pct(no_direct, n),
        "rescued_BC": rescued,
        "rescued_pct_of_no_direct": pct(rescued, no_direct),
        "soft_D": soft_only,
        "soft_D_pct_of_no_direct": pct(soft_only, no_direct),
        "none": none,
        "none_pct_of_no_direct": pct(none, no_direct),
        "derived_any": event_any,
        "derived_any_pct": pct(event_any, n),
        "quesited_to_event": sum(x["derived_quesited_to_event"] for x in xs),
        "event_to_querent": sum(x["derived_event_to_querent"] for x in xs),
        "indirect_any": indirect_any,
        "indirect_any_pct": pct(indirect_any, n),
        "translation": sum(x["translation"] for x in xs),
        "collection": sum(x["collection"] for x in xs),
        "reception_any": reception_any,
        "reception_any_pct": pct(reception_any, n),
        "moon_relevant": moon_relevant,
        "moon_relevant_pct": pct(moon_relevant, n),
        "confirmed_obstruction": obstruction,
        "confirmed_obstruction_pct": pct(obstruction, n),
    }


def render(payload: dict) -> str:
    lines = [
        "# HORARY BIAS AUDIT V2 · full evidence hierarchy",
        "",
        f"- full-engine cells: **{payload['meta']['cells']}**",
        f"- dates: {', '.join(payload['meta']['dates'])}",
        f"- hours: {', '.join(map(str, payload['meta']['hours']))}",
        f"- locations: {', '.join(payload['meta']['locations'])}",
        f"- topics: {', '.join(payload['meta']['topics'])}",
        "",
        "This audit asks a different question from V1: when direct perfection is absent, how often do the current derived-event / Translation-Collection / reception layers recover meaningful evidence, and how often does the final authoritative band remain D or NONE?",
        "",
        "## Final authoritative bands",
        "",
        "| Topic | N | A | B | C | D | NONE | direct | no direct | B/C rescue among no-direct |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for topic, row in payload["summary"].items():
        g = row["grades"]
        lines.append(
            f"| {topic} | {row['n']} | {g.get('A', 0)} | {g.get('B', 0)} | {g.get('C', 0)} | {g.get('D', 0)} | {g.get('NONE', 0)} | "
            f"{row['direct']} ({row['direct_pct']}%) | {row['no_direct']} ({row['no_direct_pct']}%) | "
            f"{row['rescued_BC']} ({row['rescued_pct_of_no_direct']}%) |"
        )

    lines += [
        "",
        "## Evidence channels",
        "",
        "| Topic | derived any | quesited→event | event→querent | indirect any | translation | collection | reception any | Moon relevant | confirmed obstruction |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for topic, row in payload["summary"].items():
        lines.append(
            f"| {topic} | {row['derived_any']} ({row['derived_any_pct']}%) | {row['quesited_to_event']} | {row['event_to_querent']} | "
            f"{row['indirect_any']} ({row['indirect_any_pct']}%) | {row['translation']} | {row['collection']} | "
            f"{row['reception_any']} ({row['reception_any_pct']}%) | {row['moon_relevant']} ({row['moon_relevant_pct']}%) | "
            f"{row['confirmed_obstruction']} ({row['confirmed_obstruction_pct']}%) |"
        )

    lines += [
        "",
        "## What happens after direct perfection is absent?",
        "",
        "| Topic | no-direct N | B/C recovered | D soft-only | NONE | primary-channel mix |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for topic, row in payload["summary"].items():
        mix = ", ".join(f"{k}={v}" for k, v in sorted(row["channels"].items()))
        lines.append(
            f"| {topic} | {row['no_direct']} | {row['rescued_BC']} ({row['rescued_pct_of_no_direct']}%) | "
            f"{row['soft_D']} ({row['soft_D_pct_of_no_direct']}%) | {row['none']} ({row['none_pct_of_no_direct']}%) | {mix} |"
        )

    lines += [
        "",
        "## Guardrail",
        "",
        "These are implementation-selectivity frequencies on fixed chart moments, not observed real-world success rates. They are useful for locating where the product's evidence hierarchy becomes narrow; they are not a target for forcing any chosen positive/negative ratio.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2026-01-01")
    p.add_argument("--end", default="2026-09-24")
    p.add_argument("--date-count", type=int, default=4)
    p.add_argument("--hours", default="9,21")
    p.add_argument("--topics", default="general,contact,reconciliation")
    p.add_argument("--locations", default="seoul,london")
    p.add_argument("--output-dir", default="audit-output")
    args = p.parse_args()

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    dates = even_dates(start, end, args.date_count)
    hours = [int(x) for x in args.hours.split(",") if x.strip()]
    topics = [x.strip() for x in args.topics.split(",") if x.strip() in QUESTIONS]
    locations = [x.strip() for x in args.locations.split(",") if x.strip() in LOCATIONS]

    total = len(dates) * len(hours) * len(topics) * len(locations)
    done = 0
    rows: list[dict] = []
    errors: list[dict] = []
    for location_key in locations:
        tz = ZoneInfo(LOCATIONS[location_key]["timezone"])
        for d in dates:
            for hour in hours:
                local_dt = datetime.combine(d, time(hour), tzinfo=tz)
                for topic in topics:
                    done += 1
                    try:
                        rows.append(classify_cell(topic, location_key, local_dt))
                    except Exception as exc:
                        errors.append({
                            "topic": topic,
                            "location": location_key,
                            "local_iso": local_dt.isoformat(),
                            "error": f"{type(exc).__name__}: {exc}",
                        })
                    if done % 6 == 0 or done == total:
                        print(f"V2_PROGRESS {done}/{total}", file=sys.stderr, flush=True)

    if errors:
        print(json.dumps(errors, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit("V2 full-evidence audit had errors")

    payload = {
        "version": VERSION,
        "meta": {
            "dates": [x.isoformat() for x in dates],
            "hours": hours,
            "topics": topics,
            "locations": locations,
            "cells": len(rows),
        },
        "summary": {topic: summarize(rows, topic) for topic in topics},
        "cells": rows,
    }

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "horary-bias-audit-v2.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report = render(payload)
    (out / "horary-bias-audit-v2.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
