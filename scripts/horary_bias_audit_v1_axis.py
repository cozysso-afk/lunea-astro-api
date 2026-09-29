from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import astro_core as core
import horary_balance_v3 as v3
import horary_topic_routes_v3  # noqa: F401  # activates current V6/V7 helpers
import horary_balance_v31 as v31


VERSION = "LUNEA_HORARY_BIAS_AUDIT_V1_AXIS"

LOCATIONS = {
    "seoul": {"place": "Seoul", "timezone": "Asia/Seoul", "lat": 37.5665, "lon": 126.9780},
    "london": {"place": "London", "timezone": "Europe/London", "lat": 51.5074, "lon": -0.1278},
}

QUESTIONS = {
    "general": "이 일은 성사될까요?",
    "contact": "그 사람이 나에게 먼저 연락할까요?",
    "reconciliation": "그 사람과 다시 만날 수 있을까요?",
    "career": "이직이 성사될까요?",
    "contract": "이 계약은 성사될까요?",
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


def compare(strict: dict, extended: dict) -> str:
    s = bool(strict.get("perfects"))
    e = bool(extended.get("perfects"))
    if s and e:
        return "agree_direct"
    if not s and not e:
        return "agree_no_direct"
    if s and not e:
        return "strict_only_direct"
    if extended.get("reason") == "future_perfection_from_out_of_orb":
        return "v3_future_out_of_orb_suppressed"
    if strict.get("reason") == "refranation_station_before_perfection":
        return "v3_ignores_station_break"
    if strict.get("reason") == "no_valid_applying_aspect":
        return "v3_future_new_aspect_or_phase"
    return "v3_other_direct_suppressed"


def axis_result(representative_topic: str, location_key: str, local_dt: datetime) -> dict:
    loc = LOCATIONS[location_key]
    data = core.compute_horary(
        question_text=QUESTIONS.get(representative_topic, "이 일은 성사될까요?"),
        question_iso=local_dt.isoformat(),
        topic=representative_topic,
        timezone_name=loc["timezone"],
        place=loc["place"],
        lat=loc["lat"],
        lon=loc["lon"],
    )
    j = data.get("judgment_support") or {}
    strict = j.get("perfection") or {}
    state = j.get("primary_connection") or {}
    sig = data.get("significators") or {}
    q = sig.get("querent") or {}
    t = sig.get("quesited") or {}
    qn, tn = q.get("ruler"), t.get("ruler")
    qr, tr = q.get("planet"), t.get("planet")
    if not (qn and tn and qr and tr):
        raise RuntimeError("missing direct significators")
    dt_utc = datetime.fromisoformat(str((data.get("moment") or {}).get("utc_iso") or "").replace("Z", "+00:00"))
    extended = v3._balanced_perfection_candidate(qn, qr, tn, tr, dt_utc, loc["timezone"])
    return {
        "location": location_key,
        "local_iso": local_dt.isoformat(),
        "querent_ruler": qn,
        "quesited_ruler": tn,
        "strict_perfects": bool(strict.get("perfects")),
        "strict_reason": strict.get("reason") or "unknown",
        "strict_state": state.get("traditional_state") or state.get("phase") or "unknown",
        "extended_perfects": bool(extended.get("perfects")),
        "extended_reason": extended.get("reason") or "unknown",
        "extended_started_within_orb": extended.get("started_within_orb"),
        "comparison": compare(strict, extended),
    }


def full_result(topic: str, location_key: str, local_dt: datetime) -> dict:
    loc = LOCATIONS[location_key]
    data = v31.compute_horary(
        question_text=QUESTIONS.get(topic, "이 일은 성사될까요?"),
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
    grade = c.get("qualified_evidence_grade_v7") or c.get("evidence_grade") or "NONE"
    return {
        "topic": topic,
        "location": location_key,
        "local_iso": local_dt.isoformat(),
        "grade": str(grade),
        "grade_band": band(grade),
        "tier": b.get("tier") or "unknown",
        "headline": b.get("headline_ko") or "",
        "support_score": b.get("support_score"),
        "constraint_score": b.get("constraint_score"),
    }


def topic_summary(cells: list[dict], topics: list[str]) -> dict:
    out = {}
    for topic in topics:
        rows = [x for x in cells if x["topic"] == topic]
        n = len(rows)
        strict = sum(x["strict_perfects"] for x in rows)
        ext = sum(x["extended_perfects"] for x in rows)
        suppressed = sum((not x["strict_perfects"]) and x["extended_perfects"] for x in rows)
        comparisons = Counter(x["comparison"] for x in rows)
        out[topic] = {
            "axis_house": rows[0]["quesited_house"] if rows else None,
            "n": n,
            "strict_direct": strict,
            "strict_pct": pct(strict, n),
            "v3_extended_direct": ext,
            "v3_pct": pct(ext, n),
            "delta_pp": round(pct(ext, n) - pct(strict, n), 1),
            "suppressed": suppressed,
            "suppressed_pct_all": pct(suppressed, n),
            "suppressed_pct_v3": pct(suppressed, ext),
            "out_of_orb_suppressed": comparisons["v3_future_out_of_orb_suppressed"],
            "out_of_orb_pct_all": pct(comparisons["v3_future_out_of_orb_suppressed"], n),
            "comparison": dict(comparisons),
            "strict_failure_reasons": dict(Counter(x["strict_reason"] for x in rows if not x["strict_perfects"]).most_common()),
        }
    return out


def render(payload: dict) -> str:
    lines = [
        "# HORARY BIAS AUDIT V1 · direct-axis optimized",
        "",
        f"- topic cells: **{payload['meta']['topic_cells']}**",
        f"- unique direct-axis calculations: **{payload['meta']['axis_calculations']}**",
        f"- full-engine spot cells: **{payload['meta']['full_cells']}**",
        f"- dates: {', '.join(payload['meta']['dates'])}",
        f"- hours: {', '.join(map(str, payload['meta']['hours']))}",
        f"- locations: {', '.join(payload['meta']['locations'])}",
        "",
        "Topics sharing the same quesited house deliberately reuse the identical 1H↔quesited-house direct-axis calculation. This prevents repeated expensive ephemeris work and makes it explicit when several product topics share the same strict direct gate.",
        "",
        "## Direct gate distribution",
        "",
        "| Topic | direct axis | N | V7 strict | V3 extended | Δ pp | suppressed | out-of-orb future |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for topic, row in payload["topic_summary"].items():
        lines.append(
            f"| {topic} | 1H↔{row['axis_house']}H | {row['n']} | {row['strict_direct']} ({row['strict_pct']}%) | "
            f"{row['v3_extended_direct']} ({row['v3_pct']}%) | {row['delta_pp']:+.1f} | "
            f"{row['suppressed']} ({row['suppressed_pct_all']}%; {row['suppressed_pct_v3']}% of V3 direct) | "
            f"{row['out_of_orb_suppressed']} ({row['out_of_orb_pct_all']}%) |"
        )

    lines += [
        "",
        "## Full current-engine spot sample",
        "",
        f"- A/B/C/D/NONE bands: **{payload['full_summary']['grades']}**",
        f"- balance tiers: **{payload['full_summary']['tiers']}**",
        "",
        "## Strict failure reasons",
        "",
    ]
    for topic, row in payload["topic_summary"].items():
        text = ", ".join(f"{k}={v}" for k, v in row["strict_failure_reasons"].items()) or "none"
        lines.append(f"- **{topic} · 1H↔{row['axis_house']}H**: {text}")

    lines += [
        "",
        "## Guardrail",
        "",
        "This measures implementation selectivity on fixed charts. It is not an empirical event-success rate and does not imply that the engine should be tuned to a 50/50 positive/negative distribution.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2026-01-01")
    p.add_argument("--end", default="2026-09-24")
    p.add_argument("--date-count", type=int, default=8)
    p.add_argument("--hours", default="3,9,15,21")
    p.add_argument("--topics", default="general,contact,reconciliation,career,contract")
    p.add_argument("--locations", default="seoul,london")
    p.add_argument("--full-date", default="2026-09-05")
    p.add_argument("--full-hour", type=int, default=15)
    p.add_argument("--full-topics", default="general,contact,reconciliation")
    p.add_argument("--output-dir", default="audit-output")
    args = p.parse_args()

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    dates = even_dates(start, end, args.date_count)
    hours = [int(x) for x in args.hours.split(",") if x.strip()]
    locations = [x.strip() for x in args.locations.split(",") if x.strip()]
    topics = [x.strip() for x in args.topics.split(",") if x.strip() and x.strip() in core.HORARY_TOPIC_SPECS]
    full_topics = [x.strip() for x in args.full_topics.split(",") if x.strip() and x.strip() in core.HORARY_TOPIC_SPECS]

    topic_groups: dict[int, list[str]] = defaultdict(list)
    for topic in topics:
        topic_groups[int(core.HORARY_TOPIC_SPECS[topic]["quesited_house"])].append(topic)

    topic_cells: list[dict] = []
    errors: list[dict] = []
    axis_total = len(locations) * len(dates) * len(hours) * len(topic_groups)
    axis_done = 0
    for location_key in locations:
        if location_key not in LOCATIONS:
            raise SystemExit(f"unknown location: {location_key}")
        tz = ZoneInfo(LOCATIONS[location_key]["timezone"])
        for d in dates:
            for hour in hours:
                local_dt = datetime.combine(d, time(hour), tzinfo=tz)
                for house, grouped_topics in sorted(topic_groups.items()):
                    axis_done += 1
                    representative = grouped_topics[0]
                    try:
                        row = axis_result(representative, location_key, local_dt)
                        for topic in grouped_topics:
                            topic_cells.append({**row, "topic": topic, "quesited_house": house})
                    except Exception as exc:
                        errors.append({"house": house, "topics": grouped_topics, "location": location_key, "local_iso": local_dt.isoformat(), "error": f"{type(exc).__name__}: {exc}"})
                    if axis_done % 10 == 0 or axis_done == axis_total:
                        print(f"AXIS_PROGRESS {axis_done}/{axis_total}", file=sys.stderr, flush=True)

    if errors:
        print(json.dumps(errors[:20], ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit("direct-axis audit had errors")

    full_cells: list[dict] = []
    full_date = date.fromisoformat(args.full_date)
    full_total = len(locations) * len(full_topics)
    full_done = 0
    for location_key in locations:
        tz = ZoneInfo(LOCATIONS[location_key]["timezone"])
        local_dt = datetime.combine(full_date, time(args.full_hour), tzinfo=tz)
        for topic in full_topics:
            full_done += 1
            full_cells.append(full_result(topic, location_key, local_dt))
            print(f"FULL_PROGRESS {full_done}/{full_total}", file=sys.stderr, flush=True)

    summary = topic_summary(topic_cells, topics)
    payload = {
        "version": VERSION,
        "meta": {
            "start": args.start,
            "end": args.end,
            "dates": [x.isoformat() for x in dates],
            "hours": hours,
            "locations": locations,
            "topics": topics,
            "topic_cells": len(topic_cells),
            "axis_calculations": axis_total,
            "full_cells": len(full_cells),
        },
        "topic_summary": summary,
        "full_summary": {
            "grades": dict(Counter(x["grade_band"] for x in full_cells)),
            "tiers": dict(Counter(x["tier"] for x in full_cells)),
        },
        "topic_cells": topic_cells,
        "full_cells": full_cells,
    }

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "horary-bias-audit-v1-axis.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report = render(payload)
    (out / "horary-bias-audit-v1-axis.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
