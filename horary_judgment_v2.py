from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import swisseph as swe

import astro_core as core
import horary_balance_v31 as v31
import horary_engine_v6 as v6
import horary_future_window_v2 as fw2


VERSION = "LUNEA_HORARY_V2_JUDGMENT_SCHEMA"
RULESET_ID = "HORARY_V2_TRADITIONAL"
_ORIGINAL_COMPUTE_HORARY = v31.compute_horary


def _utc(value):
    return v6._parse_utc(value)


def _local(dt_utc: datetime | None, timezone_name: str):
    if not dt_utc:
        return None
    try:
        return dt_utc.astimezone(ZoneInfo(timezone_name or "Asia/Seoul")).isoformat()
    except Exception:
        return dt_utc.isoformat()


def _core_v8(data):
    j = data.get("judgment_support") or {}
    return j.get("traditional_core_v8") or j.get("traditional_core_v7") or j.get("traditional_core_v6") or {}


def _hierarchy(data):
    return (data.get("judgment_support") or {}).get("judgment_hierarchy_v8") or {}


def _ruleset(data):
    meta = data.get("meta") or {}
    orb = deepcopy(meta.get("aspect_orb_policy") or {})
    return {
        "id": RULESET_ID,
        "schemaVersion": VERSION,
        "zodiac": data.get("zodiac") or "tropical",
        "houseSystem": data.get("house_system") or "regiomontanus",
        "traditionalBodies": list(core.HORARY_PLANETS),
        "aspectSystem": "ptolemaic_major_five",
        "aspects": ["conjunction", "sextile", "square", "trine", "opposition"],
        "orbPolicy": {
            "method": orb.get("method") or "planetary_moiety_sum",
            "fullOrbsDeg": orb.get("full_orbs_deg") or {},
            "moietiesDeg": orb.get("moieties_deg") or {},
            "changedByV2": False,
        },
        "vocPolicy": "current_sign_only_exact_ptolemaic_aspects_to_traditional_seven",
        "receptionPolicy": "domicile_exaltation_triplicity_egyptian_term_chaldean_face_separate_from_perfection",
        "dignityPolicy": "essential_dignity_and_debility_describe_condition_not_event_outcome",
        "perfectionPolicy": "legacy_v6_v8_current_judgment_preserved_future_development_separate",
        "modernBodiesPolicy": "excluded_from_traditional_perfection_voc_translation_collection_reception",
        "currentJudgmentMutationByV2": False,
    }


def _intent(question_text: str, topic: str):
    q = str(question_text or "").strip()
    lower = q.lower()
    result = {
        "id": "general_event_question",
        "label_ko": "일반 사건 질문",
        "sourceText": q,
        "changesRouting": False,
        "numericPredictionAllowed": False,
    }
    if topic != "stock":
        if any(token in q for token in ("언제", "시기", "몇 일", "며칠")):
            result.update(id="event_timing", label_ko="사건 시기")
        return result

    if any(token in q for token in ("지금 매도", "매도해야", "팔아야", "지금 팔")):
        result.update(id="sell_decision_advice", label_ko="현재 매도 의사결정")
    elif any(token in q for token in ("얼마나 수익", "몇%", "몇 %", "수익률", "수익 범위")):
        result.update(
            id="profit_magnitude_limit",
            label_ko="수익 크기·범위",
            limitation="Horary는 신뢰 가능한 수익률 %를 직접 산출하지 않음",
        )
    elif any(token in q for token in ("언제 익절", "익절 시기", "언제 수익실현", "수익실현이 언제", "매도 시기")):
        result.update(id="realised_profit_timing", label_ko="수익실현 시기")
    elif any(token in q for token in ("수익실현", "익절", "매도 체결", "매도 가능")):
        result.update(id="realised_profit_event", label_ko="수익실현·매도 성사")
    elif any(token in lower for token in ("오를", "상승", "주가", "price")):
        result.update(id="asset_movement", label_ko="보유자산 가격 움직임")
    else:
        result.update(id="stock_general", label_ko="주식·투기적 투자 일반")
    return result


def _judgment_axis(data):
    sig = data.get("significators") or {}
    topic = str((data.get("question") or {}).get("topic") or "general")
    q = sig.get("querent") or {}
    t = sig.get("quesited") or {}
    e = sig.get("event") or {}
    return {
        "topic": topic,
        "routingUnchanged": True,
        "querent": {"house": q.get("house"), "ruler": q.get("ruler")},
        "quesited": {"house": t.get("house"), "ruler": t.get("ruler")},
        "event": ({"house": e.get("house"), "ruler": e.get("ruler")} if e else None),
        "routingNote": (data.get("question") or {}).get("topic_note_ko"),
        "stockAxisNote": (
            "현재 라우팅을 그대로 사용: 1H 질문자 / 5H 보유주식·투기적 투자 / 2H 사건 보조(내 돈). "
            "11H를 신규 핵심축으로 추가하지 않음."
            if topic == "stock" else None
        ),
    }


def _axis_relation(body: str, data):
    sig = data.get("significators") or {}
    topic = str((data.get("question") or {}).get("topic") or "general")
    if body == (sig.get("event") or {}).get("ruler"):
        if int((sig.get("event") or {}).get("house") or 0) == 2 and topic in {"stock", "money"}:
            return "direct_money"
        return "direct_event"
    if body == (sig.get("quesited") or {}).get("ruler"):
        return "direct_quesited"
    if body == (sig.get("querent") or {}).get("ruler"):
        return "direct_querent"
    return "supportive" if body in core.HORARY_PLANETS else "unrelated"


def _event_row(body: str, event: dict, data, timezone_name: str, phase: str):
    exact = _utc(event.get("exact_utc") or event.get("utc"))
    return {
        "time": _local(exact, timezone_name),
        "event": "major_aspect",
        "planet": body,
        "planet_ko": core.PLANET_KO.get(body, body),
        "aspectType": event.get("aspect"),
        "aspect_ko": event.get("aspect_ko"),
        "applying": phase != "previous",
        "phase": phase,
        "eventAxisRelation": _axis_relation(body, data),
        "engineSource": "horary_engine_v6._exact_events_between",
    }


def _future_exact(body_a, body_b, angle, dt_utc, horizon_end):
    try:
        return v6._find_exact_aspect(body_a, body_b, angle, dt_utc, horizon_end)
    except Exception:
        return None


_NO_EXACT_HINT = object()


_SWEPH_PLANETS = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mercury": swe.MERCURY,
    "Venus": swe.VENUS,
    "Mars": swe.MARS,
    "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN,
}


def _swiss_coarse_lons(body: str, times):
    planet = _SWEPH_PLANETS.get(str(body))
    if planet is None:
        raise KeyError(body)
    flags = swe.FLG_SWIEPH
    return np.fromiter(
        (
            float(swe.calc_ut(core.to_jd_ut(dt), planet, flags)[0][0] % 360.0)
            for dt in times
        ),
        dtype=float,
        count=len(times),
    )


def _batch_future_exact_hints(entries, dt_utc, horizon_end):
    """Share identical coarse exact-aspect grids across Judgment V2 pairs."""
    if not entries or horizon_end <= dt_utc:
        return {}

    span_days = max(0.01, (horizon_end - dt_utc).total_seconds() / 86400.0)
    groups = {}
    for entry in entries:
        body_a = entry["body_a"]
        body_b = entry["body_b"]
        step_hours = 0.5 if "Moon" in {body_a, body_b} else 1.5 if span_days < 7 else 3.0
        groups.setdefault(float(step_hours), []).append(entry)

    hints = {}
    for step_hours, rows in groups.items():
        times = list(core._sample_datetimes(dt_utc, horizon_end, step_hours))
        if len(times) < 2:
            for row in rows:
                hints[row["pair_id"]] = None
            continue

        bodies = tuple(dict.fromkeys(
            body
            for row in rows
            for body in (row["body_a"], row["body_b"])
        ))
        try:
            lons = {
                body: _swiss_coarse_lons(body, times)
                for body in bodies
            }
        except Exception:
            # Omit this group's hints so each pair falls back to the original path.
            continue

        for row in rows:
            body_a = row["body_a"]
            body_b = row["body_b"]
            angle = float(row["angle"])
            try:
                a_lons = lons[body_a]
                b_lons = lons[body_b]
                seps = np.abs((a_lons - b_lons + 180.0) % 360.0 - 180.0)
                errors = np.abs(seps - angle)
                idx = int(np.argmin(errors))
                if idx == 0 or float(errors[idx]) > 1.25:
                    hints[row["pair_id"]] = None
                    continue
                left = times[max(0, idx - 1)]
                right = times[min(len(times) - 1, idx + 1)]
                if right <= left:
                    hints[row["pair_id"]] = None
                    continue
                exact, orb = v6._refine_exact_aspect(body_a, body_b, angle, left, right)
                if exact < dt_utc or exact > horizon_end or orb > v6.ASPECT_EXACT_TOL:
                    hints[row["pair_id"]] = None
                    continue
                hints[row["pair_id"]] = {
                    "type": "exact_aspect",
                    "utc": exact.isoformat(),
                    "days_from_question": round((exact - dt_utc).total_seconds() / 86400.0, 6),
                    "exact_orb": round(orb, 6),
                }
            except Exception:
                # Preserve original per-pair exception handling if batching fails.
                continue

    return hints


def _pair_diagnostic(pair_id: str, role_a: str, a: dict, role_b: str, b: dict, data, dt_utc, timezone_name, exact_hint=_NO_EXACT_HINT):
    body_a, body_b = a.get("ruler"), b.get("ruler")
    row_a, row_b = a.get("planet"), b.get("planet")
    if not body_a or not body_b or not row_a or not row_b:
        return None
    if body_a == body_b:
        return {
            "pairId": pair_id,
            "pair": [body_a, body_b],
            "roles": [role_a, role_b],
            "sharedRuler": True,
            "finalStatus": "shared_ruler_no_separate_aspect",
            "currentJudgmentUnchanged": True,
        }

    state = v6._strict_aspect_state(body_a, row_a, body_b, row_b)
    angle = float(state.get("angle") or 0.0)
    horizon_end = dt_utc + timedelta(days=180)
    exact = (
        _future_exact(body_a, body_b, angle, dt_utc, horizon_end)
        if exact_hint is _NO_EXACT_HINT
        else exact_hint
    )
    exact_dt = _utc(exact["utc"]) if exact and exact.get("utc") else None

    orb_entry = None
    if not state.get("within_orb"):
        try:
            orb_entry = fw2._find_orb_entry(
                body_a, body_b, angle, float(state.get("max_orb") or 0.0), dt_utc, horizon_end
            )
        except Exception:
            orb_entry = None

    ingress_rows = []
    station_rows = []
    retrograde_before = False
    if exact_dt:
        span_days = max(1.0, (exact_dt - dt_utc).total_seconds() / 86400.0 + 0.1)
        for body, row in ((body_a, row_a), (body_b, row_b)):
            try:
                ingress = v6._next_sign_ingress(body, row, dt_utc, horizon_days=span_days)
                if ingress:
                    when = _utc(ingress.get("utc"))
                    if when < exact_dt:
                        ingress_rows.append({
                            "body": body,
                            "time": _local(when, timezone_name),
                            "fromSignIndex": ingress.get("from_sign_index"),
                            "toSignIndex": ingress.get("to_sign_index"),
                        })
            except Exception:
                pass
            try:
                station = v6._next_station(body, row, dt_utc, horizon_days=span_days)
                if station:
                    when = _utc(station.get("utc"))
                    if when < exact_dt:
                        speed_after = float(station.get("speed_after") or 0.0)
                        retrograde_before = retrograde_before or speed_after < -v6.STATION_SPEED_EPS
                        station_rows.append({
                            "body": body,
                            "time": _local(when, timezone_name),
                            "speedBefore": station.get("speed_before"),
                            "speedAfter": station.get("speed_after"),
                        })
            except Exception:
                pass

    breaks = bool(ingress_rows or station_rows)
    motion = state.get("motion_phase") or "unclear"
    if state.get("within_orb") and motion in {"applying", "exact"} and not breaks:
        final = "current_valid_perfection_path"
    elif state.get("within_orb") and motion == "separating":
        final = "current_separating_no_fresh_perfection"
    elif not state.get("within_orb") and motion == "applying" and exact_dt:
        final = "future_applying_reference_only" if not breaks else "future_application_interrupted_before_exact"
    elif motion == "separating":
        final = "separating"
    elif exact_dt and breaks:
        final = "aspect_breaks_before_perfection"
    else:
        final = "no_confirmed_perfection_path"

    return {
        "pairId": pair_id,
        "pair": [body_a, body_b],
        "roles": [role_a, role_b],
        "aspectType": state.get("aspect"),
        "aspect_ko": state.get("aspect_ko"),
        "currentAngularDistance": state.get("separation_deg"),
        "distanceToExact": state.get("error_now_deg"),
        "orbAllowed": state.get("max_orb"),
        "currentlyWithinOrb": bool(state.get("within_orb")),
        "applying": motion == "applying",
        "separating": motion == "separating",
        "relativeMotion": {
            "phase": motion,
            "method": state.get("motion_method"),
            "probeHours": state.get("motion_probe_hours"),
            "errorPastDeg": state.get("error_past_deg"),
            "errorNowDeg": state.get("error_now_deg"),
            "errorFutureDeg": state.get("error_future_deg"),
            "relativeSpeedDegPerDay": state.get("relative_speed_deg_per_day"),
        },
        "exactPerfectionAt": _local(exact_dt, timezone_name),
        "orbEntryAt": _local(orb_entry, timezone_name) if orb_entry else None,
        "signIngressBeforePerfection": ingress_rows,
        "stationBeforePerfection": station_rows,
        "retrogradeBeforePerfection": retrograde_before,
        "aspectBreaksBeforePerfection": breaks,
        "finalStatus": final,
        "currentPerfectionUnchanged": True,
        "engineEvidence": state,
    }


def _aspect_applications(data, dt_utc, timezone_name):
    sig = data.get("significators") or {}
    q = sig.get("querent") or {}
    t = sig.get("quesited") or {}
    e = sig.get("event") or {}
    moon = {"ruler": "Moon", "planet": sig.get("moon") or (data.get("planets") or {}).get("Moon")}
    specs = [
        ("querent_quesited", "querent", q, "quesited", t),
        ("querent_event", "querent", q, "event", e),
        ("quesited_event", "quesited", t, "event", e),
        ("moon_querent", "moon", moon, "querent", q),
        ("moon_quesited", "moon", moon, "quesited", t),
        ("moon_event", "moon", moon, "event", e),
    ]

    active = []
    seen = set()
    for pair_id, role_a, a, role_b, b in specs:
        if not a or not b:
            continue
        key = tuple(sorted([str(a.get("ruler") or ""), str(b.get("ruler") or "")])) + (pair_id.startswith("moon_"),)
        if pair_id.startswith("moon_") and a.get("ruler") == b.get("ruler"):
            continue
        if not pair_id.startswith("moon_") and key in seen:
            continue
        seen.add(key)
        active.append((pair_id, role_a, a, role_b, b))

    horizon_end = dt_utc + timedelta(days=180)
    batch_entries = []
    for pair_id, _role_a, a, _role_b, b in active:
        body_a, body_b = a.get("ruler"), b.get("ruler")
        row_a, row_b = a.get("planet"), b.get("planet")
        if not body_a or not body_b or not row_a or not row_b or body_a == body_b:
            continue
        state = v6._strict_aspect_state(body_a, row_a, body_b, row_b)
        batch_entries.append({
            "pair_id": pair_id,
            "body_a": body_a,
            "body_b": body_b,
            "angle": float(state.get("angle") or 0.0),
        })
    exact_hints = _batch_future_exact_hints(batch_entries, dt_utc, horizon_end)

    rows = []
    for pair_id, role_a, a, role_b, b in active:
        hint = exact_hints[pair_id] if pair_id in exact_hints else _NO_EXACT_HINT
        row = _pair_diagnostic(
            pair_id, role_a, a, role_b, b, data, dt_utc, timezone_name,
            exact_hint=hint,
        )
        if row:
            rows.append(row)
    return rows


def _voc(data, dt_utc, timezone_name):
    j = data.get("judgment_support") or {}
    moon_course = j.get("moon_course") or {}
    moon = (data.get("planets") or {}).get("Moon") or {}
    ingress = None
    try:
        ingress = v6._next_sign_ingress("Moon", moon, dt_utc, horizon_days=4.0)
    except Exception:
        pass
    exit_dt = _utc(ingress.get("utc")) if ingress and ingress.get("utc") else None
    exact_rows = []
    if exit_dt:
        for body in core.HORARY_PLANETS:
            if body == "Moon":
                continue
            try:
                for event in v6._exact_events_between("Moon", body, dt_utc, exit_dt):
                    exact_rows.append(_event_row(body, event, data, timezone_name, "before_sign_exit"))
            except Exception:
                pass
        exact_rows.sort(key=lambda x: x.get("time") or "")
    return {
        "policy": "current_sign_only_exact_ptolemaic_aspects_to_traditional_seven",
        "isVoid": bool(moon_course.get("void_of_course")),
        "signExitAt": _local(exit_dt, timezone_name),
        "applyingAspectsBeforeExit": deepcopy(moon_course.get("next_aspects") or []),
        "exactAspectsBeforeExit": exact_rows,
        "scope": "current_sign_only",
        "notEquivalentToEventFailure": True,
        "futureWindowMayContinueAfterIngress": True,
    }


def _moon_flow(data, dt_utc, timezone_name, aspects):
    planets = data.get("planets") or {}
    moon = planets.get("Moon") or {}
    if not moon:
        return {}

    prev_ingress = None
    next_ingress = None
    try:
        prev_ingress = v6._previous_sign_ingress("Moon", moon, dt_utc, horizon_days=5.0)
        next_ingress = v6._next_sign_ingress("Moon", moon, dt_utc, horizon_days=4.0)
    except Exception:
        pass
    exit_dt = _utc(next_ingress.get("utc")) if next_ingress and next_ingress.get("utc") else None

    previous = []
    if prev_ingress:
        for body in core.HORARY_PLANETS:
            if body == "Moon":
                continue
            try:
                previous.extend(_event_row(body, e, data, timezone_name, "previous") for e in v6._exact_events_between("Moon", body, prev_ingress, dt_utc))
            except Exception:
                pass
    previous.sort(key=lambda x: x.get("time") or "")

    future = []
    if exit_dt:
        for body in core.HORARY_PLANETS:
            if body == "Moon":
                continue
            try:
                future.extend(_event_row(body, e, data, timezone_name, "before_sign_exit") for e in v6._exact_events_between("Moon", body, dt_utc, exit_dt))
            except Exception:
                pass
    future.sort(key=lambda x: x.get("time") or "")

    first_after = None
    if exit_dt:
        after_start = exit_dt + timedelta(seconds=3)
        try:
            state_after = fw2._planet_state("Moon", after_start)
            next_after = v6._next_sign_ingress("Moon", state_after, after_start, horizon_days=4.0)
            after_end = _utc(next_after.get("utc")) if next_after and next_after.get("utc") else after_start + timedelta(days=3)
            after_rows = []
            for body in core.HORARY_PLANETS:
                if body == "Moon":
                    continue
                for event in v6._exact_events_between("Moon", body, after_start, after_end):
                    after_rows.append(_event_row(body, event, data, timezone_name, "after_ingress"))
            after_rows.sort(key=lambda x: x.get("time") or "")
            first_after = after_rows[0] if after_rows else None
        except Exception:
            first_after = None

    current_applying = []
    for row in aspects:
        if not str(row.get("pairId") or "").startswith("moon_"):
            continue
        if row.get("currentlyWithinOrb") and row.get("applying"):
            current_applying.append(row)
    current_applying.sort(key=lambda x: (x.get("distanceToExact") is None, x.get("distanceToExact") or 999.0))

    core8 = _core_v8(data)
    indirect = core8.get("indirect_perfection") or {}
    translation = [x for x in (indirect.get("translation_of_light") or []) if (x or {}).get("translator") == "Moon"]
    interventions = (core8.get("interventions") or {}).get("prohibition_or_frustration") or []
    moon_interventions = [x for x in interventions if "Moon" in str(x)]

    events = []
    if previous:
        events.append(previous[-1])
    events.extend(future)
    if next_ingress:
        events.append({
            "time": _local(exit_dt, timezone_name),
            "event": "sign_ingress",
            "planet": "Moon",
            "applying": False,
            "phase": "sign_ingress",
            "eventAxisRelation": "none",
            "fromSignIndex": next_ingress.get("from_sign_index"),
            "toSignIndex": next_ingress.get("to_sign_index"),
        })
    if first_after:
        events.append(first_after)
    events.sort(key=lambda x: x.get("time") or "")

    return {
        "previousMajorAspect": previous[-1] if previous else None,
        "currentApplyingAspect": current_applying[0] if current_applying else None,
        "nextMajorAspect": future[0] if future else None,
        "laterAspectsBeforeSignExit": future[1:] if len(future) > 1 else [],
        "signIngressAt": _local(exit_dt, timezone_name),
        "firstAspectAfterIngress": first_after,
        "translationCandidate": translation[0] if translation else None,
        "prohibitionCandidate": moon_interventions[0] if moon_interventions else None,
        "finalAspectBeforeSignExit": future[-1] if future else None,
        "events": events,
        "orderedEvidenceOnly": True,
    }


def _reception(data):
    j = data.get("judgment_support") or {}
    core8 = _core_v8(data)
    direct = core8.get("direct_axis") or {}
    raw = direct.get("reception") or j.get("reception") or {}
    return {
        "A": raw.get("a"),
        "B": raw.get("b"),
        "AReceivesB": deepcopy(raw.get("b_received_by_a")),
        "BReceivesA": deepcopy(raw.get("a_received_by_b")),
        "mutual": bool(raw.get("mutual") or raw.get("mutual_reception")),
        "strength": raw.get("grade") or ("present" if raw.get("has_reception") else "none"),
        "weightLegacy": raw.get("weight"),
        "modifiesPerfection": False,
        "modifiesEventQuality": True,
        "interpretationBoundary": "수용·협력·관계 조건. 사건 성사 연결(Perfection)과 분리.",
        "raw": deepcopy(raw),
    }


def _dignity(data):
    j = data.get("judgment_support") or {}
    profiles = deepcopy(j.get("essential_dignities_v7") or {})
    return {
        "profiles": profiles,
        "supportedStates": ["domicile", "exaltation", "triplicity", "term", "face", "detriment", "fall", "peregrine"],
        "interpretationBoundary": "행성의 상태·행동 역량을 설명하는 보조층. 단독으로 사건 실패/성공을 결정하지 않음.",
        "forbiddenInferences": [
            "fall => event_failure",
            "detriment => certain_loss",
            "peregrine => impossible_perfection",
        ],
    }


def _perfection(data, aspects):
    j = data.get("judgment_support") or {}
    core8 = _core_v8(data)
    legacy = deepcopy(j.get("perfection") or {})
    indirect = core8.get("indirect_perfection") or {}
    translations = [x for x in (indirect.get("translation_of_light") or []) if (x or {}).get("classification") in {None, "confirmed_pattern"}]
    collections = [x for x in (indirect.get("collection_of_light") or []) if (x or {}).get("classification") in {None, "confirmed_pattern"}]
    if legacy.get("perfects"):
        current = "direct_perfection"
        path = "direct"
    elif translations:
        current = "translation_of_light"
        path = "translation_of_light"
    elif collections:
        current = "collection_of_light"
        path = "collection_of_light"
    else:
        current = "no_perfection"
        path = None

    future_candidates = [x for x in aspects if x.get("exactPerfectionAt") and x.get("applying")]
    future_candidates.sort(key=lambda x: x.get("exactPerfectionAt") or "")
    future_exact = future_candidates[0].get("exactPerfectionAt") if future_candidates else None
    fw = j.get("future_window_v1") or {}
    within = False
    if fw.get("active") and future_exact:
        start = (fw.get("targetWindow") or {}).get("start")
        end = (fw.get("targetWindow") or {}).get("end")
        within = bool(start and end and start <= future_exact <= end)
    return {
        "current": current,
        "path": path,
        "legacyCurrent": legacy,
        "translationOfLight": translations,
        "collectionOfLight": collections,
        "futureExactAt": future_exact,
        "withinTargetWindow": within,
        "futureOutsideWindowType": "future_perfection_outside_window" if future_exact and not within else None,
        "currentJudgmentUnchanged": True,
    }


def _obstruction(data, aspects, perfection):
    core8 = _core_v8(data)
    interventions = core8.get("interventions") or {}
    legacy = list(interventions.get("prohibition_or_frustration") or [])
    if interventions.get("refranation"):
        legacy.append(interventions.get("refranation"))

    primary_pair = next((x for x in aspects if x.get("pairId") == "querent_quesited"), None)
    applying_path = bool(primary_pair and primary_pair.get("applying"))
    checks = []
    if applying_path and primary_pair:
        for row in primary_pair.get("signIngressBeforePerfection") or []:
            checks.append({
                "type": "sign_change_before_perfection",
                "classification": "structural_interruption_candidate",
                "planet": row.get("body"),
                "occursAt": row.get("time"),
                "beforePerfection": True,
            })
            checks.append({
                "type": "evasion_candidate",
                "classification": "structural_interruption_candidate",
                "planet": row.get("body"),
                "occursAt": row.get("time"),
                "beforePerfection": True,
                "note": "V2 evidence label only; legacy grade is not changed.",
            })
        for row in primary_pair.get("stationBeforePerfection") or []:
            checks.append({
                "type": "station_before_perfection",
                "classification": "structural_interruption_candidate",
                "planet": row.get("body"),
                "occursAt": row.get("time"),
                "beforePerfection": True,
            })
        if primary_pair.get("retrogradeBeforePerfection"):
            checks.append({
                "type": "retrograde_before_perfection",
                "classification": "structural_interruption_candidate",
                "beforePerfection": True,
            })

    confirmed = [x for x in legacy if isinstance(x, dict) and x.get("classification") == "confirmed_pattern"]
    return {
        "applicable": applying_path,
        "reason": "primary_significator_pair_applying" if applying_path else "no_primary_applying_path_no_obstruction_inference",
        "legacyConfirmed": confirmed if applying_path else [],
        "structuralChecks": checks if applying_path else [],
        "typesChecked": [
            "prohibition", "frustration", "refranation", "evasion_candidate",
            "sign_change_before_perfection", "station_before_perfection",
            "retrograde_before_perfection", "third_planet_interference",
        ],
        "currentJudgmentUnchanged": True,
    }


def _current_judgment(data):
    j = data.get("judgment_support") or {}
    h = _hierarchy(data)
    core8 = _core_v8(data)
    grade = h.get("qualified_evidence_grade_v8") or core8.get("qualified_evidence_grade_v8") or core8.get("qualified_evidence_grade_v7") or core8.get("evidence_grade") or "NONE"
    band = h.get("grade_band_v8") or core8.get("grade_band_v8") or (str(grade)[:1] if str(grade)[:1] in "ABCD" else "NONE")
    return {
        "grade": grade,
        "gradeBand": band,
        "overallState": h.get("overall_state_v8") or core8.get("overall_state_v8"),
        "overallLabel_ko": h.get("overall_ko_v8") or core8.get("overall_ko_v8"),
        "actionState": deepcopy(h.get("action_state_v8") or core8.get("action_state_v8") or {}),
        "currentPerfection": bool((j.get("perfection") or {}).get("perfects")),
        "perfectionReason": (j.get("perfection") or {}).get("reason"),
        "voc": bool((j.get("moon_course") or {}).get("void_of_course")),
        "legacyJudgmentAuthoritative": True,
        "futureWindowCannotPromoteOrDemote": True,
    }


def _future_development(data):
    fw = deepcopy((data.get("judgment_support") or {}).get("future_window_v1") or {})
    if not fw.get("active"):
        return {"active": False, "currentJudgmentUnchanged": True}
    return {
        "active": True,
        "version": fw.get("version"),
        "start": (fw.get("targetWindow") or {}).get("start"),
        "end": (fw.get("targetWindow") or {}).get("end"),
        "sourceText": fw.get("sourceText") or fw.get("source"),
        "dailySnapshots": fw.get("dailySummaries") or [],
        "events": fw.get("events") or [],
        "ingresses": fw.get("ingresses") or [],
        "aspectDevelopment": fw.get("futureAspectDevelopment") or [],
        "moonFutureFlow": fw.get("moonFutureFlow") or {},
        "currentJudgmentUnchanged": True,
        "doesNotChangePerfection": True,
    }


def _confidence(data, perfection, aspects):
    j = data.get("judgment_support") or {}
    core8 = _core_v8(data)
    route = j.get("route_contract_v7") or {}
    warnings = j.get("warnings") or []
    q_t = next((x for x in aspects if x.get("pairId") == "querent_quesited"), None)

    chart = "usable"
    if warnings:
        chart = "usable_with_considerations"
    sig = "clear" if route.get("matches_spec", True) else "routing_mismatch"
    if q_t and q_t.get("sharedRuler"):
        sig = "shared_ruler"
    if perfection.get("current") == "direct_perfection":
        perf = "direct_current_path"
    elif perfection.get("current") in {"translation_of_light", "collection_of_light"}:
        perf = "indirect_current_path"
    else:
        perf = "no_current_perfection"
    if perfection.get("futureExactAt"):
        timing = "future_exact_reference_available"
    elif (j.get("future_window_v1") or {}).get("active"):
        timing = "future_window_without_exact_reference"
    else:
        timing = "not_requested_or_limited"

    if sig == "routing_mismatch":
        overall = "limited_by_routing_mismatch"
    elif perf == "no_current_perfection":
        overall = "limited_event_evidence"
    elif chart == "usable_with_considerations":
        overall = "mixed_but_traceable"
    else:
        overall = "clear_engine_evidence"
    return {
        "chartRadicality": chart,
        "significatorClarity": sig,
        "perfectionClarity": perf,
        "timingClarity": timing,
        "overall": overall,
        "probabilityPercent": None,
        "note": "정성적 근거 명료도만 표시하며 확률 %를 생성하지 않음.",
    }


def _postprocess(data):
    if not isinstance(data, dict) or data.get("schema") != "LUNEA_HORARY_V1":
        return data
    moment = data.get("moment") or {}
    dt_utc = _utc(moment.get("utc_iso"))
    timezone_name = str(moment.get("timezone") or "Asia/Seoul")
    question = data.get("question") or {}
    topic = str(question.get("topic") or "general")

    aspects = _aspect_applications(data, dt_utc, timezone_name)
    current = _current_judgment(data)
    perfection = _perfection(data, aspects)
    reception = _reception(data)
    dignity = _dignity(data)
    obstruction = _obstruction(data, aspects, perfection)
    voc = _voc(data, dt_utc, timezone_name)
    moon_flow = _moon_flow(data, dt_utc, timezone_name, aspects)
    future = _future_development(data)
    axis = _judgment_axis(data)
    intent = _intent(question.get("text") or "", topic)
    confidence = _confidence(data, perfection, aspects)

    event_quality = {
        "reception": reception,
        "dignity": dignity,
        "obstruction": obstruction,
        "directAspectTone": (_core_v8(data).get("direct_aspect_tone_v7")),
        "doesNotDetermineEventByItself": True,
    }

    v2 = {
        "version": VERSION,
        "horaryRuleset": _ruleset(data),
        "questionIntent": intent,
        "judgmentAxis": axis,
        "radicalJudgment": current,
        "currentJudgment": current,
        "aspectApplications": aspects,
        "voc": voc,
        "perfection": perfection,
        "obstruction": obstruction,
        "reception": reception,
        "dignity": dignity,
        "moonFlow": moon_flow,
        "futureDevelopment": future,
        "eventQuality": event_quality,
        "confidence": confidence,
        "separationContract": {
            "currentJudgmentSeparateFromFutureDevelopment": True,
            "eventQualitySeparateFromPerfection": True,
            "futureCannotChangeLegacyGrade": True,
            "aiIsInterpreterNotCalculator": True,
        },
        "aiInterpretationGuardrails": {
            "outputOrder": [
                "questionIntent", "currentRadicalJudgment", "directPerfectionPath",
                "moonEventFlow", "reception", "dignity", "obstruction",
                "futureWindow", "counterEvidence", "uncertainty", "oneLineConclusion",
            ],
            "forbidden": [
                "invent_aspect", "future_perfection_as_current_perfection",
                "voc_equals_automatic_failure", "reception_equals_event_perfection",
                "dignity_weakness_equals_event_failure", "supportive_equals_direct_event",
                "none_or_d_equals_automatic_no", "partial_future_window_as_whole_window",
            ],
            "evidencePathRequired": True,
        },
    }

    j = data.setdefault("judgment_support", {})
    j["horary_v2"] = v2
    data["horaryRuleset"] = deepcopy(v2["horaryRuleset"])
    data.setdefault("meta", {})["horary_judgment_schema"] = VERSION
    return data


def _compute_horary_v2(*args, **kwargs):
    return _postprocess(_ORIGINAL_COMPUTE_HORARY(*args, **kwargs))


if not getattr(v31.compute_horary, "_lunea_horary_v2_judgment", False):
    _compute_horary_v2._lunea_horary_v2_judgment = True
    v31.compute_horary = _compute_horary_v2
