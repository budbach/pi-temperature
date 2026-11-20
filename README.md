## Pi Temperature

A small web app for a Raspberry Pi with a DHT22 sensor. It records the
temperature and humidity once a minute and serves:

- **a dashboard** at `/`: current readings, plus charts for the last 24
  hours, 30 days and 90 days;
- **`/metrics`** for Prometheus, if you want to scrape it;
- **`/api/current`** and **`/api/history?range=24h|30d|90d`** as JSON.

The sensor is read through the Linux kernel's `dht11` driver (which also
handles the DHT22), so there is no Python sensor library to install.
Readings are stored in SQLite at `~/.local/share/pi-temperature/readings.db`
(set `DB_PATH` to change it).

## Setup

Tested on Raspberry Pi OS Lite (Trixie) on a Pi Zero W, with the DHT22 data
pin on GPIO 14.

1. Enable the kernel driver by adding this line to `/boot/firmware/config.txt`,
   then reboot:

   ```
   dtoverlay=dht11,gpiopin=14
   ```

   Check that it's working:

   ```bash
   cat /sys/bus/iio/devices/iio:device0/in_temp_input
   ```

   (millidegrees C; an occasional `Input/output error` or timeout is normal.)

2. Install [uv](https://docs.astral.sh/uv/):

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

3. Clone and install:

   ```bash
   git clone https://github.com/budbach/pi-temperature.git ~/pi-temperature
   cd ~/pi-temperature
   uv sync --frozen --no-dev
   ```

4. Try it, then open `http://<your-pi>.local:5000/` in a browser:

   ```bash
   uv run temperature.py
   ```

5. Run it on boot as a systemd user service (it runs as your user, so
   nothing in the unit file needs editing):

   ```bash
   mkdir -p ~/.config/systemd/user
   cp pi-temperature.service ~/.config/systemd/user/
   systemctl --user daemon-reload
   systemctl --user enable --now pi-temperature
   sudo loginctl enable-linger "$USER"
   journalctl --user -u pi-temperature -f
   ```

   `enable-linger` lets your user services start at boot without you
   logging in.

The Pi Zero W has no real-time clock, so after a reboot the app waits for
the clock to sync over the network before recording anything.

`/metrics` and `/api/current` return HTTP 503 when there's no reading from
the last 5 minutes, so Prometheus records a failed scrape rather than a
stale value.

## Updating

```bash
cd ~/pi-temperature
git pull
uv sync --frozen --no-dev
systemctl --user restart pi-temperature
```

## Backing up the history

The readings live in one SQLite file. To copy it safely while the app is
running, from another machine:

```bash
ssh <your-pi>.local 'sqlite3 ~/.local/share/pi-temperature/readings.db ".backup /tmp/readings.db"'
scp <your-pi>.local:/tmp/readings.db ./readings-backup.db
```

(`sudo apt install sqlite3` on the Pi if the `sqlite3` command is missing.)

## Development

```bash
uv run pytest
```

The tests use a fake sensor and temporary databases, so they run anywhere.

To work on the page without a Pi, fill a database with 90 days of
synthetic readings and run with the fake sensor:

```bash
DB_PATH=/tmp/fake.db uv run scripts/seed_fake_data.py
SENSOR=fake DB_PATH=/tmp/fake.db uv run temperature.py
```
