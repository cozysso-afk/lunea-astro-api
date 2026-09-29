from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import astro_core as core
import horary_balance_v3 as v3
import horary_topic_routes_v3  # noqa: F401  # activates V4 -> V5 -> V6 -> V7
import horary_balance_v31 as v31


VERSION = "LUNEA_HORARY_BIAS_AUDIT_V1"

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
    "seoul": {
        "place": "Seoul",
        "timezone": "Asia/Seoul",
        "lat": 37.5665,
        "lon": 126.9780,
    },
    "london": {
        "place": "London",
        "timezone": "Europe/London",
        "lat": 51.5074,
        "lon": -0.1278,
    },
}

DEFAULT_TOPICS = ("general", "contact", "reconciliation", "career", "contract")
DEFAULT_HOURS = (3, 9, 15, 21)


@dataclass(frozen=True)
class AuditCell:
    topic: str
    location: str
    local_iso: str
    strict_perfects: bool
    strict_reason: str
    strict_state: str
    grade_raw: str
    grade_band: str
    balanced_perfects: bool
    balanced_reason: str
    balanced_started_within_orb: bool | None
    comparison: str
    derived_event_perfects: bool
    indirect_present: bool
    reception_present: bool
    obstruction_present: bool


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _even_dates(start: date, end: date, count: int) -> list[date]:
    if count < 2:
        return [start]
    if end < start:
        raise ValueError("end must be on or after start")
    span = (end - start).days
    return [start + timedelta(days=round(span * i / (count - 1))) for i in range(count)]


def _grade_band(raw: object) -> str:
    text = str(raw or "NONE")
    if text.startswith("A"):
        return "A"
    if text in {"B", "C", "D", "NONE"}:
        return text
    return "OTHER"


def _reception_present(direct_axis: dict) -> bool:
    reception = (direct_axis or {}).get("reception") or {}
    grade = reception.get("grade")
    return bool(
        grade not in {None, "none"}
        or reception.get("has_reception")
        or reception.get("has_minor_reception")
        or reception.get("same_significator")
    )


def _comparison(strict: dict, balanced: dict) -> str:
    s = bool(strict.get("perfects"))
    b = bool(balanced.get("perfects"))
    if s and b:
        return "agree_direct"
    if not s and not b:
        return "agree_no_direct"
    if s and not b:
        return "strict_only_direct"

    strict_reason = str(strict.get("reason") or "")
    balanced_reason = str(balanced.get("reason") or "")
    if balanced_reason == "future_perfection_from_out_of_orb":
        return "v3_future_out_of_orb_suppressed"
    if strict_reason == "refranation_station_before_perfection":
        return "v3_ignores_station_break"
    if strict_reason == "sign_change_before_perfection":
        return "sign_change_disagreement"
    if strict_reason == "no_valid_applying_aspect":
        return "v3_future_new_aspect_or_phase"
    return "v3_other_direct_suppressed"


def _audit_one(topic: str, location_key: str, local_dt: datetime) -> AuditCell:
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
    direct_axis = core_v7.get("direct_axis") or {}
    strict = direct_axis.get("perfection") or j.get("perfection") or {}
    strict_state = direct_axis.get("aspect_state") or j.get("primary_connection") or {}

    sig = data.get("significators") or {}
    q = sig.get("querent") or {}
    t = sig.get("quesited") or {}
    qn, tn = q.get("ruler"), t.get("ruler")
    qr, tr = q.get("planet"), t.get("planet")
    if qn and tn and qr and tr:
        dt_utc = datetime.fromisoformat(str((data.get("moment") or {}).get("utc_iso") or "").replace("Z", "+00:00"))
        balanced = v3._balanced_perfection_candidate(qn, qr, tn, tr, dt_utc, loc["timezone"])
    else:
        balanced = {
            "perfects": False,
            "indeterminate": True,
            "reason": "missing_significator",
            "started_within_orb": None,
        }

    event_axes = core_v7.get("derived_event_axes") or {}
    derived_event_perfects = any(
        bool(((row or {}).get("perfection") or {}).get("perfects"))
        for row in event_axes.values()
    )
    indirect = core_v7.get("indirect_perfection") or {}
    indirect_present = bool(indirect.get("translation_of_light") or indirect.get("collection_of_light"))
    obstruction_present = bool(
        core_v7.get("confirmed_obstruction_count_v7")
        or (core_v7.get("interventions") or {}).get("prohibition_or_frustration")
        or (core_v7.get("interventions") or {}).get("refranation")
    )

    grade_raw = str(core_v7.get("qualified_evidence_grade_v7") or core_v7.get("evidence_grade") or "NONE")
    return AuditCell(
        topic=topic,
        location=location_key,
        local_iso=local_dt.isoformat(),
        strict_perfects=bool(strict.get("perfects")),
        strict_reason=str(strict.get("reason") or "unknown"),
        strict_state=str(strict_state.get("traditional_state") or strict_state.get("phase") or "unknown"),
        grade_raw=grade_raw,
        grade_band=_grade_band(grade_raw),
        balanced_perfects=bool(balanced.get("perfects")),
        balanced_reason=str(balanced.get("reason") or "unknown"),
        balanced_started_within_orb=balanced.get("started_within_orb"),
        comparison=_comparison(strict, balanced),
        derived_event_perfects=derived_event_perfects,
        indirect_present=indirect_present,
        reception_present=_reception_present(direct_axis),
        obstruction_present=obstruction_present,
    )


def _pct(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def _summarize(cells: list[AuditCell], requested_topics: list[str], skipped_topics: list[str]) -> dict:
    by_topic: dict[str, list[AuditCell]] = defaultdict(list)
    for cell in cells:
        by_topic[cell.topic].append(cell)

    topic_rows = {}
    for topic in requested_topics:
        rows = by_topic.get(topic, [])
        n = len(rows)
        grades = Counter(x.grade_band for x in rows)
        comparisons = Counter(x.comparison for x in rows)
        strict_reasons = Counter(x.strict_reason for x in rows if not x.strict_perfects)
        balanced_reasons = Counter(x.balanced_reason for x in rows if not x.balanced_perfects)
        strict_direct = sum(x.strict_perfects for x in rows)
        balanced_direct = sum(x.balanced_perfects for x in rows)
        suppressed = sum((not x.strict_perfects) and x.balanced_perfects for x in rows)
        out_of_orb = comparisons["v3_future_out_of_orb_suppressed"]
        v3_positive_total = balanced_direct
        topic_rows[topic] = {
            "n": n,
            "strict_direct": strict_direct,
            "strict_direct_pct": _pct(strict_direct, n),
            "v3_extended_direct": balanced_direct,
            "v3_extended_direct_pct": _pct(balanced_direct, n),
            "delta_percentage_points": round(_pct(balanced_direct, n) - _pct(strict_direct, n), 1),
            "v3_direct_suppressed_by_strict": suppressed,
            "suppressed_pct_of_all": _pct(suppressed, n),
            "suppressed_pct_of_v3_direct": _pct(suppressed, v3_positive_total),
            "out_of_orb_future_suppressed": out_of_orb,
            "out_of_orb_pct_of_all": _pct(out_of_orb, n),
            "derived_event_perfects": sum(x.derived_event_perfects for x in rows),
            "indirect_present": sum(x.indirect_present for x in rows),
            "reception_present": sum(x.reception_present for x in rows),
            "obstruction_present": sum(x.obstruction_present for x in rows),
            "grade_distribution": dict(grades),
            "comparison_distribution": dict(comparisons),
            "strict_failure_reasons": dict(strict_reasons.most_common()),
            "v3_failure_reasons": dict(balanced_reasons.most_common()),
        }

    overall_n = len(cells)
    overall_strict = sum(x.strict_perfects for x in cells)
    overall_v3 = sum(x.balanced_perfects for x in cells)
    overall_suppressed = sum((not x.strict_perfects) and x.balanced_perfects for x in cells)
    overall_out_of_orb = sum(x.comparison == "v3_future_out_of_orb_suppressed" for x in cells)
    return {
        "version": VERSION,
        "sample_count": overall_n,
        "requested_topics": requested_topics,
        "skipped_topics": skipped_topics,
        "available_topics": sorted(core.HORARY_TOPIC_SPECS.keys()),
        "overall": {
            "strict_direct": overall_strict,
            "strict_direct_pct": _pct(overall_strict, overall_n),
            "v3_extended_direct": overall_v3,
            "v3_extended_direct_pct": _pct(overall_v3, overall_n),
            "delta_percentage_points": round(_pct(overall_v3, overall_n) - _pct(overall_strict, overall_n), 1),
            "v3_direct_suppressed_by_strict": overall_suppressed,
            "suppressed_pct_of_all": _pct(overall_suppressed, overall_n),
            "suppressed_pct_of_v3_direct": _pct(overall_suppressed, overall_v3),
            "out_of_orb_future_suppressed": overall_out_of_orb,
            "out_of_orb_pct_of_all": _pct(overall_out_of_orb, overall_n),
        },
        "topics": topic_rows,
        "comparison_distribution": dict(Counter(x.comparison for x in cells)),
        "grade_distribution": dict(Counter(x.grade_band for x in cells)),
        "strict_failure_reasons": dict(Counter(x.strict_reason for x in cells if not x.strict_perfects).most_common()),
    }


def _markdown(summary: dict, meta: dict) -> str:
    lines = [
        f"# Horary Bias Audit V1",
        "",
        f"- engine audit: `{summary['version']}`",
        f"- sample cells: **{summary['sample_count']}**",
        f"- date range: {meta['start']} ~ {meta['end']} · {meta['date_count']} evenly spaced dates",
        f"- local hours: {', '.join(map(str, meta['hours']))}",
        f"- locations: {', '.join(meta['locations'])}",
        f"- topics: {', '.join(summary['requested_topics'])}",
        "",
        "`V7 strict direct` = current strict traditional direct-perfection gate.  ",
        "`V3-ext direct` = the older V3 extended future-perfection candidate run on the exact same significators.  ",
        "This audit does not treat either distribution as a target probability and does not force 50/50 outcomes.",
        "",
        "## Direct-perfection distribution",
        "",
        "| Topic | N | V7 strict direct | V3-ext direct | Δ pp | V3 direct suppressed | out-of-orb future suppressed | A/B/C/D/NONE |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for topic, row in summary["topics"].items():
        g = row["grade_distribution"]
        grade_text = "/".join(str(g.get(k, 0)) for k in ("A", "B", "C", "D", "NONE"))
        lines.append(
            f"| {topic} | {row['n']} | {row['strict_direct']} ({row['strict_direct_pct']}%) | "
            f"{row['v3_extended_direct']} ({row['v3_extended_direct_pct']}%) | "
            f"{row['delta_percentage_points']:+.1f} | "
            f"{row['v3_direct_suppressed_by_strict']} ({row['suppressed_pct_of_all']}%; {row['suppressed_pct_of_v3_direct']}% of V3 direct) | "
            f"{row['out_of_orb_future_suppressed']} ({row['out_of_orb_pct_of_all']}%) | {grade_text} |"
        )

    overall = summary["overall"]
    lines += [
        "",
        "## Overall",
        "",
        f"- V7 strict direct: **{overall['strict_direct']} / {summary['sample_count']} ({overall['strict_direct_pct']}%)**",
        f"- V3-ext direct: **{overall['v3_extended_direct']} / {summary['sample_count']} ({overall['v3_extended_direct_pct']}%)**",
        f"- gap: **{overall['delta_percentage_points']:+.1f} percentage points**",
        f"- V3 direct cases suppressed by strict gate: **{overall['v3_direct_suppressed_by_strict']} ({overall['suppressed_pct_of_all']}% of all; {overall['suppressed_pct_of_v3_direct']}% of V3 direct)**",
        f"- specifically future perfection that starts out-of-orb: **{overall['out_of_orb_future_suppressed']} ({overall['out_of_orb_pct_of_all']}%)**",
        "",
        "## Comparison reasons",
        "",
    ]
    for key, value in sorted(summary["comparison_distribution"].items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"- `{key}`: {value}")

    lines += ["", "## Current V7 strict failure reasons", ""]
    for key, value in summary["strict_failure_reasons"].items():
        lines.append(f"- `{key}`: {value}")

    if summary["skipped_topics"]:
        lines += ["", f"Skipped unavailable topics: {', '.join(summary['skipped_topics'])}"]

    lines += [
        "",
        "## Interpretation guardrail",
        "",
        "These counts diagnose implementation selectivity. They are not real-world event probabilities, accuracy rates, or a reason to tune the engine toward a desired positive/negative ratio.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure selectivity differences between current V7 strict direct perfection and V3 extended future perfection.")
    parser.add_argument("--start", default="2026-01-01")
    parser.add_argument("--end", default="2026-09-24")
    parser.add_argument("--date-count", type=int, default=12)
    parser.add_argument("--hours", default=",".join(map(str, DEFAULT_HOURS)))
    parser.add_argument("--topics", default=",".join(DEFAULT_TOPICS))
    parser.add_argument("--locations", default="seoul,london")
    parser.add_argument("--output-dir", default="audit-output")
    args = parser.parse_args()

    start = _parse_date(args.start)
    end = _parse_date(args.end)
    dates = _even_dates(start, end, args.date_count)
    hours = [int(x) for x in args.hours.split(",") if x.strip()]
    locations = [x.strip() for x in args.locations.split(",") if x.strip()]
    unknown_locations = [x for x in locations if x not in LOCATIONS]
    if unknown_locations:
        raise SystemExit(f"unknown locations: {unknown_locations}")

    requested = [x.strip() for x in args.topics.split(",") if x.strip()]
    topics = [x for x in requested if x in core.HORARY_TOPIC_SPECS]
    skipped = [x for x in requested if x not in core.HORARY_TOPIC_SPECS]
    if not topics:
        raise SystemExit("no requested topics exist in HORARY_TOPIC_SPECS")

    cells: list[AuditCell] = []
    errors: list[dict] = []
    total = len(dates) * len(hours) * len(locations) * len(topics)
    done = 0
    for location_key in locations:
        loc = LOCATIONS[location_key]
        tz = ZoneInfo(loc["timezone"])
        for d in dates:
            for hour in hours:
                local_dt = datetime.combine(d, time(hour=hour), tzinfo=tz)
                for topic in topics:
                    done += 1
                    try:
                        cells.append(_audit_one(topic, location_key, local_dt))
                    except Exception as exc:  # audit should record, not hide, sampling failures
                        errors.append({
                            "topic": topic,
                            "location": location_key,
                            "local_iso": local_dt.isoformat(),
                            "error": f"{type(exc).__name__}: {exc}",
                        })
                    if done % 25 == 0 or done == total:
                        print(f"AUDIT_PROGRESS {done}/{total}", file=sys.stderr, flush=True)

    if not cells:
        raise SystemExit("audit produced no cells")
    error_rate = len(errors) / max(1, total)
    if error_rate > 0.02:
        print(json.dumps(errors[:20], ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(f"audit error rate too high: {len(errors)}/{total} ({error_rate:.1%})")

    meta = {
        "start": args.start,
        "end": args.end,
        "date_count": args.date_count,
        "dates": [x.isoformat() for x in dates],
        "hours": hours,
        "locations": locations,
        "topics": topics,
        "skipped_topics": skipped,
        "planned_cells": total,
        "completed_cells": len(cells),
        "errors": errors,
    }
    summary = _summarize(cells, topics, skipped)
    payload = {
        "meta": meta,
        "summary": summary,
        "cells": [cell.__dict__ for cell in cells],
    }

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "horary-bias-audit-v1.json"
    md_path = out_dir / "horary-bias-audit-v1.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report = _markdown(summary, meta)
    md_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"AUDIT_JSON={json_path}")
    print(f"AUDIT_MD={md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
