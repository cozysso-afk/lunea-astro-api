from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np

import astro_core as core
import horary_balance_v31 as v31
import horary_engine_v6 as v6


VERSION = "LUNEA_HORARY_FUTURE_WINDOW_V2"
_ORIGINAL_COMPUTE_HORARY = v31.compute_horary

_RANGE_SEP = r"(?:~|〜|～|–|—|-|부터)"
_WEEKDAY = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
_RELATIVE = {"오늘": 0, "내일": 1, "모레": 2}
_SIGN_KO = [
    "양자리", "황소자리", "쌍둥이자리", "게자리", "사자자리", "처녀자리",
    "천칭자리", "전갈자리", "사수자리", "염소자리", "물병자리", "물고기자리",
]


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "Asia/Seoul")
    except Exception:
        return ZoneInfo("Asia/Seoul")


def _date_for_month_day(local_question: datetime, month: int, day: int, *, year: int | None = None) -> date:
    y = int(year or local_question.year)
    candidate = date(y, int(month), int(day))
    if year is None and candidate < local_question.date() - timedelta(days=31):
        candidate = date(y + 1, int(month), int(day))
    return candidate


def _roll_end_date(start: date, month: int | None, day: int, year: int | None = None) -> date:
    if year is not None:
        return date(int(year), int(month or start.month), int(day))
    m = int(month or start.month)
    y = start.year
    candidate = date(y, m, int(day))
    if candidate < start:
        if month is not None:
            candidate = date(y + 1, m, int(day))
        else:
            nm = 1 if start.month == 12 else start.month + 1
            ny = start.year + 1 if start.month == 12 else start.year
            candidate = date(ny, nm, int(day))
    return candidate


def _window(start_date: date, end_date: date, source: str, zone: ZoneInfo):
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    start_local = datetime.combine(start_date, time(0, 0, 0), tzinfo=zone)
    end_local = datetime.combine(end_date, time(23, 59, 59), tzinfo=zone)
    return {
        "sourceText": source,
        "start_date": start_date,
        "end_date": end_date,
        "start_local": start_local,
        "end_local": end_local,
        "start_utc": start_local.astimezone(ZoneInfo("UTC")),
        "end_utc": end_local.astimezone(ZoneInfo("UTC")),
    }


def parse_target_window(question_text: str, dt_utc: datetime, timezone_name: str):
    text = str(question_text or "").strip()
    if not text:
        return None
    zone = _zone(timezone_name)
    local_question = dt_utc.astimezone(zone)

    m = re.search(rf"(오늘|내일|모레)\s*{_RANGE_SEP}\s*(오늘|내일|모레)(?:\s*까지)?", text)
    if m:
        a = local_question.date() + timedelta(days=_RELATIVE[m.group(1)])
        b = local_question.date() + timedelta(days=_RELATIVE[m.group(2)])
        return _window(a, b, m.group(0), zone)

    m = re.search(rf"이번\s*주\s*([월화수목금토일])(?:요일)?\s*{_RANGE_SEP}\s*([월화수목금토일])(?:요일)?(?:\s*까지)?", text)
    if m:
        monday = local_question.date() - timedelta(days=local_question.weekday())
        a = monday + timedelta(days=_WEEKDAY[m.group(1)])
        b = monday + timedelta(days=_WEEKDAY[m.group(2)])
        if b < a:
            b += timedelta(days=7)
        return _window(a, b, m.group(0), zone)

    m = re.search(
        rf"(?<!\d)(20\d{{2}})\s*[./-]\s*(\d{{1,2}})\s*[./-]\s*(\d{{1,2}})\s*{_RANGE_SEP}\s*"
        rf"(20\d{{2}})\s*[./-]\s*(\d{{1,2}})\s*[./-]\s*(\d{{1,2}})(?:\s*까지)?",
        text,
    )
    if m:
        try:
            a = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            b = date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
            return _window(a, b, m.group(0), zone)
        except ValueError:
            pass

    m = re.search(
        rf"(?<!\d)(\d{{1,2}})\s*/\s*(\d{{1,2}})\s*{_RANGE_SEP}\s*"
        rf"(?:(\d{{1,2}})\s*/\s*)?(\d{{1,2}})(?:\s*까지)?",
        text,
    )
    if m:
        try:
            a = _date_for_month_day(local_question, int(m.group(1)), int(m.group(2)))
            b = _roll_end_date(a, int(m.group(3)) if m.group(3) else None, int(m.group(4)))
            return _window(a, b, m.group(0), zone)
        except ValueError:
            pass

    m = re.search(
        rf"(?<!\d)(\d{{1,2}})\s*월\s*(\d{{1,2}})\s*일\s*{_RANGE_SEP}\s*"
        rf"(?:(\d{{1,2}})\s*월\s*)?(\d{{1,2}})\s*일(?:\s*까지)?",
        text,
    )
    if m:
        try:
            a = _date_for_month_day(local_question, int(m.group(1)), int(m.group(2)))
            b = _roll_end_date(a, int(m.group(3)) if m.group(3) else None, int(m.group(4)))
            return _window(a, b, m.group(0), zone)
        except ValueError:
            pass

    for token, days in (("모레", 2), ("내일", 1), ("오늘", 0)):
        if token in text:
            d = local_question.date() + timedelta(days=days)
            return _window(d, d, token, zone)

    patterns = [
        (r"(?<!\d)(20\d{2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{1,2})(?!\d)", True),
        (r"(?<!\d)(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", True),
        (r"(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?!\d)", False),
        (r"(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일", False),
    ]
    for pattern, has_year in patterns:
        m = re.search(pattern, text)
        if not m:
            continue
        try:
            if has_year:
                d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            else:
                d = _date_for_month_day(local_question, int(m.group(1)), int(m.group(2)))
            return _window(d, d, m.group(0), zone)
        except ValueError:
            continue
    return None


def _local(dt_utc: datetime, timezone_name: str) -> str:
    return dt_utc.astimezone(_zone(timezone_name)).isoformat()


def _planet_state(body: str, dt_utc: datetime):
    lon, speed, direction = core.planet_motion(body, dt_utc)
    sign_index = int(float(lon) // 30.0) % 12
    return {
        "longitude": float(lon),
        "speed_deg_per_day": float(speed),
        "direction": direction,
        "sign_index": sign_index,
        "sign_en": core.SIGNS_EN[sign_index],
        "sign_ko": _SIGN_KO[sign_index],
    }


def _aspect_error(body_a: str, body_b: str, angle: float, dt_utc: datetime) -> float:
    a = core.get_tropical_ecliptic_lon(body_a, core.sf_time(dt_utc))
    b = core.get_tropical_ecliptic_lon(body_b, core.sf_time(dt_utc))
    return abs(core.angular_separation(float(a), float(b)) - float(angle))


def _nearest_aspect(body_a: str, row_a, body_b: str, row_b):
    sep = core.angular_separation(float(row_a["longitude"]), float(row_b["longitude"]))
    rows = []
    for key, spec in core.HORARY_ASPECTS.items():
        rows.append((abs(float(sep) - float(spec["angle"])), key, spec))
    error, key, spec = min(rows)
    limit = float(core._horary_aspect_limit(body_a, body_b, key))
    return {
        "aspect": key,
        "aspect_ko": spec.get("label_ko", key),
        "angle": float(spec["angle"]),
        "separation_deg": float(sep),
        "distance_to_exact_deg": float(error),
        "max_orb_deg": limit,
        "within_orb": bool(error <= limit + 1e-9),
    }


def _trend(body_a: str, body_b: str, angle: float, dt_utc: datetime, current_error: float):
    probe = 0.5 if "Moon" in {body_a, body_b} else 2.0
    later = _aspect_error(body_a, body_b, angle, dt_utc + timedelta(hours=probe))
    if later + v6.ASPECT_MOTION_EPS < current_error:
        return "applying"
    if later > current_error + v6.ASPECT_MOTION_EPS:
        return "separating"
    return "unclear"


def _find_orb_entry(body_a: str, body_b: str, angle: float, limit: float, start: datetime, end: datetime):
    if end <= start:
        return None
    current = _aspect_error(body_a, body_b, angle, start)
    if current <= limit + 1e-9:
        return start
    step = timedelta(minutes=30 if "Moon" in {body_a, body_b} else 60)
    left = start
    left_error = current
    while left < end:
        right = min(end, left + step)
        right_error = _aspect_error(body_a, body_b, angle, right)
        if left_error > limit and right_error <= limit:
            lo, hi = left, right
            for _ in range(28):
                mid = lo + (hi - lo) / 2
                if _aspect_error(body_a, body_b, angle, mid) <= limit:
                    hi = mid
                else:
                    lo = mid
            return hi
        left, left_error = right, right_error
    return None


def _all_ingresses(body: str, start: datetime, end: datetime, timezone_name: str):
    if end <= start:
        return []

    if body == "Moon":
        step = timedelta(minutes=30)
        chunk = timedelta(days=3)
    elif body in {"Mercury", "Venus", "Mars", "Sun"}:
        step = timedelta(minutes=60)
        chunk = timedelta(days=10)
    else:
        step = timedelta(minutes=180)
        chunk = timedelta(days=30)

    out = []
    left = start
    left_sign = v6._sign_index_at(body, left)

    while left < end:
        chunk_end = min(end, left + chunk)
        times = []
        cursor = left
        while cursor < chunk_end:
            cursor = min(chunk_end, cursor + step)
            times.append(cursor)

        if not times:
            break

        try:
            lons = np.asarray(core.get_tropical_ecliptic_lons(body, times), dtype=float)
            signs = np.asarray(np.floor(np.mod(lons, 360.0) / 30.0), dtype=int)
        except Exception:
            # Preserve the original scalar behavior if vector evaluation fails.
            right = min(end, left + step)
            right_sign = v6._sign_index_at(body, right)
            if right_sign != left_sign:
                exact = v6._refine_sign_ingress(body, left, right, left_sign)
                to_sign = v6._sign_index_at(body, exact + timedelta(seconds=2))
                out.append({
                    "type": "sign_ingress",
                    "body": body,
                    "body_ko": core.PLANET_KO.get(body, body),
                    "utc": exact.isoformat(),
                    "time_local": _local(exact, timezone_name),
                    "from_sign_index": left_sign,
                    "to_sign_index": to_sign,
                    "from_sign_en": core.SIGNS_EN[left_sign],
                    "to_sign_en": core.SIGNS_EN[to_sign],
                    "from_sign_ko": _SIGN_KO[left_sign],
                    "to_sign_ko": _SIGN_KO[to_sign],
                })
                left = exact + timedelta(seconds=3)
                left_sign = v6._sign_index_at(body, left)
                continue
            left = right
            left_sign = right_sign
            continue

        previous_time = left
        previous_sign = left_sign
        crossing_index = None
        for index, right_sign in enumerate(signs):
            if int(right_sign) != int(previous_sign):
                crossing_index = index
                break
            previous_time = times[index]
            previous_sign = int(right_sign)

        if crossing_index is None:
            left = times[-1]
            left_sign = int(signs[-1])
            continue

        right = times[crossing_index]
        exact = v6._refine_sign_ingress(body, previous_time, right, previous_sign)
        to_sign = v6._sign_index_at(body, exact + timedelta(seconds=2))
        out.append({
            "type": "sign_ingress",
            "body": body,
            "body_ko": core.PLANET_KO.get(body, body),
            "utc": exact.isoformat(),
            "time_local": _local(exact, timezone_name),
            "from_sign_index": previous_sign,
            "to_sign_index": to_sign,
            "from_sign_en": core.SIGNS_EN[previous_sign],
            "to_sign_en": core.SIGNS_EN[to_sign],
            "from_sign_ko": _SIGN_KO[previous_sign],
            "to_sign_ko": _SIGN_KO[to_sign],
        })
        # Match the scalar implementation exactly: restart three seconds after
        # the refined ingress and establish the new sign from that instant.
        left = exact + timedelta(seconds=3)
        left_sign = v6._sign_index_at(body, left)

    return out

def _scope(dt: datetime | None, target) -> str | None:
    if not dt:
        return None
    if dt < target["start_utc"]:
        return "before_target_window"
    if dt <= target["end_utc"]:
        return "within_target_window"
    return "after_target_window"


def _sample_points(target, topic: str, timezone_name: str):
    zone = _zone(timezone_name)
    out = []
    d = target["start_date"]
    while d <= target["end_date"]:
        points = [
            ("day_start", datetime.combine(d, time(0, 0), tzinfo=zone)),
        ]
        if topic == "stock":
            points.extend([
                ("market_open_reference", datetime.combine(d, time(9, 0), tzinfo=zone)),
                ("market_close_reference", datetime.combine(d, time(15, 30), tzinfo=zone)),
            ])
        points.append(("day_end", datetime.combine(d, time(23, 59, 59), tzinfo=zone)))
        for label, local_dt in points:
            out.append((d.isoformat(), label, local_dt.astimezone(ZoneInfo("UTC"))))
        d += timedelta(days=1)
    return out


def _pair_development(pair_id: str, roles: list[str], body_a: str, row_a, body_b: str, row_b,
                      dt_utc: datetime, target, topic: str, timezone_name: str):
    if not body_a or not body_b or body_a == body_b:
        return {
            "pair": pair_id,
            "roles": roles,
            "a": body_a,
            "b": body_b,
            "shared_ruler": body_a == body_b and bool(body_a),
            "direct_event_axis": True,
            "supportive_only": False,
            "currentPerfectionUnchanged": True,
        }

    current = _nearest_aspect(body_a, row_a, body_b, row_b)
    trend = _trend(body_a, body_b, current["angle"], dt_utc, current["distance_to_exact_deg"])
    search_end = min(target["end_utc"] + timedelta(days=45), dt_utc + timedelta(days=180))
    orb_entry = None if current["within_orb"] else _find_orb_entry(
        body_a, body_b, current["angle"], current["max_orb_deg"], dt_utc, search_end
    )
    exact_row = v6._find_exact_aspect(body_a, body_b, current["angle"], dt_utc, search_end)
    exact_dt = v6._parse_utc(exact_row["utc"]) if exact_row else None

    blocker = None
    if exact_dt:
        candidates = []
        for body, row in ((body_a, row_a), (body_b, row_b)):
            try:
                ing = v6._next_sign_ingress(body, row, dt_utc, horizon_days=max(1.0, (exact_dt - dt_utc).total_seconds() / 86400.0 + 0.1))
                if ing:
                    candidates.append((v6._parse_utc(ing["utc"]), "sign_ingress", body))
            except Exception:
                pass
            try:
                station = v6._next_station(body, row, dt_utc, horizon_days=max(1.0, (exact_dt - dt_utc).total_seconds() / 86400.0 + 0.1))
                if station:
                    candidates.append((v6._parse_utc(station["utc"]), "station", body))
            except Exception:
                pass
        candidates = [x for x in candidates if x[0] < exact_dt]
        if candidates:
            when, kind, body = min(candidates, key=lambda x: x[0])
            blocker = {"type": kind, "body": body, "time_local": _local(when, timezone_name)}

    samples = []
    for sample_date, label, sample_utc in _sample_points(target, topic, timezone_name):
        err = _aspect_error(body_a, body_b, current["angle"], sample_utc)
        a_lon = core.get_tropical_ecliptic_lon(body_a, core.sf_time(sample_utc))
        b_lon = core.get_tropical_ecliptic_lon(body_b, core.sf_time(sample_utc))
        samples.append({
            "date": sample_date,
            "label": label,
            "time_local": _local(sample_utc, timezone_name),
            "separation_deg": round(core.angular_separation(float(a_lon), float(b_lon)), 4),
            "distance_to_exact_deg": round(float(err), 4),
            "within_orb": bool(err <= current["max_orb_deg"] + 1e-9),
        })

    return {
        "pair": pair_id,
        "roles": roles,
        "a": body_a,
        "a_ko": core.PLANET_KO.get(body_a, body_a),
        "b": body_b,
        "b_ko": core.PLANET_KO.get(body_b, body_b),
        "aspect": current["aspect"],
        "aspect_ko": current["aspect_ko"],
        "direct_event_axis": True,
        "supportive_only": False,
        "question_time": {
            "separation_deg": round(current["separation_deg"], 4),
            "distance_to_exact_deg": round(current["distance_to_exact_deg"], 4),
            "max_orb_deg": round(current["max_orb_deg"], 4),
            "within_orb": current["within_orb"],
            "motion": trend,
        },
        "samples": samples,
        "orb_entry": ({
            "time_local": _local(orb_entry, timezone_name),
            "scope": _scope(orb_entry, target),
            "label_ko": "Future Window 중 유효 orb 진입" if _scope(orb_entry, target) == "within_target_window" else "목표기간 밖 유효 orb 진입 참고",
        } if orb_entry else None),
        "exact_perfection_reference": ({
            "time_local": _local(exact_dt, timezone_name),
            "scope": _scope(exact_dt, target),
            "traditional_continuity": blocker is None,
            "blocker_before_exact": blocker,
            "label_ko": "목표기간 내 exact perfection" if _scope(exact_dt, target) == "within_target_window" else "목표기간 후 perfection 참고",
        } if exact_dt else None),
        "currentPerfectionUnchanged": True,
        "note_ko": "미래 접근·orb 진입·정확각 시각은 현재 차트의 Perfection/grade를 자동 변경하지 않습니다.",
    }


def _current_judgment_snapshot(data):
    j = data.get("judgment_support") or {}
    h = j.get("judgment_hierarchy_v8") or {}
    core8 = j.get("traditional_core_v8") or {}
    return {
        "grade": h.get("qualified_evidence_grade_v8") or core8.get("qualified_evidence_grade_v8") or core8.get("evidence_grade") or "NONE",
        "gradeBand": h.get("grade_band_v8") or core8.get("grade_band_v8") or "NONE",
        "currentPerfection": bool((j.get("perfection") or {}).get("perfects")),
        "perfectionReason": (j.get("perfection") or {}).get("reason"),
        "receptionPreserved": True,
        "dignityPreserved": True,
        "voc": bool((j.get("moon_course") or {}).get("void_of_course")),
    }


def build_future_window(data, dt_utc: datetime, timezone_name: str):
    question = ((data.get("question") or {}).get("text") or "")
    target = parse_target_window(question, dt_utc, timezone_name)
    if not target or target["end_utc"] < dt_utc:
        return {
            "version": VERSION,
            "active": False,
            "reason": "no_future_target_window",
            "currentJudgmentUnchanged": True,
            "does_not_change_perfection": True,
        }

    sig = data.get("significators") or {}
    planets = data.get("planets") or {}
    topic = str((data.get("question") or {}).get("topic") or "general")
    roles_by_body: dict[str, list[str]] = {}

    def add_role(role: str, body: str | None):
        if body:
            roles_by_body.setdefault(body, [])
            if role not in roles_by_body[body]:
                roles_by_body[body].append(role)

    add_role("querent", (sig.get("querent") or {}).get("ruler"))
    add_role("quesited", (sig.get("quesited") or {}).get("ruler"))
    add_role("event", (sig.get("event") or {}).get("ruler"))
    add_role("moon", "Moon")

    scan_start = dt_utc
    ingress_rows = []
    for body, roles in roles_by_body.items():
        for row in _all_ingresses(body, scan_start, target["end_utc"], timezone_name):
            row["roles"] = roles
            exact = v6._parse_utc(row["utc"])
            row["before_target_start"] = exact < target["start_utc"]
            row["within_target_window"] = target["start_utc"] <= exact <= target["end_utc"]
            ingress_rows.append(row)
    ingress_rows.sort(key=lambda x: x["utc"])

    q = sig.get("querent") or {}
    t = sig.get("quesited") or {}
    e = sig.get("event") or {}
    pairs = []
    pair_specs = [
        ("querent_quesited", ["querent", "quesited"], q, t),
        ("querent_event", ["querent", "event"], q, e),
        ("quesited_event", ["quesited", "event"], t, e),
    ]
    for pair_id, roles, left, right in pair_specs:
        if not left or not right:
            continue
        pairs.append(_pair_development(
            pair_id,
            roles,
            left.get("ruler"), left.get("planet"),
            right.get("ruler"), right.get("planet"),
            dt_utc, target, topic, timezone_name,
        ))

    moon_ingress = next((x for x in ingress_rows if x.get("body") == "Moon"), None)
    moon_flow_start = target["start_utc"]
    if moon_ingress:
        moon_ingress_dt = v6._parse_utc(moon_ingress["utc"])
        moon_flow_start = max(target["start_utc"], moon_ingress_dt)

    moon_events = []
    if moon_ingress and moon_flow_start <= target["end_utc"]:
        for body in core.HORARY_PLANETS:
            if body == "Moon":
                continue
            for event in v6._exact_events_between("Moon", body, moon_flow_start, target["end_utc"]):
                exact = v6._parse_utc(event["exact_utc"])
                target_roles = [r for r in roles_by_body.get(body, []) if r in {"querent", "quesited", "event"}]
                direct = bool(target_roles)
                moon_events.append({
                    "type": "moon_major_aspect",
                    "body": body,
                    "body_ko": core.PLANET_KO.get(body, body),
                    "aspect": event.get("aspect"),
                    "aspect_ko": event.get("aspect_ko"),
                    "phase": "applying_to_exact",
                    "exact_local": _local(exact, timezone_name),
                    "exact_utc": exact.isoformat(),
                    "direct_event_axis": direct,
                    "direct_roles": target_roles,
                    "supportive_only": not direct,
                })
    moon_events.sort(key=lambda x: x["exact_utc"])

    daily = []
    d = target["start_date"]
    zone = _zone(timezone_name)
    while d <= target["end_date"]:
        day_start = datetime.combine(d, time(0, 0), tzinfo=zone).astimezone(ZoneInfo("UTC"))
        day_end = datetime.combine(d, time(23, 59, 59), tzinfo=zone).astimezone(ZoneInfo("UTC"))
        moon_start = _planet_state("Moon", day_start)
        moon_end = _planet_state("Moon", day_end)
        pair_rows = []
        orb_entries = []
        exacts = []
        for pair in pairs:
            samples = [x for x in pair.get("samples", []) if x.get("date") == d.isoformat()]
            pair_rows.append({
                "pair": pair.get("pair"),
                "a": pair.get("a"),
                "b": pair.get("b"),
                "aspect": pair.get("aspect"),
                "samples": samples,
            })
            entry = pair.get("orb_entry")
            exact = pair.get("exact_perfection_reference")
            if entry and entry.get("scope") == "within_target_window" and entry.get("time_local", "").startswith(d.isoformat()):
                orb_entries.append({"pair": pair.get("pair"), **entry})
            if exact and exact.get("scope") == "within_target_window" and exact.get("time_local", "").startswith(d.isoformat()):
                exacts.append({"pair": pair.get("pair"), **exact})
        daily.append({
            "date": d.isoformat(),
            "moon": {
                "start_sign": moon_start["sign_en"],
                "start_sign_ko": moon_start["sign_ko"],
                "end_sign": moon_end["sign_en"],
                "end_sign_ko": moon_end["sign_ko"],
            },
            "moon_major_aspects": [x for x in moon_events if x.get("exact_local", "").startswith(d.isoformat())],
            "significator_aspects": pair_rows,
            "orb_entries": orb_entries,
            "exact_perfections": exacts,
        })
        d += timedelta(days=1)

    moon_course = (data.get("judgment_support") or {}).get("moon_course") or {}
    major_ingress = [x for x in ingress_rows if any(r in {"querent", "quesited", "event"} for r in x.get("roles", []))]
    target_label = target["start_date"].isoformat() if target["start_date"] == target["end_date"] else f"{target['start_date'].isoformat()}~{target['end_date'].isoformat()}"

    events = []
    for x in ingress_rows:
        events.append({"type": "sign_ingress", "time_local": x["time_local"], "body": x["body"], "roles": x.get("roles", [])})
    for x in moon_events:
        events.append({"type": "moon_major_aspect", "time_local": x["exact_local"], "body": x["body"], "aspect": x["aspect"], "direct_event_axis": x["direct_event_axis"], "supportive_only": x["supportive_only"]})
    for x in pairs:
        if x.get("orb_entry"):
            events.append({"type": "orb_entry", "time_local": x["orb_entry"]["time_local"], "pair": x["pair"], "scope": x["orb_entry"]["scope"]})
        if x.get("exact_perfection_reference"):
            events.append({"type": "exact_perfection_reference", "time_local": x["exact_perfection_reference"]["time_local"], "pair": x["pair"], "scope": x["exact_perfection_reference"]["scope"]})
    events.sort(key=lambda x: x.get("time_local") or "")

    return {
        "version": VERSION,
        "active": True,
        "source": target["sourceText"],
        "sourceText": target["sourceText"],
        "target_date": target_label,
        "target_start_local": target["start_local"].isoformat(),
        "target_end_local": target["end_local"].isoformat(),
        "targetWindow": {
            "start": target["start_local"].isoformat(),
            "end": target["end_local"].isoformat(),
            "sourceText": target["sourceText"],
        },
        "currentJudgmentUnchanged": True,
        "currentJudgment": _current_judgment_snapshot(data),
        "currentPerfection": {
            "perfects": bool(((data.get("judgment_support") or {}).get("perfection") or {}).get("perfects")),
            "reason": ((data.get("judgment_support") or {}).get("perfection") or {}).get("reason"),
        },
        "futureAspectDevelopment": pairs,
        "ingresses": ingress_rows,
        "moonFutureFlow": {
            "current_voc": bool(moon_course.get("void_of_course")),
            "current_voc_ends_at_ingress": bool(moon_course.get("void_of_course") and moon_ingress),
            "ingress": moon_ingress,
            "aspects_after_ingress": moon_events,
        },
        "dailySummaries": daily,
        "events": events,
        "moon_ingress_before_target_end": bool(moon_ingress),
        "moon_voc_scope_ends_before_target_end": bool(moon_course.get("void_of_course") and moon_ingress),
        "major_significator_condition_changes": bool(major_ingress),
        "current_reception_not_guaranteed_through_target": bool(major_ingress),
        "does_not_change_perfection": True,
        "interpretation_rules_ko": [
            "currentJudgment와 Future Window는 별도 레이어입니다. Future Window 때문에 현재 grade/Perfection/reception/dignity/VOC 판정을 변경하지 않습니다.",
            "현재 Moon VOC는 현재 sign 이탈 전까지만 유효합니다. 목표기간 시작 전/중 ingress가 있으면 VOC를 목표기간 전체의 정체·불성사 근거로 확장하지 않습니다.",
            "질문 시각에 orb 밖인 aspect가 미래에 접근하거나 orb 안으로 진입해도 이를 현재 Perfection 또는 YES로 승격하지 않습니다.",
            "Reception은 수용성·관계 조건의 기술적 근거이며 시장·상대가 질문자의 통제나 이익 방향으로 움직인다고 과장하지 않습니다.",
            "D/NONE은 확정 근거 부족이지 자동 불성사 판정이 아닙니다.",
            "Dignity/Debility는 행성 상태·행동능력의 보조 근거이며 사건 실패와 1:1로 동일시하지 않습니다.",
            "future aspect는 direct_event_axis와 supportive_only를 구분하며 supportive_only를 사건 성사 근거로 자동 승격하지 않습니다.",
            "범위 질문은 targetWindow.start부터 targetWindow.end까지 모두 분석하고 특정 날짜를 임의로 더 좋다고 순위화하지 않습니다.",
        ],
    }


def _postprocess(data):
    if not isinstance(data, dict) or data.get("schema") != "LUNEA_HORARY_V1":
        return data
    moment = data.get("moment") or {}
    dt_utc = v6._parse_utc(moment.get("utc_iso"))
    timezone_name = str(moment.get("timezone") or "Asia/Seoul")
    data.setdefault("judgment_support", {})["future_window_v1"] = build_future_window(data, dt_utc, timezone_name)
    data.setdefault("meta", {})["future_window"] = VERSION
    return data


def _compute_horary_future_window_v2(*args, **kwargs):
    return _postprocess(_ORIGINAL_COMPUTE_HORARY(*args, **kwargs))


if not getattr(v31.compute_horary, "_lunea_future_window_v2", False):
    _compute_horary_future_window_v2._lunea_future_window_v2 = True
    v31.compute_horary = _compute_horary_future_window_v2
