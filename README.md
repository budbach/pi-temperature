## Pi Temperature

Simple web app that reads the temperature and humidity from a DHT22 on a
Raspberry Pi and serves them at `/metrics` in a format Prometheus can scrape.

The sensor is read through the Linux kernel's `dht11` driver (which also
handles the DHT22), so there is no Python sensor library to install.

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

4. Try it:

   ```bash
   uv run temperature.py
   curl http://localhost:5000/metrics
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

The `/metrics` endpoint returns HTTP 503 if the sensor can't be read after
several retries, so Prometheus records a failed scrape rather than a stale
value.

## Development

```bash
uv run pytest
```

The tests use a fake sysfs tree, so they run anywhere.
