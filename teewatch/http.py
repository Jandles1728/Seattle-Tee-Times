import time

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)

session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*"})


def polite_pause(seconds: float = 0.4) -> None:
    """Small gap between requests so we look like one person browsing, not a crawler."""
    time.sleep(seconds)
