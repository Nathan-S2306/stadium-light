#!/usr/bin/env python3
"""
Bin Light - a second Govee bulb that shows which bin goes out.

Runs inside the same every-4-minutes loop as bulb.py. Reads docs/bins.json
(made by fetch_bins.py) and lights the bulb in the colour of the bin that's
due, from the evening before until late morning on collection day:

    grey bin  -> white
    green bin -> green
    brown bin -> orange
    two bins on the same day -> the bulb swaps between them every few minutes

Otherwise it's off. If the council lookup stops working, it keeps going by
assuming each bin stays on its fortnightly cycle.

Secrets / variables:
  GOVEE_BIN_DEVICE + GOVEE_BIN_SKU   the bin bulb (listed in the Update light log)
  GOVEE_BIN_API_KEY                  optional: only if the bin bulb is on a
                                     different Govee account; otherwise GOVEE_API_KEY is used
"""

import datetime as dt
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

UK = ZoneInfo("Europe/London")
ROOT = Path(__file__).resolve().parent
BINS_FILE = ROOT / "docs" / "bins.json"
STATE_FILE = ROOT / "docs" / "bin_light_state.json"   # not committed (see .gitignore)

SHOW_FROM = dt.time(17, 0)     # evening before collection
SHOW_UNTIL = dt.time(12, 0)    # midday on collection day
CYCLE_DAYS = 14
NIGHT_START, NIGHT_END = 23, 7
DAY_BRIGHTNESS, NIGHT_BRIGHTNESS = 60, 15

LOOKS = {   # bin -> (r, g, b)
    "grey":  (255, 255, 255),
    "green": (0, 255, 40),
    "brown": (255, 90, 0),
}
ORDER = ["grey", "green", "brown"]


def collection_dates(today):
    """{colour: [dates]} from bins.json, extended fortnightly if it's gone stale."""
    if not BINS_FILE.exists():
        return {}
    raw = json.loads(BINS_FILE.read_text()).get("bins", {})
    out = {}
    for colour, days in raw.items():
        dates = sorted(dt.date.fromisoformat(d) for d in days)
        if not dates:
            continue
        while dates[-1] < today:                     # lookup has stopped updating
            dates.append(dates[-1] + dt.timedelta(days=CYCLE_DAYS))
        out[colour] = dates
    return out


def due_now(now):
    """Bins whose 'put it out' window covers this moment."""
    local = now.astimezone(UK)
    due = []
    for colour, dates in collection_dates(local.date()).items():
        for d in dates:
            start = dt.datetime.combine(d - dt.timedelta(days=1), SHOW_FROM, tzinfo=UK)
            end = dt.datetime.combine(d, SHOW_UNTIL, tzinfo=UK)
            if start <= local < end:
                due.append(colour)
                break
    return sorted(due, key=ORDER.index)


def choose(due, last_shown):
    """Pick one colour; when two bins are due, take turns."""
    if not due:
        return None
    if last_shown in due:
        return due[(due.index(last_shown) + 1) % len(due)]
    return due[0]


def target_state(colour, now):
    if colour is None:
        return {"power": 0}
    hour = now.astimezone(UK).hour
    night = hour >= NIGHT_START or hour < NIGHT_END
    return {"power": 1, "rgb": list(LOOKS[colour]),
            "brightness": NIGHT_BRIGHTNESS if night else DAY_BRIGHTNESS}


def main():
    if os.environ.get("GOVEE_BIN_API_KEY"):
        os.environ["GOVEE_API_KEY"] = os.environ["GOVEE_BIN_API_KEY"]
    if not os.environ.get("GOVEE_API_KEY"):
        print("Bin light: no Govee API key - skipping.")
        return

    import bulb   # reuse the Govee helpers

    separate_account = bool(os.environ.get("GOVEE_BIN_API_KEY"))
    sku, device = os.environ.get("GOVEE_BIN_SKU"), os.environ.get("GOVEE_BIN_DEVICE")
    if not device:
        if separate_account:   # own account: just use its first colour bulb
            os.environ.pop("GOVEE_DEVICE", None)
            sku, device = bulb.find_bulb()
        else:
            print("Bin light: set GOVEE_BIN_DEVICE and GOVEE_BIN_SKU to pick the bin bulb.")
            os.environ.pop("GOVEE_DEVICE", None)
            bulb.find_bulb()   # prints the device list to copy from
            return
    if not device or not sku:
        print("Bin light: bulb not found - skipping.")
        return

    now = dt.datetime.now(dt.timezone.utc)
    previous = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    due = due_now(now)
    colour = choose(due, previous.get("colour"))
    state = target_state(colour, now)
    print(f"Bin light {now.astimezone(UK):%a %d %b %H:%M} -> "
          f"{colour or 'off'} (due: {', '.join(due) or 'nothing'})  {state}")

    if state == previous.get("state") and "--force" not in sys.argv:
        print("Bin light: no change.")
        return

    if state["power"] == 0:
        bulb.send(sku, device, "devices.capabilities.on_off", "powerSwitch", 0)
    else:
        r, g, b = state["rgb"]
        bulb.send(sku, device, "devices.capabilities.on_off", "powerSwitch", 1)
        bulb.send(sku, device, "devices.capabilities.color_setting", "colorRgb", (r << 16) + (g << 8) + b)
        bulb.send(sku, device, "devices.capabilities.range", "brightness", state["brightness"])
    STATE_FILE.write_text(json.dumps({"colour": colour, "state": state,
                                      "changed": now.isoformat(timespec="seconds")}))
    print("Bin light updated.")


if __name__ == "__main__":
    main()
