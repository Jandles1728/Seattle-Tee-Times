"""Twilio SMS via the REST API (no SDK needed). Reads credentials from env:
TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM, ALERT_TO (comma-separated)."""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)
SMS_LIMIT = 1500  # Twilio allows 1600 chars; leave headroom


def configured() -> bool:
    return all(os.getenv(k) for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM", "ALERT_TO"))


def send_sms(body: str) -> None:
    if not configured():
        log.warning("Twilio not configured; would have sent:\n%s", body)
        return
    sid, token = os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"]
    for to in [x.strip() for x in os.environ["ALERT_TO"].split(",") if x.strip()]:
        r = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            auth=(sid, token),
            data={"From": os.environ["TWILIO_FROM"], "To": to, "Body": body[:SMS_LIMIT]},
            timeout=30,
        )
        if r.status_code >= 300:
            raise RuntimeError(f"Twilio {r.status_code}: {r.text[:300]}")
