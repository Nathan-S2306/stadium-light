#!/usr/bin/env python3
"""
Bin Light - Kirklees (Huddersfield) bin collection collector.

Looks up the next grey / green / brown bin dates for one property on the
Kirklees "Manage your bins" service and writes docs/bins.json, which
bin_bulb.py reads.

Dates are remembered for a few days after they pass, so the light still shows
on collection morning even if the council site has already moved on to the
next date. If the lookup ever fails, bin_bulb.py carries on by assuming each
bin keeps its fortnightly cycle.

Settings (GitHub: Settings -> Secrets and variables -> Actions -> Variables):
  BIN_UPRN   required: the property's UPRN (Unique Property Reference Number)
"""

import datetime as dt
import http.cookiejar
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

UK = ZoneInfo("Europe/London")
ROOT = Path(__file__).resolve().parent
OUT_FILE = ROOT / "docs" / "bins.json"
KEEP_PAST_DAYS = 3

BASE = "https://my.kirklees.gov.uk"
SESSION_URL = (BASE + "/authapi/isauthenticated?uri=https%253A%252F%252Fmy.kirklees.gov.uk"
               "%252Fservice%252FBins_and_recycling___Manage_your_bins"
               "&hostname=my.kirklees.gov.uk&withCredentials=true")
LOOKUP_URL = BASE + "/apibroker/runLookup"
LOOKUP_ID = "65e08e60b299d"   # the council's "find bins for this UPRN" lookup


def colour_of(label):
    """Map the council's label (e.g. 'Grey 240L bin') to grey / green / brown."""
    s = label.lower()
    for colour in ("grey", "green", "brown"):
        if colour in s:
            return colour
    if "gray" in s or "domestic" in s or "general" in s or "residual" in s:
        return "grey"
    if "recycl" in s:
        return "green"
    if "garden" in s:
        return "brown"
    return None


def fetch(uprn):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    ua = {"User-Agent": "Mozilla/5.0 (bin-light)"}

    with opener.open(urllib.request.Request(SESSION_URL, headers=ua), timeout=30) as r:
        sid = json.load(r)["auth-session"]

    params = urllib.parse.urlencode({
        "id": LOOKUP_ID, "repeat_against": "", "noRetry": "false",
        "getOnlyTokens": "undefined", "log_id": "", "app_name": "AF-Renderer::Self",
        "_": str(int(time.time() * 1000)), "sid": sid,
    })
    body = {"formValues": {"Search": {"validatedUPRN": {"value": str(uprn)}}}}
    req = urllib.request.Request(
        f"{LOOKUP_URL}?{params}", method="POST", data=json.dumps(body).encode(),
        headers={**ua, "Content-Type": "application/json", "Accept": "application/json",
                 "X-Requested-With": "XMLHttpRequest",
                 "Referer": BASE + "/fillform/?iframe_id=fillform-frame-1&db_id="},
    )
    with opener.open(req, timeout=30) as r:
        reply = json.load(r)

    rows = reply.get("integration", {}).get("transformed", {}).get("rows_data")
    if not isinstance(rows, dict) or not rows:
        raise RuntimeError(f"Kirklees returned no bins for UPRN {uprn}: {str(reply)[:300]}")

    found = {}
    for row in rows.values():
        label = row.get("label", "")
        when = (row.get("NextCollectionDate") or "")[:10]
        colour = colour_of(label)
        print(f"  council says: {label!r} next {when or '?'}  -> {colour or 'ignored'}")
        if colour and when:
            found.setdefault(colour, set()).add(dt.date.fromisoformat(when))
    if not found:
        raise RuntimeError("Couldn't recognise any bins in the council's reply (see above).")
    return found


def main():
    uprn = os.environ.get("BIN_UPRN", "").strip()
    if not uprn:
        print("No BIN_UPRN set yet - skipping. See README (Bin light).")
        return

    old = json.loads(OUT_FILE.read_text()) if OUT_FILE.exists() else {}
    today = dt.datetime.now(UK).date()

    found = fetch(uprn)

    # merge with remembered dates, dropping anything more than a few days old
    bins = {}
    for colour in ("grey", "green", "brown"):
        dates = {dt.date.fromisoformat(d) for d in old.get("bins", {}).get(colour, [])}
        dates |= found.get(colour, set())
        dates = sorted(d for d in dates if d >= today - dt.timedelta(days=KEEP_PAST_DAYS))
        if dates:
            bins[colour] = [d.isoformat() for d in dates]

    now = dt.datetime.now(dt.timezone.utc)
    OUT_FILE.parent.mkdir(exist_ok=True)
    OUT_FILE.write_text(json.dumps({
        "generated": now.isoformat(timespec="seconds"),
        "generated_ts": int(now.timestamp()),
        "bins": bins,
    }, indent=1) + "\n")
    for colour, dates in bins.items():
        print(f"{colour:>5}: {', '.join(dates)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:   # keep the old file; bin_bulb.py extrapolates from it
        print(f"Bin lookup failed: {e}")
        sys.exit(1)
