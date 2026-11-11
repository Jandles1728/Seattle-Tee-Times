"""Chronogolf (Lightspeed Golf) marketplace: the club page carries the course
UUIDs in its __NEXT_DATA__ blob; the v2 teetimes feed takes those UUIDs."""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .http import session, polite_pause
from .models import TeeTime, hhmm_to_minutes

log = logging.getLogger(__name__)
BASE = "https://www.chronogolf.com"
PACIFIC = ZoneInfo("America/Los_Angeles")
_NEXT = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)

_uuid_cache: dict[str, list[dict]] = {}


def course_uuids(slug: str) -> list[dict]:
    if slug not in _uuid_cache:
        html = session.get(f"{BASE}/club/{slug}", timeout=30, headers={"Accept": "text/html"}).text
        m = _NEXT.search(html)
        if not m:
            raise RuntimeError("club page had no __NEXT_DATA__")
        club = json.loads(m.group(1))["props"]["pageProps"]["club"]
        _uuid_cache[slug] = [
            {"uuid": c["uuid"], "name": c.get("name", "")}
            for c in club.get("courses", [])
            if c.get("uuid") and "simulator" not in c.get("name", "").lower()
        ]
    return _uuid_cache[slug]


def club_times(club: dict, day: date, search: dict) -> list[TeeTime]:
    courses = course_uuids(club["slug"])
    if not courses:
        return []
    ids = ",".join(c["uuid"] for c in courses)
    lo, hi = hhmm_to_minutes(search["earliest"]), hhmm_to_minutes(search["latest"])
    out = []
    for page in range(1, 11):
        r = session.get(
            f"{BASE}/marketplace/v2/teetimes",
            params={"start_date": day.isoformat(), "course_ids": ids, "holes": 18, "page": page},
            timeout=30,
        )
        r.raise_for_status()
        batch = r.json().get("teetimes") or []
        if not batch:
            break
        for t in batch:
            if (t.get("max_player_size") or 0) < search["players"] or t.get("frozen"):
                continue
            local = datetime.fromisoformat(t["starts_at"].replace("Z", "+00:00")).astimezone(PACIFIC)
            mins = local.hour * 60 + local.minute
            if not lo <= mins <= hi:
                continue
            p = t.get("default_price") or {}
            course_name = t.get("course", {}).get("name", "")
            name = club["name"] if len(courses) == 1 else f"{club['name']} ({course_name.title()})"
            holes = p.get("bookable_holes")
            note = []
            if holes == 9:
                note.append("9-hole rate shown; 18 costs more")
            if p.get("half_cart"):
                note.append(f"+${p['half_cart']:g} cart")
            out.append(TeeTime(
                course=name, day=day, time=f"{local.hour:02d}:{local.minute:02d}",
                price=p.get("green_fee"), holes=holes, source="chronogolf",
                book_url=f"{BASE}/club/{club['slug']}?date={day.isoformat()}&nb_holes=18",
                note="; ".join(note),
            ))
        polite_pause()
    return out


def fetch(clubs: list[dict], days: list[date], search: dict) -> tuple[list[TeeTime], list[str]]:
    times, errors = [], []
    for club in clubs:
        for day in days:
            try:
                times += club_times(club, day, search)
            except Exception as e:  # noqa: BLE001
                errors.append(f"Chronogolf {club['name']} {day}: {e}")
            polite_pause()
    return times, errors
