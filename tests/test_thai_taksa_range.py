from __future__ import annotations

from datetime import datetime
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

import astro_api


POSITIONS = [
    ("Sri", "ศรี", "스리", "길조·매력·호의"),
    ("Montri", "มนตรี", "몬트리", "지원·조력"),
    ("Dech", "เดช", "데트", "권위·추진력"),
    ("Boriwan", "บริวาร", "보리완", "주변 사람·환경"),
    ("Ayu", "อายุ", "아유", "지속·생명력"),
    ("Mula", "มูละ", "물라", "기반·자원"),
    ("Utsaha", "อุตสาหะ", "웃사하", "노력·행동"),
]


def fake_taksa(*, natal, topic, current_iso, timezone_name):
    dt = datetime.fromisoformat(current_iso)
    # The production calculator has a special Wednesday-night Rahu split.
    if dt.weekday() == 2 and dt.hour >= 18:
        ruler = {"key": "Rahu", "ko": "라후", "planet_number": 8}
        position, thai, ko, meaning = ("Kalakini", "กาลกิณี", "칼라키니", "장애·주의")
    else:
        position, thai, ko, meaning = POSITIONS[dt.weekday() % len(POSITIONS)]
        ruler = {"key": f"P{dt.weekday()+1}", "ko": f"요일행성{dt.weekday()+1}", "planet_number": dt.weekday()+1}

    return {
        "current_day": {
            "weekday_label": dt.strftime("%A"),
            "ruler": ruler,
            "falls_in_natal_taksa": {
                "position": position,
                "position_thai": thai,
                "position_ko": ko,
                "meaning_ko": meaning,
            },
        },
        "question": {
            "focus_positions": ["Sri", "Montri"],
            "focus_rows": [],
        },
    }


class ThaiTaksaRangeTests(unittest.TestCase):
    def test_health_exposes_range_capability(self):
        data = astro_api.health()
        self.assertEqual(data["version"], "1.8.0")
        self.assertTrue(data["thai_taksa"])
        self.assertTrue(data["thai_taksa_range"])
        self.assertEqual(data["thai_taksa_range_max_days"], 90)

    @patch("astro_api.calculate_thai_taksa", side_effect=fake_taksa)
    def test_range_builds_calendar_and_wednesday_night_variant(self, mocked):
        req = astro_api.ThaiTaksaRangeRequest(
            natal={"birth": {"date": "1991-03-21"}},
            topic="연락",
            start_iso="2026-09-07",
            days=7,
            timezone="Asia/Seoul",
        )
        data = astro_api.thai_taksa_range(req)

        self.assertEqual(data["schema"], "LUNEA_THAI_TAKSA_RANGE_V1")
        self.assertEqual(data["start_date"], "2026-09-07")
        self.assertEqual(len(data["calendar"]), 7)
        self.assertEqual(mocked.call_count, 14, "each Taksa day should sample noon and evening")

        wed = next(row for row in data["calendar"] if row["date"] == "2026-09-09")
        self.assertIsNotNone(wed["night_variant"])
        self.assertEqual(wed["night_variant"]["ruler"]["key"], "Rahu")
        self.assertEqual(wed["night_variant"]["position"], "Kalakini")
        self.assertEqual(wed["night_variant"]["tone"]["key"], "caution")

        monday = data["calendar"][0]
        self.assertIsNone(monday["night_variant"])
        self.assertEqual(monday["daytime"]["tone"]["key"], "supportive")
        self.assertTrue(monday["daytime"]["focus_match"])

        self.assertGreaterEqual(data["summary"]["supportive_segments"], 1)
        self.assertGreaterEqual(data["summary"]["caution_segments"], 1)
        self.assertEqual(data["meta"]["day_boundary"], "06:00 local time")

    def test_days_are_bounded(self):
        with self.assertRaises(ValidationError):
            astro_api.ThaiTaksaRangeRequest(natal={}, days=91)

    def test_invalid_start_is_422(self):
        req = astro_api.ThaiTaksaRangeRequest(natal={}, start_iso="not-a-date", days=7)
        with self.assertRaises(HTTPException) as ctx:
            astro_api.thai_taksa_range(req)
        self.assertEqual(ctx.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
