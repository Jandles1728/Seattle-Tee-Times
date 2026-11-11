# Seattle Tee Times

Checks Seattle-area tee sheets every 30 minutes for **foursome times on Saturdays and Sundays between 8 AM and 2 PM**, pairs them with the National Weather Service forecast for that window, and **texts you only when a new time opens up** (new release or a cancellation).

- **[REPORT.md](REPORT.md)**: the full current board for this weekend and next, refreshed every run.
- **latest.json**: the same data in machine-readable form.
- **state.json**: which times have already been texted, so you aren't alerted twice.

## Sources

| Source | Courses |
|---|---|
| GolfNow | Anything within 50 miles of Seattle with foursome inventory (Druids Glen, White Horse, Salish Cliffs, Tolt, Allenmore, Cedarcrest, Riverbend, Foster, Auburn, etc.) |
| Chronogolf (direct) | Newcastle (Coal + China Creek), Gold Mountain, Trophy Lake, Washington National, Redmond Ridge, Harbour Pointe, Meadow Park, Cedar Irons, Enumclaw, Echo Falls, McCormick Woods, Tolt, Snohomish |
| ForeUP (direct) | The Home Course |
| api.weather.gov | Hourly forecast, 8 AM–2 PM, each weekend day (about 7 days out) |

**Not covered:** the Seattle munis (Jefferson, Jackson, West Seattle, Interbay) need an account sign-in. Chambers Bay's booking site blocks automated access.

## Setup

1. **Add Twilio secrets:** go to *Settings → Secrets and variables → Actions → New repository secret* and add:
   - `TWILIO_ACCOUNT_SID`
   - `TWILIO_AUTH_TOKEN`
   - `TWILIO_FROM`: your Twilio number, e.g. `+12065550123`
   - `ALERT_TO`: the phone(s) to text, comma-separated, e.g. `+12065551234,+12065555678`
2. **Run it once by hand:** *Actions → Scan weekend tee times → Run workflow*. The first run only records what's already open and sends no text. After that, you'll get a text whenever something new appears.
3. Check **REPORT.md** to see the current board.

Without the secrets it still runs and updates REPORT.md; it just doesn't text.

## Tuning (edit `config.yaml`)

- `search.earliest` / `latest`: the tee time window.
- `search.max_price`: ignore anything above this per-player price.
- `search.weekends_ahead`: 1 = this weekend only, 2 = this and next.
- `alerts.courses`: only text about these courses, e.g. `["Newcastle", "Home Course", "Gold Mountain"]`. Everything still appears in the report.
- `alerts.quiet_hours`: no texts overnight; held times go out at the first run after quiet hours end.
- Add a Chronogolf course: find its `chronogolf.com/club/<slug>` URL and add `{name, slug}`.

## Notes

- **Prices** are per player as each site shows them. GolfNow prices include its booking fee. Some Chronogolf courses only publish a 9-hole rate in their feed; those are marked "9h" and the 18-hole price will be higher.
- **Timing:** GitHub can delay scheduled runs by a few minutes at busy times. GitHub also pauses schedules after 60 days without repo activity; this job's own commits count as activity.
- **Failed sources:** if a source starts failing (site change or blocking), the failure is listed at the bottom of REPORT.md. If *every* source fails, the run is marked red in Actions.
- **Manual check:** `pip install -r requirements.txt && python -m teewatch.main --dry-run` prints the text instead of sending it.
