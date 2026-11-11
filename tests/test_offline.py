"""Offline test: replays response shapes recorded from the live sites (Nov 2026)
so the parsing, filtering, de-dupe and alert logic can be checked without network."""
import json
import shutil
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import pytest

from teewatch import main, http

PT = ZoneInfo("America/Los_Angeles")


def money(v):
    return {"value": v}


GOLFNOW_NEAR = {"ttResults": {"facilities": [
    {"id": 1252, "name": "Druids Glen Golf Club", "seoFriendlyName": "1252-druids-glen-golf-club"},
]}}


def golfnow_times(times):
    return {"ttResults": {"teeTimes": [
        {"time": {"formatted": f, "formattedTimeMeridian": m},
         "teeTimeRates": [{"holeCount": 18, "isEighteen": True, "isCartIncluded": False,
                           "singlePlayerPrice": {"feeMessagingDisplayRates": {"totalPrice": money(p)}}},
                          {"holeCount": 9, "isEighteen": False, "isCartIncluded": False,
                           "singlePlayerPrice": {"feeMessagingDisplayRates": {"totalPrice": money(20)}}}]}
        for f, m, p in times]}}


CHRONO_HTML = ('<html><script id="__NEXT_DATA__" type="application/json">'
               + json.dumps({"props": {"pageProps": {"club": {"courses": [
                   {"uuid": "u1", "name": "China Creek"}, {"uuid": "u2", "name": "Coal Creek"},
                   {"uuid": "u3", "name": "SIMULATOR"}]}}}})
               + "</script></html>")


def chrono_tt(start_utc, course, maxp=4, fee=123.0, holes=18):
    return {"starts_at": start_utc, "max_player_size": maxp, "frozen": False,
            "course": {"name": course},
            "default_price": {"green_fee": fee, "half_cart": 20.0, "bookable_holes": holes}}


FOREUP = [
    {"time": "2026-11-14 07:30", "available_spots": 4, "green_fee_18": 60, "cart_fee_18": 0},
    {"time": "2026-11-14 13:18", "available_spots": 4, "green_fee_18": 46, "cart_fee_18": 0},
    {"time": "2026-11-14 13:36", "available_spots": 2, "green_fee_18": 39, "cart_fee_18": 0},
]

NWS_POINT = {"properties": {"forecastHourly": "https://api.weather.gov/hourly"}}
NWS_HOURLY = {"properties": {"periods": [
    {"startTime": f"2026-11-14T{h:02d}:00:00-08:00", "temperature": 40 + h, "windSpeed": "5 to 10 mph",
     "probabilityOfPrecipitation": {"value": 20 if h < 12 else 60}, "shortForecast": "Light Rain"}
    for h in range(6, 18)]}}


class Resp:
    def __init__(self, data=None, text=None, status=200):
        self._d, self.text, self.status_code = data, text if text is not None else json.dumps(data), status

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def fake_get(url, params=None, **kw):
    if "v2/session" in url:
        return Resp(None, text="", status=204)
    if "chronogolf.com/club/" in url:
        return Resp(text=CHRONO_HTML)
    if "v2/teetimes" in url:
        if params["page"] > 1 or params["start_date"] != "2026-11-14":
            return Resp({"teetimes": []})
        return Resp({"teetimes": [
            chrono_tt("2026-11-14T15:36:00Z", "China Creek"),             # 7:36 -> outside window
            chrono_tt("2026-11-14T16:00:00Z", "Coal Creek", fee=168),     # 8:00 keep
            chrono_tt("2026-11-14T16:03:00Z", "China Creek", maxp=1),     # singles only -> drop
            chrono_tt("2026-11-14T20:15:00Z", "China Creek", fee=86),     # 12:15 keep
        ]})
    if "foreupsoftware" in url:
        return Resp(FOREUP if params["date"] == "11-14-2026" else [])
    if url.endswith("/points/47.6062,-122.3321"):
        return Resp(NWS_POINT)
    if url == "https://api.weather.gov/hourly":
        return Resp(NWS_HOURLY)
    raise AssertionError(url)


def fake_post(url, json=None, **kw):
    if "courses-near-me" in url:
        return Resp(GOLFNOW_NEAR if json["Date"] == "Nov 14 2026" else {"ttResults": {"facilities": []}})
    if "tee-time-search-results" in url:
        assert json["TimeMin"] == 16 and json["TimeMax"] == 28 and json["Players"] == 4
        return Resp(golfnow_times([("8:10", "AM", 86.99), ("12:00", "PM", 60.99)]))
    raise AssertionError(url)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parent.parent
    shutil.copy(root / "config.yaml", tmp_path / "config.yaml")
    cfg = (tmp_path / "config.yaml").read_text()
    # trim the chronogolf list to one club for the test
    head, rest = cfg.split("chronogolf:\n", 1)
    _, foreup_part = rest.split("foreup:\n", 1)
    (tmp_path / "config.yaml").write_text(
        head + "chronogolf:\n  - {name: \"Golf Club at Newcastle\", slug: golf-club-at-newcastle}\n\nforeup:\n" + foreup_part)
    monkeypatch.setattr(main, "ROOT", tmp_path)
    monkeypatch.setattr(http.session, "get", fake_get)
    monkeypatch.setattr(http.session, "post", fake_post)
    monkeypatch.setattr(http, "polite_pause", lambda *a, **k: None)
    for m in ("golfnow", "chronogolf", "foreup"):
        monkeypatch.setattr(f"teewatch.{m}.polite_pause", lambda *a, **k: None)
    return tmp_path


def test_full_cycle(repo, capsys):
    wed = datetime(2026, 11, 11, 13, 7, tzinfo=PT)
    sent = []
    with mock.patch("teewatch.notify.send_sms", side_effect=sent.append):
        # first run: baseline only, no text
        assert main.run(now=wed) == 0
        assert sent == []
        latest = json.loads((repo / "latest.json").read_text())
        got = sorted((t["course"], t["time"], t["price"]) for t in latest["times"])
        assert got == sorted([
            ("Druids Glen Golf Club", "08:10", 86.99),
            ("Druids Glen Golf Club", "12:00", 60.99),
            ("Golf Club at Newcastle (Coal Creek)", "08:00", 168.0),
            ("Golf Club at Newcastle (China Creek)", "12:15", 86.0),
            ("The Home Course", "13:18", 46),
        ]), got
        report = (repo / "REPORT.md").read_text()
        assert "Saturday, November 14" in report and "Light Rain" in report
        assert "Sunday, November 22" in report  # two weekends

        # second run: nothing new -> no text
        assert main.run(now=wed.replace(minute=37)) == 0
        assert sent == []

        # a cancellation opens a new slot -> exactly one text naming it
        FOREUP.append({"time": "2026-11-14 10:00", "available_spots": 4, "green_fee_18": 79, "cart_fee_18": 0})
        assert main.run(now=wed.replace(hour=14, minute=7)) == 0
        assert len(sent) == 1
        assert "The Home Course: 10:00a $79" in sent[0] and "Druids" not in sent[0]
        assert "Sat Nov 14" in sent[0] and "rain" in sent[0]

        # quiet hours: new slot held, then sent at 6 AM
        FOREUP.append({"time": "2026-11-14 11:00", "available_spots": 4, "green_fee_18": 79, "cart_fee_18": 0})
        main.run(now=datetime(2026, 11, 12, 23, 7, tzinfo=PT))
        assert len(sent) == 1
        main.run(now=datetime(2026, 11, 13, 6, 7, tzinfo=PT))
        assert len(sent) == 2 and "11:00a" in sent[1]


def test_target_days_sunday_afternoon():
    sun_late = datetime(2026, 11, 15, 15, 0, tzinfo=PT)
    days = main.target_days(sun_late, ["Sat", "Sun"], 2, "14:00")
    assert [d.isoformat() for d in days] == ["2026-11-21", "2026-11-22", "2026-11-28", "2026-11-29"]
