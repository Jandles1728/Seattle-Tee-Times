"""National Weather Service hourly forecast, summarized for the tee time window."""
from __future__ import annotations

from datetime import date, datetime

from .http import session
from .models import hhmm_to_minutes

NWS_HEADERS = {
    # NWS asks for an identifying User-Agent with contact info
    "User-Agent": "seattle-tee-times (github actions weekend golf watcher)",
    "Accept": "application/geo+json",
}


def outlook(lat: float, lon: float, days: list[date], earliest: str, latest: str) -> dict[date, dict]:
    pt = session.get(f"https://api.weather.gov/points/{lat},{lon}", headers=NWS_HEADERS, timeout=30)
    pt.raise_for_status()
    hourly_url = pt.json()["properties"]["forecastHourly"]
    r = session.get(hourly_url, headers=NWS_HEADERS, timeout=30)
    r.raise_for_status()
    lo, hi = hhmm_to_minutes(earliest), hhmm_to_minutes(latest)
    buckets: dict[date, list[dict]] = {d: [] for d in days}
    for p in r.json()["properties"]["periods"]:
        start = datetime.fromisoformat(p["startTime"])  # already Pacific offset
        if start.date() in buckets and lo <= start.hour * 60 + start.minute <= hi:
            buckets[start.date()].append(p)
    out = {}
    for d, periods in buckets.items():
        if not periods:
            out[d] = {"summary": "forecast not out yet"}
            continue
        temps = [p["temperature"] for p in periods]
        rain = [(p.get("probabilityOfPrecipitation") or {}).get("value") or 0 for p in periods]
        winds = []
        for p in periods:
            digits = [int(x) for x in p.get("windSpeed", "0").replace("mph", "").split() if x.isdigit()]
            winds.append(max(digits) if digits else 0)
        common = max(set(p["shortForecast"] for p in periods), key=[p["shortForecast"] for p in periods].count)
        out[d] = {
            "low": min(temps), "high": max(temps), "rain_pct": max(rain), "wind_mph": max(winds),
            "sky": common,
            "summary": f"{min(temps)}–{max(temps)}°F, {max(rain)}% rain, wind to {max(winds)} mph, {common}",
        }
    return out
