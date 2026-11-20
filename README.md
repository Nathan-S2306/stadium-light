# Stadium Light (smart bulb version)

A smart bulb that changes colour when something's on at the Etihad or Co-op Live, so nobody gets caught in event traffic. You don't need any wiring or extra hardware, and you don't need to leave a computer running.

## What the colours mean

**Co-op Live** (and any other concert or show)

| Time | Bulb |
|---|---|
| From 12 midday on the day | Green |
| 2 hours before the start | Red (crowds arriving) |
| During the event | Green |
| 1 hour after it ends | Red (crowds leaving) |

**Man City home games**

| Time | Bulb |
|---|---|
| From 4 hours before kick-off | Sky blue |
| 2 hours before kick-off | Red (crowds arriving) |
| During the match | Sky blue |
| 1 hour after the final whistle | Red (crowds leaving) |

At all other times the bulb is **off**. If two events overlap, red wins, then blue. A very dim white light means the event data has gone stale (see Troubleshooting).

Brightness is 40%, dropping to 15% between 11pm and 7am.

## What to buy

**One Govee Wi-Fi colour bulb (about £10–£15).**
- Search for "Govee smart bulb RGBWW Wi-Fi" and pick a standard screw (E27) or bayonet (B22) fitting to match your lamp.
- Make sure it says **Wi-Fi**. Bluetooth-only Govee bulbs won't work, because the system controls the bulb over the internet through Govee's free developer API.
- Put it in a lamp that's somewhere she walks past: by the front door, in the hallway, or near where the keys go.

That's everything you need to buy. The system runs free on GitHub.

## How it works

```
Twice a day:      fetch_events.py  -> finds events at Co-op Live / Etihad -> docs/events.json
Every 10 minutes: bulb.py          -> reads events.json -> sets the bulb colour (only when it needs to change)
```

Both run free on GitHub Actions. Because `bulb.py` only sends a command when the colour should change, she can turn the bulb off in the Govee app and it will stay off until the next change.

---

## Setup (about 20 minutes)

### 1. Set up the bulb
Screw it in, install the **Govee Home** app, and add the bulb to your Wi-Fi. Check you can change its colour from the app.

### 2. Get three free API keys
- **Govee:** in the Govee Home app, go to Profile (person icon) → Settings (cog) → **Apply for API Key**. Fill in the short form (reason: "home automation"), and the key arrives by email.
- **Ticketmaster:** sign up at developer.ticketmaster.com, create an app, and copy the "Consumer Key". This covers concerts and shows.
- **football-data.org:** register for the free tier, and you'll receive a token by email. This covers Man City home Premier League and Champions League games.

### 3. Put the project on GitHub
1. Create a free GitHub account, then a new repository called `stadium-light`. Set it to **public**; GitHub Actions minutes are unlimited for public repos.
2. Upload everything in this folder, **including the hidden `.github` folder**. GitHub Desktop is easiest, because some file browsers hide folders starting with a dot.

### 4. Add your keys as secrets
In the repo, go to **Settings → Secrets and variables → Actions → New repository secret**, and add:
- `GOVEE_API_KEY`
- `TICKETMASTER_API_KEY`
- `FOOTBALL_DATA_API_KEY`

Secrets stay private even though the repo is public.

### 5. Start it
1. Go to **Actions** and enable workflows if asked.
2. Open **Update events → Run workflow** and wait for the green tick.
3. Open **Update light → Run workflow**, tick "force", and run it. The bulb should change within a few seconds: it switches off if nothing is on today, or shows a colour if something is.

That's it. From now on it runs by itself.

---

## Optional extras

**Calendar on both phones:** turn on **Settings → Pages**, set it to deploy from the `main` branch using the `/docs` folder, then subscribe to:
`https://YOUR_USERNAME.github.io/stadium-light/events.ics`
- On iPhone: Settings → Calendar → Accounts → Add Subscribed Calendar.
- On Google Calendar: Other calendars → From URL.

**Faint glow instead of off on quiet days:** go to Settings → Secrets and variables → Actions → **Variables** tab, and add `IDLE_MODE` with the value `glow`.

**More than one Govee device:** by default the system uses the first colour bulb on your account. To choose a specific one, open the latest **Update light** run log. It lists your devices with their `sku` and `device` values. Add those as the secrets `GOVEE_SKU` and `GOVEE_DEVICE`.

**Cup games:** the free football feed doesn't include FA Cup or League Cup games. Add them by hand in `extra_events.json` (there's an example inside); they'll be picked up at the next twice-daily update.

**Timings and colours:** these are set at the top of `bulb.py` (`RUSH_BEFORE_START`, `NIGHT_START`, the `LOOKS` colour table, and so on).

---

## Bin light (second bulb, Kirklees / Huddersfield)

A second Govee bulb that shows which bin goes out, from **5pm the evening before until midday on collection day**. It's off the rest of the time.

| Bin | Bulb |
|---|---|
| Grey (general waste) | White |
| Green (recycling) | Green |
| Brown (garden waste) | Orange |
| Two bins on the same day | Swaps between the two colours every few minutes |

Brightness is 60%, dropping to 15% between 11pm and 7am. Collection dates come from the Kirklees "Manage your bins" service twice a day. If that service ever stops answering, the light keeps going by assuming each bin stays on its fortnightly cycle. Bank holiday and Christmas changes come through from the council automatically.

### Setup
1. Add the second bulb in the **Govee Home** app. If it's on the same Govee account, the existing API key covers it. If it's on a different account (a different house, say), request a key on that account and add it as the secret `GOVEE_BIN_API_KEY`.
2. Find the property's **UPRN** (Unique Property Reference Number) by searching the postcode on findmyaddress.co.uk or uprn.uk and picking the address.
3. Go to **Settings → Secrets and variables → Actions → Variables** and add `BIN_UPRN` with that number.
4. Run **Update events** so it fetches the bin dates; the log lists them.
5. Run **Update light** with "force" ticked, then open its log. It lists your Govee devices with their `sku` and `device` values. Add the bin bulb's values as the secrets `GOVEE_BIN_SKU` and `GOVEE_BIN_DEVICE`, then run **Update light** with "force" once more. (Skip this step if the bin bulb has its own `GOVEE_BIN_API_KEY` and is the only bulb on that account.)

Times and colours are at the top of `bin_bulb.py` (`SHOW_FROM`, `SHOW_UNTIL`, `LOOKS`).

---

## Troubleshooting

- **Bulb never changes:** open Actions → Update light → the latest run, and read the log. It prints what it decided ("rush_in: Big Pop Tour starts 19:45") and any error from Govee. The usual causes are a mistyped API key or a Bluetooth-only bulb.
- **Very dim white:** the event list hasn't updated for 36 hours or more. Check the **Update events** runs for errors, such as an expired API key.
- **Changes arrive a little late:** GitHub sometimes runs scheduled jobs 5–15 minutes behind. That's fine for a 3-hour warning window.
- **Bin light never changes:** check the "Fetch bin dates" step in the latest **Update events** run. It prints what the council returned. An empty reply usually means the UPRN is wrong.
- **Workflows stopped after a couple of months:** GitHub pauses scheduled jobs in repos with no activity for 60 days. The twice-daily event commits normally count as activity, but if it ever happens, click "Enable workflow" in Actions.
