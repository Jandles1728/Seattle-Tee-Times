"""ForeUP public booking feed (used by The Home Course)."""
from __future__ import annotations

from datetime import date

from .http import session, polite_pause
from .models import TeeTime, hhmm_to_minutes

BASE = "https://foreupsoftware.com/index.php/api/booking/times"


def course_times(c: dict, day: date, search: dict) -> list[TeeTime]:
    r = session.get(
        BASE,
        params={
            "time": "all", "date": day.strftime("%m-%d-%Y"), "holes": 18,
            "players": search["players"], "booking_class": c["booking_class"],
            "schedule_id": c["schedule_id"], "schedule_ids[]": c["schedule_id"],
            "specials_only": 0, "api_key": "no_limits",
        },
        headers={"X-Requested-With": "XMLHttpRequest", "Referer": c["book_url"]},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        return []
    lo, hi = hhmm_to_minutes(search["earliest"]), hhmm_to_minutes(search["latest"])
    out = []
    for t in data:
        hhmm = t["time"][11:16]  # "2026-11-14 13:18"
        if not lo <= hhmm_to_minutes(hhmm) <= hi:
            continue
        if (t.get("available_spots") or 0) < search["players"]:
            continue
        out.append(TeeTime(
            course=c["name"], day=day, time=hhmm,
            price=t.get("green_fee_18") or t.get("green_fee"), holes=18,
            source="foreup", book_url=c["book_url"],
            note="walking rate" if not t.get("cart_fee_18") else f"+${t['cart_fee_18']:g} cart",
        ))
    return out


def fetch(courses: list[dict], days: list[date], search: dict) -> tuple[list[TeeTime], list[str]]:
    times, errors = [], []
    for c in courses:
        for day in days:
            try:
                times += course_times(c, day, search)
            except Exception as e:  # noqa: BLE001
                errors.append(f"ForeUP {c['name']} {day}: {e}")
            polite_pause()
    return times, errors
