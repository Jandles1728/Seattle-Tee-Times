from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date


@dataclass(frozen=True)
class TeeTime:
    course: str          # display name, e.g. "Golf Club at Newcastle (Coal Creek)"
    day: date
    time: str            # "HH:MM" 24h, Pacific
    price: float | None  # per player, USD, as shown by the source
    holes: int | None    # holes the price applies to (Chronogolf sometimes only quotes 9)
    source: str          # golfnow | chronogolf | foreup
    book_url: str
    note: str = ""

    @property
    def key(self) -> str:
        """Identity used to tell 'new' from 'already alerted'. Price is left out on
        purpose so a price wobble on the same slot doesn't re-alert."""
        return f"{self.source}|{self.course}|{self.day.isoformat()}|{self.time}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["day"] = self.day.isoformat()
        return d


def hhmm_to_minutes(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def pretty_time(hhmm: str) -> str:
    h, m = map(int, hhmm.split(":"))
    suffix = "a" if h < 12 else "p"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d}{suffix}"
