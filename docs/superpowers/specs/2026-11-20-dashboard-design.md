# Temperature dashboard — design

Date: 2026-11-20
Status: draft for approval

## Intent

The Pi Zero W reads a DHT22 and serves the current values at `/metrics`.
Readings used to be stored and charted by Prometheus and Grafana running in
Docker on the old Pi (see the `pi-temperature-monitor` repo). That died with
the old SD card, so today nothing is recorded and there is no history.

The goal is a single web page on the home network that looks great and
shows:

- the current temperature and humidity at a glance,
- the last 24 hours in fine detail,
- 30-day and 90-day trends.

It replaces the old Grafana dashboard (current °F, current humidity, two
24-hour graphs) with something better looking and with longer history.

## Goals

- Record a reading about once a minute, all the time, on the Pi itself.
- One page with: big current values, a "last updated" indicator, and a
  chart that switches between 24h, 30d and 90d.
- "Dark glass" visual style (chosen from mockups): deep navy radial
  gradient background, thin oversized numerals, translucent card behind the
  chart, glowing temperature line with a soft gradient fill under it,
  humidity as a second, quieter line. Should look good on a laptop, a phone,
  and an always-on tablet across the room.
- Runs entirely on the Pi Zero W (armv6, 512 MB RAM) alongside the existing
  app. No Docker, no second machine.
- Keep `/metrics` working unchanged, so Prometheus can scrape it again later.

## Non-goals

- Access from outside the home network, logins, or HTTPS.
- Alerts or notifications.
- Multiple sensors or multiple rooms.
- Restoring old history (it's gone).
- Grafana compatibility beyond keeping `/metrics`.
- Automated backups (see "Left to the builder" for a lightweight option).

## Anti-goals

- Anything that makes the Pi struggle: heavy runtimes, a build step that
  has to run on the Pi, or per-request sensor reads holding up page loads.
- A page that looks like a generic admin dashboard. The look is the point.
- Writing to the SD card much more than needed (the last card died).

## Constraints

- Pi Zero W: single-core armv6, 512 MB RAM, Raspberry Pi OS Lite (Trixie),
  Python 3.13, managed with uv. Existing service is a systemd **user** unit
  running `temperature.py` (Flask) on port 5000.
- Sensor is read through the kernel `dht11` IIO driver; one read takes up to
  a couple of seconds and fails now and then (EIO/ETIMEDOUT). The sensor
  needs about 2 s between reads.
- Home network only; reached as `http://pi-temperature.local:5000/`.
- No CDN dependence at runtime is preferred but not required (the LAN has
  internet). See "Left to the builder".

## Approaches considered

- **A. Everything on the Pi (chosen).** The Flask app gains a background
  sampler that stores one reading a minute in SQLite, plus a JSON API and
  a static page. 24h uses raw readings; 30d/90d use hourly averages with
  min/max computed by SQL when requested. Self-contained, light, and gives
  full control over the look. Downside: custom code for new views; history
  lives on the SD card.
- **B. Prometheus + Grafana on another always-on machine.** Most flexible,
  but needs a machine that is always on (the MacBook isn't, and current
  Grafana doesn't run on armv6), and Grafana is hard to make look polished.
- **C. A now, Grafana later.** Not a separate build; A keeps `/metrics`, so
  this stays possible.

The user picked **A**.

## Design

### Data collection

- A background sampler thread in the existing Flask process reads the
  sensor every 60 s, reusing `find_device` / `read_with_retries` from
  `temperature.py`.
- Each successful reading is inserted into SQLite:
  `readings(ts INTEGER PRIMARY KEY, temp_c REAL, humidity REAL)`,
  where `ts` is Unix seconds (UTC). Failed reads after retries are skipped
  (a gap in the data), and the failure is logged.
- The sampler also keeps the latest reading in memory.
- Database file lives outside the repo checkout, at
  `~/.local/share/pi-temperature/readings.db` (overridable with an env var),
  so `git pull` / redeploys never touch it.
- Raw readings are kept indefinitely. At one row a minute that's about
  525k rows (~20 MB) a year, which is fine.
- SQLite in WAL mode. One small insert a minute is a negligible write load.

### `/metrics`

- Serves the latest in-memory reading instead of reading the sensor on each
  request, so scrapes are instant and don't compete with the sampler for the
  sensor.
- Returns 503 if there is no reading yet, or the latest one is older than
  5 minutes (sensor stuck), so Prometheus sees a failed scrape rather than a
  stale value.
- Metric names, units and format unchanged.

### JSON API

- `GET /api/current` →
  `{"ts": ..., "temp_c": ..., "humidity": ...}` or 503 as above.
- `GET /api/history?range=24h|30d|90d` →
  - `24h`: raw points `[ts, temp_c, humidity]` for the last 24 hours.
  - `30d` / `90d`: hourly buckets
    `[ts_hour_start, temp_avg, temp_min, temp_max, hum_avg, hum_min, hum_max]`.
  - Values are in °C / %; the page converts units.
- Gaps (missing minutes/hours) are simply absent; the chart should show them
  as breaks, not straight lines across them, when a gap is longer than a few
  sample intervals.

### The page

- Served at `/` by the same Flask app, as static HTML/CSS/JS with no build
  step.
- Layout (top to bottom):
  - Big current temperature and humidity, thin numerals, units smaller and
    dimmer.
  - Status line: a live dot plus "updated 20s ago", and the min–max
    temperature for the range shown. The dot and text change colour/wording
    when the data is stale (older than 5 minutes) or the Pi is unreachable.
  - Range tabs: 24h · 30d · 90d.
  - Chart in a translucent card: temperature as the glowing primary line
    with gradient fill; humidity as a quieter second line on its own scale.
    For 30d/90d, draw the hourly average as the line with a faint shaded
    min–max band behind it.
  - Hovering or touching the chart shows the time and values at that point.
- Units: °F is the main unit (as on the old dashboard). A small toggle
  switches to °C and is remembered in the browser.
- Refresh: current values every 30 s; the chart data every few minutes (24h)
  or on tab switch (30d/90d). No full page reloads.
- Responsive: works at phone width; on a large screen the numbers get
  bigger rather than the layout getting busier.

## Calls made while writing this up (not discussed)

- **Clock at boot:** the Pi Zero W has no real-time clock. The sampler
  doesn't record until the system clock has synced (the user service waits
  for `time-sync.target`, or the sampler checks sync status), so no readings
  get 1970 or stale timestamps.
- **Hourly buckets** are grouped by UTC hour and include the current partial
  hour; the browser converts all times to local time for display.
- **Exactly one sampler:** the app runs as a single process (a small
  production server such as waitress, or Flask's threaded server with the
  reloader off), never with multiple workers.
- **24h is the default tab.** The DB directory is created on startup.
- README and the systemd unit description are updated to match (they
  currently say `/metrics` reads the sensor per request).

## Changed during the build

- **30d and 90d show one point per day, not per hour.** Hourly points over
  90 days showed every daily swing and buried the trend. The API still
  returns hourly buckets; the page groups them into local days and draws the
  daily average as a smooth line, with the day's low–high as the band.
  Days with fewer than 18 hours of data (today, either side of an outage)
  are left out, because their averages are skewed.
- **The 24h line is lightly smoothed for drawing** (9-point rolling
  average). The sensor's 0.1° steps otherwise look like a staircase. Hover
  shows the raw reading.
- **Charts are hand-drawn SVG**, with no chart library, to get the glow and
  temperature-coloured line exactly.

## Left to the builder

- Charting library, as long as it's small and fast on a phone or tablet
  (uPlot is a good fit; Chart.js would also work). Whether to vendor it into
  the repo or load it from a CDN.
- Exact colours, fonts and spacing within the dark-glass direction, the
  gap-detection threshold, the stale-indicator styling.
- How the sampler thread is started and stopped cleanly with Flask, and
  whether to switch from Flask's dev server to a small production server
  (e.g. waitress) given the extra background work.
- Tests: unit tests for storage and the history/rollup queries using a
  temporary database, and for `/metrics` and `/api/*` with a fake sensor.
  The page itself is checked by hand.
- Optional, lightweight backup of `readings.db` (e.g. a weekly
  `sqlite3 .backup` to the Mac or a USB stick), documented in the README
  rather than automated.
