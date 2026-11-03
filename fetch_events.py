#!/usr/bin/env python3
"""
Stadium Light - event collector.

Builds two files in docs/ (served free by GitHub Pages):
  events.json  -> read by the ESP32 light
  events.ics   -> optional calendar feed you can subscribe to on a phone

Sources:
  - Ticketmaster Discovery API: concerts/shows at Co-op Live and the Etihad Stadium
  - football-data.org: Man City home matches (Premier League + Champions League on the free tier)
  - extra_events.json: anything you want to add by hand (cup games, etc.)
"""

import datetime as dt
import hashlib
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
OUT_DIR = ROOT / "docs"
EXTRA_FILE = ROOT / "extra_events.json"

LATLONG = "53.4831,-2.2004"      # between the Etihad and Co-op Live
RADIUS_KM = 1
DAYS_AHEAD = 120
MAX_EVENTS_FOR_LIGHT = 60

VENUE_KEYWORDS = {"co-op live": "Co-op Live", "etihad": "Etihad Stadium"}
SKIP_KEYWORDS = (
    "parking", "car park", "hospitality", "vip", "package", "upgrade",
    "stadium tour", "lounge", "add-on", "merch", "gift card", "voucher",
)
MAN_CITY_ID = 65
DEFAULT_HOURS = {"concert": 3.5, "sport": 2.5, "football": 2.0, "other": 3.0}
DEFAULT_START_LOCAL = dt.time(19, 30)


# ---------- helpers ----------

def http_json(url, headers=None):
    req = urllib.request.Request(
        url, headers={"User-Agent": "stadium-light/1.0", **(headers or {})}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def make_event(name, venue, kind, start, hours, source, tbc=False):
    start = start.astimezone(dt.timezone.utc)
    return {
        "name": name,
        "venue": venue,
        "type": kind,
        "start": start,
        "end": start + dt.timedelta(hours=hours),
        "source": source,
        "tbc": tbc,
    }


def venue_label(name):
    low = (name or "").lower()
    for key, label in VENUE_KEYWORDS.items():
        if key in low:
            return label
    return None


# ---------- sources ----------

def parse_tm_event(ev):
    name = (ev.get("name") or "").strip()
    if not name or any(w in name.lower() for w in SKIP_KEYWORDS):
        return None
    venues = (ev.get("_embedded") or {}).get("venues") or []
    venue = venue_label(venues[0].get("name") if venues else "")
    if not venue:
        return None
    dates = ev.get("dates") or {}
    if (dates.get("status") or {}).get("code") in ("cancelled", "postponed"):
        return None

    s = dates.get("start") or {}
    tbc = bool(s.get("timeTBA") or s.get("noSpecificTime"))
    if s.get("dateTime") and not tbc:
        start = dt.datetime.fromisoformat(s["dateTime"].replace("Z", "+00:00"))
    elif s.get("localDate"):
        d = dt.date.fromisoformat(s["localDate"])
        t = dt.time.fromisoformat(s["localTime"]) if s.get("localTime") and not tbc else DEFAULT_START_LOCAL
        start = dt.datetime.combine(d, t, tzinfo=UK)
    else:
        return None

    seg = (((ev.get("classifications") or [{}])[0]).get("segment") or {}).get("name", "").lower()
    kind = "concert" if seg == "music" else "sport" if seg == "sports" else "other"
    return make_event(name, venue, kind, start, DEFAULT_HOURS[kind], "ticketmaster", tbc)


def ticketmaster_events(now):
    key = os.environ.get("TICKETMASTER_API_KEY")
    if not key:
        raise RuntimeError("TICKETMASTER_API_KEY not set")
    start = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (now + dt.timedelta(days=DAYS_AHEAD)).strftime("%Y-%m-%dT%H:%M:%SZ")
    events, page = [], 0
    while True:
        params = {
            "apikey": key, "latlong": LATLONG, "radius": RADIUS_KM, "unit": "km",
            "countryCode": "GB", "size": 200, "page": page, "sort": "date,asc",
            "startDateTime": start, "endDateTime": end,
        }
        data = http_json("https://app.ticketmaster.com/discovery/v2/events.json?"
                         + urllib.parse.urlencode(params))
        for ev in (data.get("_embedded") or {}).get("events", []):
            parsed = parse_tm_event(ev)
            if parsed:
                events.append(parsed)
        page += 1
        total_pages = (data.get("page") or {}).get("totalPages", 1)
        if page >= total_pages or page * 200 >= 1000:   # API stops at 1000 results
            break
        time.sleep(0.3)
    return events


def man_city_home_matches():
    key = os.environ.get("FOOTBALL_DATA_API_KEY")
    if not key:
        raise RuntimeError("FOOTBALL_DATA_API_KEY not set")
    data = http_json(
        f"https://api.football-data.org/v4/teams/{MAN_CITY_ID}/matches?status=SCHEDULED,TIMED",
        headers={"X-Auth-Token": key},
    )
    out = []
    for m in data.get("matches", []):
        home = m.get("homeTeam") or {}
        if home.get("id") != MAN_CITY_ID:
            continue
        away = m.get("awayTeam") or {}
        opponent = away.get("shortName") or away.get("name") or "TBC"
        start = dt.datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
        tbc = m.get("status") == "SCHEDULED"   # date known, kick-off not confirmed yet
        out.append(make_event(f"Man City v {opponent}", "Etihad Stadium", "football",
                              start, DEFAULT_HOURS["football"], "football-data", tbc))
    return out


def extra_events():
    if not EXTRA_FILE.exists():
        return []
    items = json.loads(EXTRA_FILE.read_text()).get("events", [])
    out = []
    for it in items:
        start = dt.datetime.strptime(it["start"], "%Y-%m-%d %H:%M").replace(tzinfo=UK)
        out.append(make_event(it["name"], it.get("venue", "Etihad Campus"),
                              it.get("type", "other"), start,
                              float(it.get("duration_hours", 3)), "manual"))
    return out


def previous_events(source):
    """If a source fails, reuse what it gave us last time."""
    path = OUT_DIR / "events.json"
    if not path.exists():
        return []
    out = []
    for e in json.loads(path.read_text()).get("events", []):
        if e.get("source") == source:
            start = dt.datetime.fromtimestamp(e["start"], dt.timezone.utc)
            out.append(make_event(e["name"], e["venue"], e["type"], start,
                                  (e["end"] - e["start"]) / 3600, source, e.get("tbc", False)))
    return out


# ---------- output ----------

def dedupe(events):
    kept = []
    for e in events:   # earlier sources in the list win
        if any(k["venue"] == e["venue"] and abs((k["start"] - e["start"]).total_seconds()) < 2 * 3600
               for k in kept):
            continue
        kept.append(e)
    return sorted(kept, key=lambda e: e["start"])


def ics_escape(text):
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def write_outputs(events, now):
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / ".nojekyll").touch()

    light = {
        "generated": now.isoformat(timespec="seconds"),
        "generated_ts": int(now.timestamp()),
        "events": [
            {
                "name": e["name"],
                "venue": e["venue"],
                "type": e["type"],
                "start": int(e["start"].timestamp()),
                "end": int(e["end"].timestamp()),
                "start_local": e["start"].astimezone(UK).strftime("%a %d %b %H:%M"),
                "tbc": e["tbc"],
                "source": e["source"],
            }
            for e in events[:MAX_EVENTS_FOR_LIGHT]
        ],
    }
    (OUT_DIR / "events.json").write_text(json.dumps(light, indent=1, ensure_ascii=False))

    fmt = "%Y%m%dT%H%M%SZ"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//stadium-light//EN",
             "X-WR-CALNAME:Etihad & Co-op Live traffic", "CALSCALE:GREGORIAN"]
    for e in events:
        uid = f"{int(e['start'].timestamp())}-{hashlib.md5((e['venue'] + e['name']).encode()).hexdigest()[:10]}@stadium-light"
        summary = f"Traffic: {e['name']} ({e['venue']})" + (" - time TBC" if e["tbc"] else "")
        lines += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{now.strftime(fmt)}",
                  f"DTSTART:{e['start'].strftime(fmt)}", f"DTEND:{e['end'].strftime(fmt)}",
                  f"SUMMARY:{ics_escape(summary)}", f"LOCATION:{ics_escape(e['venue'] + ', Manchester')}",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    (OUT_DIR / "events.ics").write_text("\r\n".join(lines) + "\r\n")


def main():
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    sources = [
        ("football-data", man_city_home_matches),
        ("manual", extra_events),
        ("ticketmaster", lambda: ticketmaster_events(now)),
    ]
    collected, failed = [], []
    for name, fn in sources:
        try:
            got = fn()
            print(f"{name}: {len(got)} events")
            collected += got
        except Exception as exc:
            print(f"WARNING: {name} failed: {exc}", file=sys.stderr)
            failed.append(name)
            collected += previous_events(name)

    if "football-data" in failed and "ticketmaster" in failed:
        print("Both live sources failed; leaving the old file alone.", file=sys.stderr)
        sys.exit(1)   # light will show 'no data' blue if this keeps happening

    window_start = now - dt.timedelta(hours=6)
    events = dedupe([e for e in collected if e["end"] >= window_start])
    write_outputs(events, now)
    for e in events[:10]:
        print(f"  {e['start'].astimezone(UK):%a %d %b %H:%M}  {e['venue']:<15} {e['name']}")


if __name__ == "__main__":
    main()
