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
import horary_topic_routes_v3  # noqa: F401  # activates V4 -> V5 -> V6 -> V7
import horary_balance_v31 as v31


VERSION = "LUNEA_HORARY_BIAS_AUDIT_V1_CI"

QUESTION_BY_TOPIC = {
    "general": "이 일은 성사될까요?",
    "contact": "그 사람이 나에게 먼저 연락할까요?",
    "reconciliation": "그 사람과 다시 만날 수 있을까요?",
    "relationship": "그 사람과 관계가 진전될까요?",
    "career": "이직이 성사될까요?",
    "contract": "이 계약은 성사될까요?",
    "exam": "이번 시험에 합격할까요?",
}

LOCATIONS = {
    "seoul": {"place": "Seoul", "timezone": "Asia/Seoul", "lat": 37.5665, "lon": 126.9780},
    "london": {"place": "London", "timezone": "Europe/London", "lat": 51.5074, "lon": -0.1278},
}


def even_dates(start: date, end: date, count: int) -> list[date]:
    if count <= 1:
        return [start + timedelta(days=(end - start).days // 2)]
    span = (end - start).days
    return [start + timedelta(days=round(span * i / (count - 1))) for i in range(count)]


def pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 1) if d else 0.0


def grade_band(raw) -> str:
    text = str(raw or "NONE")
    if text.startswith("A"):
        return "A"
    if text in {"B", "C", "D", "NONE"}:
        return text
    return "OTHER"


def direct_cell(topic: str, location_key: str, local_dt: datetime) -> dict:
    loc = LOCATIONS[location_key]
    question = QUESTION_BY_TOPIC.get(topic, f"{topic} 질문이 성사될까요?")

    # Important: this intentionally calls astro_core directly after V6/V7
    # activation. That preserves the CURRENT strict aspect/perfection helpers
    # but avoids the expensive V3.1 translation/collection full post-processing.
    data = core.compute_horary(
        question_text=question,
        question_iso=local_dt.isoformat(),
        topic=topic,
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
    if qn and tn and qr and tr:
        dt_utc = datetime.fromisoformat(str((data.get("moment") or {}).get("utc_iso") or "").replace("Z", "+00:00"))
        extended = v3._balanced_perfection_candidate(qn, qr, tn, tr, dt_utc, loc["timezone"])
    else:
        extended = {"perfects": False, "indeterminate": True, "reason": "missing_significator"}

    strict_yes = bool(strict.get("perfects"))
    extended_yes = bool(extended.get("perfects"))
    if strict_yes and extended_yes:
        comparison = "agree_direct"
    elif not strict_yes and not extended_yes:
        comparison = "agree_no_direct"
    elif strict_yes and not extended_yes:
        comparison = "strict_only_direct"
    elif extended.get("reason") == "future_perfection_from_out_of_orb":
        comparison = "v3_future_out_of_orb_suppressed"
    elif strict.get("reason") == "refranation_station_before_perfection":
        comparison = "v3_ignores_station_break"
    elif strict.get("reason") == "no_valid_applying_aspect":
        comparison = "v3_future_new_aspect_or_phase"
    else:
        comparison = "v3_other_direct_suppressed"

    return {
        "topic": topic,
        "location": location_key,
        "local_iso": local_dt.isoformat(),
        "strict_perfects": strict_yes,
        "strict_reason": strict.get("reason") or "unknown",
        "strict_state": state.get("traditional_state") or state.get("phase") or "unknown",
        "extended_perfects": extended_yes,
        "extended_reason": extended.get("reason") or "unknown",
        "extended_started_within_orb": extended.get("started_within_orb"),
        "comparison": comparison,
    }


def full_cell(topic: str, location_key: str, local_dt: datetime) -> dict:
    loc = LOCATIONS[location_key]
    question = QUESTION_BY_TOPIC.get(topic, f"{topic} 질문이 성사될까요?")
    data = v31.compute_horary(
        question_text=question,
        question_iso=local_dt.isoformat(),
        topic=topic,
        timezone_name=loc["timezone"],
        place=loc["place"],
        lat=loc["lat"],
        lon=loc["lon"],
    )
    j = data.get("judgment_support") or {}
    core_v7 = j.get("traditional_core_v7") or j.get("traditional_core_v6") or {}
    balance = j.get("balance_v31") or {}
    direct = (core_v7.get("direct_axis") or {}).get("perfection") or j.get("perfection") or {}
    grade_raw = core_v7.get("qualified_evidence_grade_v7") or core_v7.get("evidence_grade") or "NONE"
    return {
        "topic": topic,
        "location": location_key,
        "local_iso": local_dt.isoformat(),
        "grade_raw": str(grade_raw),
        "grade_band": grade_band(grade_raw),
        "direct_perfects": bool(direct.get("perfects")),
        "strict_reason": direct.get("reason") or "unknown",
        "balance_tier": balance.get("tier") or "unknown",
        "balance_headline": balance.get("headline_ko") or "",
        "support_score": balance.get("support_score"),
        "constraint_score": balance.get("constraint_score"),
    }


def summarize_direct(cells: list[dict], topics: list[str]) -> dict:
    out = {}
    for topic in topics:
        rows = [x for x in cells if x["topic"] == topic]
        n = len(rows)
        strict = sum(x["strict_perfects"] for x in rows)
        ext = sum(x["extended_perfects"] for x in rows)
        suppressed = sum((not x["strict_perfects"]) and x["extended_perfects"] for x in rows)
        comp = Counter(x["comparison"] for x in rows)
        out[topic] = {
            "n": n,
            "strict_direct": strict,
            "strict_direct_pct": pct(strict, n),
            "v3_extended_direct": ext,
            "v3_extended_direct_pct": pct(ext, n),
            "delta_pp": round(pct(ext, n) - pct(strict, n), 1),
            "suppressed": suppressed,
            "suppressed_pct_all": pct(suppressed, n),
            "suppressed_pct_v3_direct": pct(suppressed, ext),
            "out_of_orb_suppressed": comp["v3_future_out_of_orb_suppressed"],
            "out_of_orb_pct_all": pct(comp["v3_future_out_of_orb_suppressed"], n),
            "comparison": dict(comp),
            "strict_failure_reasons": dict(Counter(x["strict_reason"] for x in rows if not x["strict_perfects"]).most_common()),
        }
    return out


def markdown(payload: dict) -> str:
    direct = payload["direct_summary"]
    full = payload["full_summary"]
    meta = payload["meta"]
    lines = [
        "# Horary Bias Audit V1 · CI sample",
        "",
        f"- direct-gate cells: **{meta['direct_cells']}**",
        f"- full-engine spot cells: **{meta['full_cells']}**",
        f"- range: {meta['start']} ~ {meta['end']}",
        f"- locations: {', '.join(meta['locations'])}",
        "",
        "## Direct gate: current strict vs V3 extended candidate",
        "",
        "| Topic | N | current strict | V3 extended | Δ pp | suppressed by strict | out-of-orb future suppressed |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for topic, row in direct.items():
        lines.append(
            f"| {topic} | {row['n']} | {row['strict_direct']} ({row['strict_direct_pct']}%) | "
            f"{row['v3_extended_direct']} ({row['v3_extended_direct_pct']}%) | {row['delta_pp']:+.1f} | "
            f"{row['suppressed']} ({row['suppressed_pct_all']}%; {row['suppressed_pct_v3_direct']}% of V3 direct) | "
            f"{row['out_of_orb_suppressed']} ({row['out_of_orb_pct_all']}%) |"
        )

    lines += [
        "",
        "## Full current V7/V3.1 spot sample",
        "",
        f"Grade bands A/B/C/D/NONE: **{full['grade_distribution']}**",
        "",
        "Balance tiers:",
    ]
    for key, value in sorted(full["tier_distribution"].items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"- `{key}`: {value}")

    lines += ["", "## Strict failure reasons by topic", ""]
    for topic, row in direct.items():
        reasons = ", ".join(f"{k}={v}" for k, v in row["strict_failure_reasons"].items()) or "none"
        lines.append(f"- **{topic}**: {reasons}")

    lines += [
        "",
        "## Guardrail",
        "",
        "This is an implementation-selectivity audit, not a real-world accuracy/probability study. A larger positive or negative share is not itself a target; the key diagnostic is which implementation gate creates the difference on identical charts.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2026-01-01")
    parser.add_argument("--end", default="2026-09-24")
    parser.add_argument("--direct-date-count", type=int, default=4)
    parser.add_argument("--direct-hours", default="3,9,15,21")
    parser.add_argument("--topics", default="general,contact,reconciliation,career,contract")
    parser.add_argument("--locations", default="seoul,london")
    parser.add_argument("--full-topics", default="general,contact,reconciliation")
    parser.add_argument("--full-dates", default="2026-03-15,2026-09-05")
    parser.add_argument("--full-hours", default="15")
    parser.add_argument("--output-dir", default="audit-output")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    locations = [x.strip() for x in args.locations.split(",") if x.strip()]
    for key in locations:
        if key not in LOCATIONS:
            raise SystemExit(f"unknown location: {key}")

    topics = [x.strip() for x in args.topics.split(",") if x.strip() and x.strip() in core.HORARY_TOPIC_SPECS]
    full_topics = [x.strip() for x in args.full_topics.split(",") if x.strip() and x.strip() in core.HORARY_TOPIC_SPECS]
    direct_dates = even_dates(start, end, args.direct_date_count)
    direct_hours = [int(x) for x in args.direct_hours.split(",") if x.strip()]
    full_dates = [date.fromisoformat(x.strip()) for x in args.full_dates.split(",") if x.strip()]
    full_hours = [int(x) for x in args.full_hours.split(",") if x.strip()]

    direct_cells: list[dict] = []
    direct_errors: list[dict] = []
    planned_direct = len(locations) * len(direct_dates) * len(direct_hours) * len(topics)
    done = 0
    for location_key in locations:
        tz = ZoneInfo(LOCATIONS[location_key]["timezone"])
        for d in direct_dates:
            for hour in direct_hours:
                local_dt = datetime.combine(d, time(hour), tzinfo=tz)
                for topic in topics:
                    done += 1
                    try:
                        direct_cells.append(direct_cell(topic, location_key, local_dt))
                    except Exception as exc:
                        direct_errors.append({"topic": topic, "location": location_key, "local_iso": local_dt.isoformat(), "error": f"{type(exc).__name__}: {exc}"})
                    if done % 20 == 0 or done == planned_direct:
                        print(f"DIRECT_PROGRESS {done}/{planned_direct}", file=sys.stderr, flush=True)

    if len(direct_errors) > max(1, round(planned_direct * 0.02)):
        print(json.dumps(direct_errors[:20], ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit("direct audit error rate exceeded 2%")

    full_cells: list[dict] = []
    full_errors: list[dict] = []
    planned_full = len(locations) * len(full_dates) * len(full_hours) * len(full_topics)
    done = 0
    for location_key in locations:
        tz = ZoneInfo(LOCATIONS[location_key]["timezone"])
        for d in full_dates:
            for hour in full_hours:
                local_dt = datetime.combine(d, time(hour), tzinfo=tz)
                for topic in full_topics:
                    done += 1
                    try:
                        full_cells.append(full_cell(topic, location_key, local_dt))
                    except Exception as exc:
                        full_errors.append({"topic": topic, "location": location_key, "local_iso": local_dt.isoformat(), "error": f"{type(exc).__name__}: {exc}"})
                    print(f"FULL_PROGRESS {done}/{planned_full}", file=sys.stderr, flush=True)

    if full_errors:
        print(json.dumps(full_errors, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit("full-engine spot audit had errors")

    direct_summary = summarize_direct(direct_cells, topics)
    full_summary = {
        "grade_distribution": dict(Counter(x["grade_band"] for x in full_cells)),
        "tier_distribution": dict(Counter(x["balance_tier"] for x in full_cells)),
        "direct_perfects": sum(x["direct_perfects"] for x in full_cells),
        "n": len(full_cells),
    }
    payload = {
        "version": VERSION,
        "meta": {
            "start": args.start,
            "end": args.end,
            "locations": locations,
            "topics": topics,
            "direct_dates": [x.isoformat() for x in direct_dates],
            "direct_hours": direct_hours,
            "direct_cells": len(direct_cells),
            "full_topics": full_topics,
            "full_dates": [x.isoformat() for x in full_dates],
            "full_hours": full_hours,
            "full_cells": len(full_cells),
            "direct_errors": direct_errors,
            "full_errors": full_errors,
        },
        "direct_summary": direct_summary,
        "full_summary": full_summary,
        "direct_cells": direct_cells,
        "full_cells": full_cells,
    }

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "horary-bias-audit-v1-ci.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report = markdown(payload)
    (out / "horary-bias-audit-v1-ci.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
