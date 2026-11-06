#!/usr/bin/env python3
"""
Stadium Light - smart bulb controller (Govee Wi-Fi bulbs, cloud API).

Runs every ~10 minutes on GitHub Actions. Reads docs/events.json (made by
fetch_events.py), works out what the bulb should show right now, and only
talks to the bulb when that changes, so turning it off by hand sticks until the
next change.

Colours
  Off (or faint warm glow)  nothing on today
  Sky blue                  Man City home game later today or in progress
  Purple                    concert / show later today or in progress
  Amber                     traffic building: 3h before start until start
  Red                       crowds leaving: 30 min before end until 75 min after
  Dim white                 event data is over 36h old (something's broken)

Secrets / environment:
  GOVEE_API_KEY   required (request it in the Govee Home app)
  GOVEE_DEVICE    optional: the bulb's device id (auto-picks the first colour bulb if unset)
  GOVEE_SKU       optional: the bulb's model, needed only when GOVEE_DEVICE is set
  IDLE_MODE       optional: "off" (default) or "glow"
"""

import datetime as dt
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

UK = ZoneInfo("Europe/London")
ROOT = Path(__file__).resolve().parent
EVENTS_FILE = ROOT / "docs" / "events.json"
STATE_FILE = ROOT / "docs" / "light_state.json"
API = "https://openapi.api.govee.com/router/api/v1"

RUSH_BEFORE_START = dt.timedelta(hours=3)
RUSH_BEFORE_END = dt.timedelta(minutes=30)
RUSH_AFTER_END = dt.timedelta(minutes=75)
STALE_AFTER = dt.timedelta(hours=36)
NIGHT_START, NIGHT_END = 23, 7          # dim between these hours (UK time)
DAY_BRIGHTNESS, NIGHT_BRIGHTNESS = 40, 15

LOOKS = {   # mode -> (r, g, b, brightness %)   brightness None = use day/night level
    "rush_out":   (255, 0, 0, None),
    "rush_in":    (255, 110, 0, None),
    "today_city": (108, 171, 221, None),
    "today_gig":  (150, 40, 255, None),
    "stale":      (255, 255, 255, 10),
    "idle_glow":  (255, 140, 60, 8),
}


# ---------- deciding what to show ----------

def load_events():
    data = json.loads(EVENTS_FILE.read_text())
    gen = dt.datetime.fromtimestamp(data.get("generated_ts", 0), dt.timezone.utc)
    events = []
    for e in data.get("events", []):
        events.append({
            "name": e["name"],
            "football": e.get("type") == "football",
            "start": dt.datetime.fromtimestamp(e["start"], dt.timezone.utc),
            "end": dt.datetime.fromtimestamp(e["end"], dt.timezone.utc),
        })
    return gen, events


def decide(now, generated, events):
    """Return (mode, reason)."""
    if now - generated > STALE_AFTER:
        return "stale", "event data is out of date"
    today = now.astimezone(UK).date()
    best = ("idle", "nothing on today")
    for e in sorted(events, key=lambda e: e["start"]):
        if e["end"] - RUSH_BEFORE_END <= now <= e["end"] + RUSH_AFTER_END:
            return "rush_out", f"{e['name']} finishing"
        if e["start"] <= now < e["end"] - RUSH_BEFORE_END:
            if best[0] != "rush_in":
                mode = "today_city" if e["football"] else "today_gig"
                best = (mode, f"{e['name']} in progress")
            continue
        if e["start"] - RUSH_BEFORE_START <= now < e["start"]:
            if best[0] != "rush_in":
                best = ("rush_in", f"{e['name']} starts {e['start'].astimezone(UK):%H:%M}")
        elif best[0] == "idle" and e["start"] > now and e["start"].astimezone(UK).date() == today:
            mode = "today_city" if e["football"] else "today_gig"
            best = (mode, f"{e['name']} at {e['start'].astimezone(UK):%H:%M}")
    return best


def target_state(mode, now):
    hour = now.astimezone(UK).hour
    night = hour >= NIGHT_START or hour < NIGHT_END
    if mode == "idle":
        if os.environ.get("IDLE_MODE", "off").lower() == "glow":
            mode = "idle_glow"
        else:
            return {"power": 0}
    r, g, b, bri = LOOKS[mode]
    if bri is None:
        bri = NIGHT_BRIGHTNESS if night else DAY_BRIGHTNESS
    return {"power": 1, "rgb": [r, g, b], "brightness": bri}


# ---------- talking to the bulb ----------

def govee(method, path, body=None):
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Govee-API-Key": os.environ["GOVEE_API_KEY"],
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        reply = json.load(r)
    if reply.get("code") not in (200, None):
        raise RuntimeError(f"Govee said: {reply}")
    return reply


def find_bulb():
    if os.environ.get("GOVEE_DEVICE"):
        if not os.environ.get("GOVEE_SKU"):
            sys.exit("GOVEE_DEVICE is set, so GOVEE_SKU must be set too.")
        return os.environ["GOVEE_SKU"], os.environ["GOVEE_DEVICE"]
    devices = govee("GET", "/user/devices").get("data", [])
    print("Devices on your Govee account:")
    for d in devices:
        print(f"  {d.get('deviceName')!r}  sku={d.get('sku')}  device={d.get('device')}")
    for d in devices:
        caps = {c.get("instance") for c in d.get("capabilities", [])}
        if "colorRgb" in caps and "powerSwitch" in caps:
            print(f"Using {d.get('deviceName')!r}")
            return d["sku"], d["device"]
    return None, None


def send(sku, device, ctype, instance, value):
    govee("POST", "/device/control", {
        "requestId": f"stadium-{int(time.time() * 1000)}",
        "payload": {"sku": sku, "device": device,
                    "capability": {"type": ctype, "instance": instance, "value": value}},
    })
    time.sleep(0.4)


def apply(state):
    sku, device = find_bulb()
    if not device:
        print("No colour bulb on the Govee account yet - add it in the Govee Home app. Skipping.")
        return False
    if state["power"] == 0:
        send(sku, device, "devices.capabilities.on_off", "powerSwitch", 0)
        return True
    r, g, b = state["rgb"]
    send(sku, device, "devices.capabilities.on_off", "powerSwitch", 1)
    send(sku, device, "devices.capabilities.color_setting", "colorRgb", (r << 16) + (g << 8) + b)
    send(sku, device, "devices.capabilities.range", "brightness", int(state["brightness"]))
    return True


# ---------- main ----------

def main():
    if not os.environ.get("GOVEE_API_KEY"):
        print("No GOVEE_API_KEY secret yet - skipping until the bulb is set up.")
        return
    now = dt.datetime.now(dt.timezone.utc)
    try:
        generated, events = load_events()
    except FileNotFoundError:
        generated, events = dt.datetime.fromtimestamp(0, dt.timezone.utc), []

    mode, reason = decide(now, generated, events)
    state = target_state(mode, now)
    print(f"{now.astimezone(UK):%a %d %b %H:%M} -> {mode}: {reason}  {state}")

    previous = json.loads(STATE_FILE.read_text()).get("state") if STATE_FILE.exists() else None
    force = "--force" in sys.argv
    if state == previous and not force:
        print("No change; leaving the bulb alone.")
        return

    if not apply(state):
        return
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(
        {"mode": mode, "reason": reason, "state": state,
         "changed": now.isoformat(timespec="seconds")}, indent=1))
    print("Bulb updated.")


if __name__ == "__main__":
    main()
