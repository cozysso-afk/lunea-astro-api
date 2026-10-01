from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import astro_core as core
import horary_balance_v31 as v31
import horary_engine_v6 as v6
import horary_future_window_v2 as fw2


VERSION = "LUNEA_HORARY_FUTURE_WINDOW_V2_1_COMPLETENESS"
_ORIGINAL_COMPUTE_HORARY = v31.compute_horary


def _utc(value) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(ZoneInfo("UTC"))
    return v6._parse_utc(value)


def _local(value: datetime, timezone_name: str) -> str:
    try:
        return value.astimezone(ZoneInfo(timezone_name or "Asia/Seoul")).isoformat()
    except Exception:
        return value.isoformat()


def _axis_relation(body: str, data) -> str:
    sig = data.get("significators") or {}
    topic = str((data.get("question") or {}).get("topic") or "general")
    event = sig.get("event") or {}
    if body == event.get("ruler"):
        if int(event.get("house") or 0) == 2 and topic in {"stock", "money"}:
            return "direct_money"
        return "direct_event"
    if body == (sig.get("quesited") or {}).get("ruler"):
        return "direct_quesited"
    if body == (sig.get("querent") or {}).get("ruler"):
        return "direct_querent"
    return "supportive" if body in core.HORARY_PLANETS else "unrelated"


def _moon_event(body: str, event: dict, data, timezone_name: str, sign_index: int):
    exact = _utc(event.get("exact_utc") or event.get("utc"))
    relation = _axis_relation(body, data)
    direct = relation.startswith("direct_")
    return {
        "type": "moon_major_aspect",
        "body": body,
        "body_ko": core.PLANET_KO.get(body, body),
        "aspect": event.get("aspect"),
        "aspect_ko": event.get("aspect_ko"),
        "phase": "applying_to_exact",
        "exact_local": _local(exact, timezone_name),
        "exact_utc": exact.isoformat(),
        "eventAxisRelation": relation,
        "direct_event_axis": direct,
        "direct_roles": [relation.replace("direct_", "")] if direct else [],
        "supportive_only": relation == "supportive",
        "sign_index": sign_index,
        "sign_en": core.SIGNS_EN[sign_index],
        "sign_ko": fw2._SIGN_KO[sign_index],
    }


def _next_moon_ingress(start_utc: datetime):
    state = fw2._planet_state("Moon", start_utc)
    row = {
        "longitude": state["longitude"],
        "direction": state["direction"],
    }
    try:
        ingress = v6._next_sign_ingress("Moon", row, start_utc, horizon_days=4.0)
    except Exception:
        ingress = None
    if not ingress or not ingress.get("utc"):
        return None
    exact = _utc(ingress["utc"])
    return exact, ingress


def _moon_sign_segments(data, target_start: datetime, target_end: datetime, dt_utc: datetime, timezone_name: str):
    scan_start = max(target_start, dt_utc)
    segments = []
    target_events = []
    cursor = scan_start
    guard = 0

    while cursor <= target_end and guard < 5:
        guard += 1
        state = fw2._planet_state("Moon", cursor)
        sign_index = int(state["sign_index"])
        next_ingress = _next_moon_ingress(cursor)
        if next_ingress:
            sign_exit, ingress_row = next_ingress
        else:
            sign_exit, ingress_row = target_end + timedelta(seconds=1), None

        # Scan all remaining exact Ptolemaic aspects in this sign, not merely
        # aspects after an ingress that happens to fall inside the target window.
        full_events = []
        exact_end = sign_exit if sign_exit > cursor else target_end
        for body in core.HORARY_PLANETS:
            if body == "Moon":
                continue
            try:
                for event in v6._exact_events_between("Moon", body, cursor, exact_end):
                    row = _moon_event(body, event, data, timezone_name, sign_index)
                    key = (row["exact_utc"], row["body"], row.get("aspect"))
                    if not any((x["exact_utc"], x["body"], x.get("aspect")) == key for x in full_events):
                        full_events.append(row)
            except Exception:
                continue
        full_events.sort(key=lambda x: x["exact_utc"])

        in_target = [
            row for row in full_events
            if target_start <= _utc(row["exact_utc"]) <= target_end
        ]
        target_events.extend(in_target)
        last_exact = full_events[-1] if full_events else None
        voc_start = _utc(last_exact["exact_utc"]) if last_exact else cursor
        has_known_exit = ingress_row is not None

        segment = {
            "sign_index": sign_index,
            "sign_en": core.SIGNS_EN[sign_index],
            "sign_ko": fw2._SIGN_KO[sign_index],
            "scanStart": _local(cursor, timezone_name),
            "signExitAt": _local(sign_exit, timezone_name) if has_known_exit else None,
            "targetWindowExactAspects": in_target,
            "remainingExactAspectsBeforeSignExit": full_events,
            "lastMajorAspectBeforeSignExit": last_exact,
            "vocAfterLastExact": bool(has_known_exit),
            "vocAfterLastExactAt": _local(voc_start, timezone_name) if has_known_exit else None,
            "vocUntilSignExitAt": _local(sign_exit, timezone_name) if has_known_exit else None,
            "note_ko": (
                "이 시각 이후 sign 이탈 전 추가 주요 exact aspect가 없어 VOC 구간으로 전환됩니다."
                if has_known_exit else
                "다음 sign ingress를 확인하지 못해 이 segment의 VOC 종료시각은 확정하지 않습니다."
            ),
        }
        segments.append(segment)

        if not next_ingress or sign_exit > target_end:
            break
        cursor = sign_exit + timedelta(seconds=3)

    dedup = {}
    for row in target_events:
        dedup[(row["exact_utc"], row["body"], row.get("aspect"))] = row
    target_events = sorted(dedup.values(), key=lambda x: x["exact_utc"])
    return segments, target_events


def _planet_row(data, body: str):
    planets = data.get("planets") or {}
    if body in planets:
        return planets[body]
    sig = data.get("significators") or {}
    for role in ("querent", "quesited", "event"):
        row = sig.get(role) or {}
        if row.get("ruler") == body and row.get("planet"):
            return row.get("planet")
    return None


def _interruption_events_before_exact(data, pair: dict, exact_dt: datetime, dt_utc: datetime, timezone_name: str):
    out = []
    span_days = max(1.0, (exact_dt - dt_utc).total_seconds() / 86400.0 + 0.2)
    angle = None
    try:
        angle = float(core.HORARY_ASPECTS[pair.get("aspect")]["angle"])
    except Exception:
        pass

    for body in (pair.get("a"), pair.get("b")):
        if not body:
            continue
        row = _planet_row(data, body)
        if not row:
            continue
        try:
            ingress = v6._next_sign_ingress(body, row, dt_utc, horizon_days=span_days)
            if ingress and ingress.get("utc"):
                when = _utc(ingress["utc"])
                if when < exact_dt:
                    out.append({
                        "type": "sign_ingress",
                        "body": body,
                        "body_ko": core.PLANET_KO.get(body, body),
                        "time_local": _local(when, timezone_name),
                        "time_utc": when.isoformat(),
                        "beforeExact": True,
                    })
        except Exception:
            pass
        try:
            station = v6._next_station(body, row, dt_utc, horizon_days=span_days)
            if station and station.get("utc"):
                when = _utc(station["utc"])
                if when < exact_dt:
                    speed_after = float(station.get("speed_after") or 0.0)
                    breaks = None
                    if angle is not None:
                        try:
                            other = pair.get("b") if body == pair.get("a") else pair.get("a")
                            breaks = bool(v6._station_breaks_application(body, other, angle, when))
                        except Exception:
                            breaks = None
                    out.append({
                        "type": "station",
                        "stationKind": "retrograde_station" if speed_after < -v6.STATION_SPEED_EPS else "direct_station",
                        "body": body,
                        "body_ko": core.PLANET_KO.get(body, body),
                        "time_local": _local(when, timezone_name),
                        "time_utc": when.isoformat(),
                        "speed_before": station.get("speed_before"),
                        "speed_after": station.get("speed_after"),
                        "breaksApplication": breaks,
                        "beforeExact": True,
                    })
        except Exception:
            pass
    out.sort(key=lambda x: x.get("time_utc") or "")
    return out


def _enrich_pair(data, pair: dict, target_start: datetime, target_end: datetime, dt_utc: datetime, timezone_name: str):
    question_time = pair.get("question_time") or {}
    current_within = bool(question_time.get("within_orb"))
    samples = pair.get("samples") or []
    entry = pair.get("orb_entry") or {}
    target_within = any(bool(row.get("within_orb")) for row in samples)
    if entry.get("scope") == "within_target_window":
        target_within = True

    pair["currentWithinOrb"] = current_within
    pair["targetWindowWithinOrb"] = bool(target_within)
    pair["targetWindowOrbEntryAt"] = entry.get("time_local") if entry.get("scope") == "within_target_window" else None
    pair["futureDevelopmentOnly"] = bool(not current_within and target_within)
    pair["currentPerfectionUnchanged"] = True

    exact = pair.get("exact_perfection_reference") or {}
    exact_local = exact.get("time_local")
    if exact_local:
        try:
            exact_dt = _utc(exact_local)
            exact["interruption_events_before_exact"] = _interruption_events_before_exact(
                data, pair, exact_dt, dt_utc, timezone_name
            )
        except Exception:
            exact["interruption_events_before_exact"] = []

    pair["targetWindowEvidence"] = {
        "start": _local(target_start, timezone_name),
        "end": _local(target_end, timezone_name),
        "currentlyWithinOrb": current_within,
        "withinOrbAtAnyTargetSnapshotOrEntry": bool(target_within),
        "mayBeDiscussedAsFutureDevelopment": bool(target_within),
        "mayBePromotedToCurrentPerfection": False,
    }
    return pair


def _patch_daily_summaries(fw: dict, moon_events: list[dict], segments: list[dict]):
    for day in fw.get("dailySummaries") or []:
        date_key = str(day.get("date") or "")
        day["moon_major_aspects"] = [row for row in moon_events if str(row.get("exact_local") or "").startswith(date_key)]
        voc_rows = []
        for segment in segments:
            voc_at = str(segment.get("vocAfterLastExactAt") or "")
            exit_at = str(segment.get("vocUntilSignExitAt") or "")
            if voc_at.startswith(date_key) or exit_at.startswith(date_key):
                voc_rows.append({
                    "sign_en": segment.get("sign_en"),
                    "sign_ko": segment.get("sign_ko"),
                    "vocAfterLastExactAt": segment.get("vocAfterLastExactAt"),
                    "vocUntilSignExitAt": segment.get("vocUntilSignExitAt"),
                    "lastMajorAspectBeforeSignExit": segment.get("lastMajorAspectBeforeSignExit"),
                })
        day["moon_voc_transitions"] = voc_rows


def _patch_events(fw: dict, moon_events: list[dict]):
    existing = [row for row in (fw.get("events") or []) if row.get("type") != "moon_major_aspect"]
    for row in moon_events:
        existing.append({
            "type": "moon_major_aspect",
            "time_local": row.get("exact_local"),
            "body": row.get("body"),
            "aspect": row.get("aspect"),
            "eventAxisRelation": row.get("eventAxisRelation"),
            "direct_event_axis": row.get("direct_event_axis"),
            "supportive_only": row.get("supportive_only"),
        })
    existing.sort(key=lambda x: x.get("time_local") or "")
    fw["events"] = existing


def _postprocess(data):
    if not isinstance(data, dict) or data.get("schema") != "LUNEA_HORARY_V1":
        return data
    j = data.get("judgment_support") or {}
    fw = j.get("future_window_v1") or {}
    if not fw.get("active"):
        return data

    moment = data.get("moment") or {}
    timezone_name = str(moment.get("timezone") or "Asia/Seoul")
    dt_utc = _utc(moment.get("utc_iso"))
    target = fw.get("targetWindow") or {}
    try:
        target_start = _utc(target.get("start"))
        target_end = _utc(target.get("end"))
    except Exception:
        return data

    pairs = fw.get("futureAspectDevelopment") or []
    for pair in pairs:
        _enrich_pair(data, pair, target_start, target_end, dt_utc, timezone_name)

    segments, moon_events = _moon_sign_segments(data, target_start, target_end, dt_utc, timezone_name)
    moon_flow = fw.setdefault("moonFutureFlow", {})
    first_ingress = moon_flow.get("ingress")
    first_ingress_dt = None
    try:
        if first_ingress and first_ingress.get("utc"):
            first_ingress_dt = _utc(first_ingress["utc"])
    except Exception:
        pass

    moon_flow["target_window_aspects"] = moon_events
    moon_flow["sign_segments"] = segments
    moon_flow["aspects_after_ingress"] = [
        row for row in moon_events
        if first_ingress_dt is None or _utc(row.get("exact_utc")) >= first_ingress_dt
    ]
    moon_flow["target_window_scan_complete"] = True
    moon_flow["scan_policy"] = "every_target_intersecting_moon_sign_segment_until_sign_exit"
    moon_flow["note_ko"] = (
        "목표기간과 겹치는 Moon의 각 sign segment마다 sign 이탈 전 주요 exact aspect를 시간순으로 검사합니다. "
        "마지막 exact aspect 뒤에는 다음 sign ingress까지 VOC 구간을 별도로 표시합니다."
    )

    _patch_daily_summaries(fw, moon_events, segments)
    _patch_events(fw, moon_events)

    fw["hardeningVersion"] = VERSION
    fw["currentJudgmentUnchanged"] = True
    fw["does_not_change_perfection"] = True
    fw.setdefault("interpretation_rules_ko", []).extend([
        "currentWithinOrb=false와 targetWindowWithinOrb=true는 서로 다른 상태입니다. 후자는 Future Window 진행 근거로만 언급하며 현재 Perfection으로 승격하지 않습니다.",
        "Moon Future Flow는 ingress 존재 여부와 무관하게 목표기간과 겹치는 현재 sign 내부의 주요 exact aspect까지 검사합니다.",
        "Moon의 마지막 주요 exact aspect 이후에는 다음 sign ingress까지 VOC 전환 구간을 별도로 표시합니다.",
    ])
    data.setdefault("meta", {})["future_window_hardening"] = VERSION
    return data


def _compute_horary_future_window_v21(*args, **kwargs):
    return _postprocess(_ORIGINAL_COMPUTE_HORARY(*args, **kwargs))


if not getattr(v31.compute_horary, "_lunea_future_window_v21", False):
    _compute_horary_future_window_v21._lunea_future_window_v21 = True
    v31.compute_horary = _compute_horary_future_window_v21
