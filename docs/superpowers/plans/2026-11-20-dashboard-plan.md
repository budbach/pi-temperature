# Temperature dashboard — implementation plan

Design: `docs/superpowers/specs/2026-11-20-dashboard-design.md` (approved 2026-11-20).

## Module layout

| File | Responsibility |
|------|----------------|
| `sensor.py` | Kernel IIO DHT reads (moved from `temperature.py`), plus a `FakeSensor` for local development (`SENSOR=fake`). |
| `store.py` | SQLite storage: open/create (WAL), `insert`, `raw(since)`, `hourly(since)`. New connection per call, so it's safe across threads. |
| `sampler.py` | Background thread: waits for clock sync, reads the sensor every 60 s, stores readings, and keeps `latest` in memory. `run_once()` for tests. |
| `temperature.py` | Flask app: `/`, `/static/*`, `/api/current`, `/api/history`, `/metrics`. `main()` starts the sampler and serves with waitress (one process). |
| `static/index.html`, `static/style.css`, `static/app.js` | The dark glass page. Hand-rolled SVG chart (no chart library): glow filter, gradient fill, min/max band, hover readout. |
| `scripts/seed_fake_data.py` | Fills a database with 90 days of synthetic readings, for local design work. |

## Steps

1. **sensor.py**: move the existing read code over unchanged, add `FakeSensor`, and update the tests' imports.
2. **store.py** + tests: schema, insert, raw window, hourly buckets (UTC, partial hour included, avg/min/max), empty DB.
3. **sampler.py** + tests: records when the clock is synced and skips when it isn't, skips failed reads, updates `latest`, `is_fresh` (5 min).
4. **temperature.py** routes + tests: `/metrics` from `latest` (503 when missing or stale), `/api/current`, `/api/history` validation and shapes, `/` serves the page.
5. **Page**: layout per the design; °F default with a remembered °C toggle; 30 s current refresh; chart refresh on tab switch or every 5 min for 24h; gaps break the line; stale/unreachable status.
6. **Packaging and service**: add the `waitress` dependency, `DB_PATH` env var (default `~/.local/share/pi-temperature/readings.db`), update the unit description, rewrite the README sections.
7. **Local check**: seed fake data, run with `SENSOR=fake`, and review the page in a browser at desktop and phone widths.
8. **Deploy**: rsync, `uv sync`, restart the user service. Verify `/`, `/api/*`, and `/metrics` on the Pi, then check that rows are accumulating.

## Clock sync check

The user service can't order itself after the system's `time-sync.target`,
so the sampler checks for `/run/systemd/timesync/synchronized` (created by
systemd-timesyncd). Where `/run/systemd/system` doesn't exist (macOS, dev),
the clock is assumed to be synced. `ASSUME_CLOCK_SYNCED=1` forces it.
