"""GolfNow: one geo search per day to find courses with foursome slots in the
window, then one facility search per course for the individual times."""
from __future__ import annotations

import logging
from datetime import date

from .http import session, polite_pause
from .models import TeeTime, hhmm_to_minutes

log = logging.getLogger(__name__)
BASE = "https://www.golfnow.com"


def _half_hour_index(hhmm: str) -> int:
    # GolfNow's TimeMin/TimeMax are half-hour slots: 16 = 8:00 AM, 28 = 2:00 PM
    return hhmm_to_minutes(hhmm) // 30


def _body(day: date, players: int, earliest: str, latest: str, **extra) -> dict:
    body = {
        "Date": day.strftime("%b %d %Y"),
        "Players": players,
        "Holes": 3,  # any; we keep 18-hole rates below
        "TimeMin": _half_hour_index(earliest),
        "TimeMax": _half_hour_index(latest),
        "PriceMin": 0,
        "PriceMax": 10000,
        "PageSize": 100,
        "PageNumber": 0,
        "SortBy": "Date",
        "SortDirection": 0,
        "HotDealsOnly": False,
        "FacilityType": 0,
        "RateType": "all",
        "PromotedCampaignsOnly": False,
        "TeeTimeCount": 100,
    }
    body.update(extra)
    return body


def _to_24h(formatted: str, meridian: str) -> str:
    h, m = map(int, formatted.split(":"))
    if meridian.upper() == "PM" and h != 12:
        h += 12
    if meridian.upper() == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{m:02d}"


def find_courses(cfg: dict, day: date, search: dict) -> list[dict]:
    body = _body(
        day, search["players"], search["earliest"], search["latest"],
        SearchType=0, View="Course", SortByRollup="Date.MinDate",
        Latitude=cfg["lat"], Longitude=cfg["lon"], Radius=cfg["radius_miles"],
        ExcludeFeaturedFacilities=False,
    )
    r = session.post(f"{BASE}/api/tee-times/courses-near-me", json=body, timeout=30)
    r.raise_for_status()
    facilities = r.json()["ttResults"]["facilities"]
    seen, out = set(), []
    for f in facilities:
        if f["id"] in seen or f["name"] in cfg.get("exclude", []):
            continue
        seen.add(f["id"])
        out.append({"id": f["id"], "name": f["name"].rstrip(". "), "slug": f["seoFriendlyName"]})
    return out


def facility_times(fac: dict, day: date, search: dict) -> list[TeeTime]:
    body = _body(
        day, search["players"], search["earliest"], search["latest"],
        SearchType=1, FacilityId=fac["id"], View="Grouping",
        ExcludeFeaturedFacilities=True, Radius=0, Latitude=0, Longitude=0,
    )
    r = session.post(f"{BASE}/api/tee-times/tee-time-search-results", json=body, timeout=30)
    r.raise_for_status()
    out = []
    for t in r.json()["ttResults"].get("teeTimes") or []:
        rates = [q for q in t.get("teeTimeRates", []) if q.get("isEighteen") or q.get("holeCount") == 18]
        if not rates:
            continue
        best = min(rates, key=lambda q: q["singlePlayerPrice"]["feeMessagingDisplayRates"]["totalPrice"]["value"])
        price = best["singlePlayerPrice"]["feeMessagingDisplayRates"]["totalPrice"]["value"]
        hhmm = _to_24h(t["time"]["formatted"], t["time"]["formattedTimeMeridian"])
        out.append(TeeTime(
            course=fac["name"], day=day, time=hhmm, price=round(float(price), 2), holes=18,
            source="golfnow",
            book_url=f"{BASE}/tee-times/facility/{fac['slug']}/search",
            note="cart incl." if best.get("isCartIncluded") else "",
        ))
    return out


def fetch(cfg: dict, days: list[date], search: dict) -> tuple[list[TeeTime], list[str]]:
    times, errors = [], []
    for day in days:
        try:
            courses = find_courses(cfg, day, search)
        except Exception as e:  # noqa: BLE001
            errors.append(f"GolfNow search {day}: {e}")
            continue
        for fac in courses:
            polite_pause()
            try:
                times += facility_times(fac, day, search)
            except Exception as e:  # noqa: BLE001
                errors.append(f"GolfNow {fac['name']} {day}: {e}")
    return times, errors
