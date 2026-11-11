"""One scan: fetch weekend tee times + weather, write REPORT.md and latest.json,
text any foursome slots not seen before, and remember what was sent in state.json."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import chronogolf, foreup, golfnow, notify, weather
from .models import TeeTime, hhmm_to_minutes, pretty_time

PACIFIC = ZoneInfo("America/Los_Angeles")
ROOT = Path(__file__).resolve().parent.parent
DAY_NUM = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
log = logging.getLogger("teewatch")


def target_days(now: datetime, names: list[str], weekends: int, latest: str = "14:00") -> list[date]:
    wanted = {DAY_NUM[n] for n in names}
    today = now.date()
    out = []
    for i in range(0, 7 * weekends + 1):
        d = today + timedelta(days=i)
        if d.weekday() in wanted and len(out) < len(wanted) * weekends:
            # skip today once its window has passed
            if d == today and now.hour * 60 + now.minute > hhmm_to_minutes(latest):
                continue
            out.append(d)
    return out


def in_quiet_hours(now: datetime, quiet: list[str] | None) -> bool:
    if not quiet:
        return False
    start, end = (hhmm_to_minutes(x) for x in quiet)
    m = now.hour * 60 + now.minute
    return (m >= start or m < end) if start > end else start <= m < end


def load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"alerted": {}}


def prune_state(state: dict, today: date) -> None:
    state["alerted"] = {k: v for k, v in state["alerted"].items() if k.split("|")[2] >= today.isoformat()}


def format_alert(new: list[TeeTime], wx: dict, max_lines: int) -> str:
    by_day: dict[date, list[TeeTime]] = defaultdict(list)
    for t in new:
        by_day[t.day].append(t)
    lines = [f"⛳ {len(new)} new foursome time{'s' if len(new) != 1 else ''}"]
    shown = 0
    for d in sorted(by_day):
        w = wx.get(d, {})
        lines.append(f"\n{d.strftime('%a %b %-d')}" + (f" — {w['summary']}" if w.get("summary") else ""))
        # one line per course: earliest few times + cheapest price
        by_course: dict[str, list[TeeTime]] = defaultdict(list)
        for t in by_day[d]:
            by_course[t.course].append(t)
        for course, ts in sorted(by_course.items(), key=lambda kv: min(x.time for x in kv[1])):
            if shown >= max_lines:
                break
            ts.sort(key=lambda x: x.time)
            times = " ".join(pretty_time(x.time) for x in ts[:4]) + (f" +{len(ts) - 4}" if len(ts) > 4 else "")
            prices = [x.price for x in ts if x.price]
            p = f" ${min(prices):.0f}" if prices else ""
            if any(x.holes == 9 for x in ts):
                p += "(9h)"
            lines.append(f"• {course}: {times}{p}")
            shown += 1
    if shown < len({(t.day, t.course) for t in new}):
        lines.append("…more in REPORT.md")
    return "\n".join(lines)


def write_report(path: Path, times: list[TeeTime], wx: dict, days: list[date], errors: list[str],
                 now: datetime, search: dict) -> None:
    out = [
        f"# Weekend tee times — foursome, {pretty_time(search['earliest'])}–{pretty_time(search['latest'])}",
        f"_Updated {now.strftime('%a %b %-d, %-I:%M %p')} Pacific. Prices are per player as each site shows them._\n",
    ]
    for d in days:
        w = wx.get(d, {})
        day_times = [t for t in times if t.day == d]
        out.append(f"## {d.strftime('%A, %B %-d')}")
        out.append(f"**Weather (8a–2p):** {w.get('summary', 'unavailable')}\n")
        if not day_times:
            out.append("_No open foursome times found._\n")
            continue
        out.append("| Course | Open times | From | Book |")
        out.append("|---|---|---|---|")
        by_course: dict[str, list[TeeTime]] = defaultdict(list)
        for t in day_times:
            by_course[t.course].append(t)
        rows = []
        for course, ts in by_course.items():
            ts.sort(key=lambda x: x.time)
            prices = [x.price for x in ts if x.price]
            low = min(prices) if prices else None
            flag = " (9-hole rate)" if any(x.holes == 9 for x in ts) else ""
            times_s = ", ".join(pretty_time(x.time) for x in ts[:8]) + (f" … +{len(ts) - 8}" if len(ts) > 8 else "")
            rows.append((low if low is not None else 9e9, course,
                         f"| {course} | {times_s} | {f'${low:.0f}' if low else '—'}{flag} | [{ts[0].source}]({ts[0].book_url}) |"))
        out += [r[2] for r in sorted(rows)]
        out.append("")
    if errors:
        out.append("<details><summary>Sources that failed this run</summary>\n")
        out += [f"- {e}" for e in errors]
        out.append("\n</details>")
    path.write_text("\n".join(out) + "\n")


def run(dry_run: bool = False, now: datetime | None = None) -> int:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    search = cfg["search"]
    now = now or datetime.now(PACIFIC)
    days = target_days(now, search["days"], search.get("weekends_ahead", 1), search["latest"])
    log.info("Checking %s", ", ".join(d.isoformat() for d in days))

    times: list[TeeTime] = []
    errors: list[str] = []
    if cfg.get("golfnow", {}).get("enabled"):
        t, e = golfnow.fetch(cfg["golfnow"], days, search); times += t; errors += e
    t, e = chronogolf.fetch(cfg.get("chronogolf") or [], days, search); times += t; errors += e
    t, e = foreup.fetch(cfg.get("foreup") or [], days, search); times += t; errors += e

    # same course on two sources (e.g. Tolt): keep one slot per course/day/time, cheapest price
    best: dict[tuple, TeeTime] = {}
    for t in times:
        k = (t.course.lower().split(" golf")[0].strip(), t.day, t.time)
        if k not in best or (t.price or 9e9) < (best[k].price or 9e9):
            best[k] = t
    times = sorted(best.values(), key=lambda x: (x.day, x.time, x.course))

    if search.get("max_price"):
        times = [t for t in times if t.price is None or t.price <= search["max_price"]]

    try:
        wx = weather.outlook(cfg["weather"]["lat"], cfg["weather"]["lon"], days, search["earliest"], search["latest"])
    except Exception as e:  # noqa: BLE001
        errors.append(f"Weather: {e}")
        wx = {}

    write_report(ROOT / "REPORT.md", times, wx, days, errors, now, search)
    (ROOT / "latest.json").write_text(json.dumps(
        {"updated": now.isoformat(), "errors": errors, "times": [t.to_dict() for t in times]}, indent=1))

    state_path = ROOT / "state.json"
    state = load_state(state_path)
    prune_state(state, now.date())
    watch = {c.lower() for c in cfg.get("alerts", {}).get("courses") or []}
    candidates = [t for t in times if not watch or any(w in t.course.lower() for w in watch)]
    new = [t for t in candidates if t.key not in state["alerted"]]
    first_run = not state_path.exists()

    log.info("%d times found, %d new, %d source errors", len(times), len(new), len(errors))
    if new and first_run:
        # don't blast every existing slot on day one; just baseline it
        log.info("First run: recording %d existing times without texting", len(new))
        for t in new:
            state["alerted"][t.key] = now.isoformat()
    elif new and in_quiet_hours(now, cfg.get("alerts", {}).get("quiet_hours")):
        log.info("Quiet hours: holding %d new times for the next run", len(new))
    elif new:
        msg = format_alert(new, wx, cfg.get("alerts", {}).get("max_lines_per_text", 12))
        if dry_run:
            print(msg)
        else:
            notify.send_sms(msg)
        for t in new:
            state["alerted"][t.key] = now.isoformat()

    if not dry_run or first_run:
        state_path.write_text(json.dumps(state, indent=1, sort_keys=True))
    # every source failing usually means we're being blocked; surface it as a failed run
    return 1 if errors and not times else 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Weekend tee time + weather watcher")
    ap.add_argument("--dry-run", action="store_true", help="print the text instead of sending it")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
