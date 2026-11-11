"""Chronogolf (Lightspeed Golf) marketplace.

Uses the club tee time feed the booking widget calls:
  /marketplace/clubs/{club_id}/teetimes?date=…&course_id=…&nb_holes=18&affiliation_type_ids[]=… (one per player)
It returns real 18-hole prices for the group size and flags slots that are full
or restricted. The newer v2 feed answers 403 from cloud servers, so it isn't used.
Club and course ids come from the club page's __NEXT_DATA__ blob."""
from __future__ import annotations

import json
import logging
import re
from datetime import date

from .http import session, polite_pause
from .models import TeeTime, hhmm_to_minutes

log = logging.getLogger(__name__)
BASE = "https://www.chronogolf.com"
_NEXT = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)

_club_cache: dict[str, dict] = {}


def club_info(slug: str) -> dict:
    """{'id': 14713, 'courses': [{'id': 16894, 'name': 'China Creek'}, …], 'affiliation': 59674}"""
    if slug in _club_cache:
        return _club_cache[slug]
    html = session.get(f"{BASE}/club/{slug}", timeout=30, headers={"Accept": "text/html"}).text
    m = _NEXT.search(html)
    if not m:
        raise RuntimeError("club page had no __NEXT_DATA__")
    club = json.loads(m.group(1))["props"]["pageProps"]["club"]
    club_id = club["id"]
    courses = [
        {"id": c["id"], "name": c.get("name", "")}
        for c in club.get("courses", [])
        if c.get("id") and "simulator" not in c.get("name", "").lower()
        and (c.get("holes", 18) >= 18 or 18 in (c.get("bookableHoles") or []))
    ]
    affiliation = club.get("defaultAffiliationTypeId") \
        or (club.get("settings") or {}).get("default_affiliation_type_id")
    if not affiliation:
        # fall back to the organization's affiliation list: pick the public rate
        types = session.get(f"{BASE}/marketplace/organizations/{club_id}/affiliation_types", timeout=30).json()
        public = [t for t in types if t.get("name", "").strip().lower() == "public"] or \
                 [t for t in types if "public" in t.get("name", "").lower()]
        if not public:
            raise RuntimeError("couldn't find the public rate for this club")
        affiliation = public[0]["id"]
    info = {"id": club_id, "courses": courses, "affiliation": int(affiliation)}
    _club_cache[slug] = info
    return info


def club_times(club: dict, day: date, search: dict) -> list[TeeTime]:
    info = club_info(club["slug"])
    players = search["players"]
    lo, hi = hhmm_to_minutes(search["earliest"]), hhmm_to_minutes(search["latest"])
    out = []
    for course in info["courses"]:
        params = [("date", day.isoformat()), ("course_id", course["id"]), ("nb_holes", 18)]
        params += [("affiliation_type_ids[]", info["affiliation"])] * players
        r = session.get(f"{BASE}/marketplace/clubs/{info['id']}/teetimes", params=params, timeout=30,
                        headers={"Referer": f"{BASE}/club/{club['slug']}"})
        r.raise_for_status()
        for t in r.json() or []:
            if t.get("out_of_capacity") or t.get("restrictions") or t.get("frozen"):
                continue
            hhmm = t["start_time"][:5]
            if not lo <= hhmm_to_minutes(hhmm) <= hi:
                continue
            fees = t.get("green_fees") or []
            if len(fees) < players:
                continue
            price = fees[0].get("green_fee")
            cart = fees[0].get("half_cart")
            name = club["name"] if len(info["courses"]) == 1 else f"{club['name']} ({course['name'].title()})"
            out.append(TeeTime(
                course=name, day=day, time=hhmm, price=price, holes=18, source="chronogolf",
                book_url=f"{BASE}/club/{club['slug']}?date={day.isoformat()}&nb_holes=18",
                note=f"+${cart:g} cart" if cart else "",
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
                errors.append(f"Chronogolf {club['name']}: {str(e).split(' for url')[0]}")
                break  # same failure would repeat for every date
            polite_pause()
    return times, errors
