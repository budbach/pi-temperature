"""Background sampler: read the sensor on a fixed interval and store it."""

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

INTERVAL = 60  # seconds between readings
STALE_AFTER = 300  # a reading older than this is considered stale


@dataclass(frozen=True)
class Reading:
    ts: int
    temp_c: float
    humidity: float


def clock_synced() -> bool:
    """True once the system clock can be trusted.

    The Pi Zero W has no real-time clock, so until NTP syncs after boot
    the time can be far off. systemd-timesyncd creates this file once it
    has synced. On systems without systemd (e.g. macOS for development)
    the clock is assumed to be fine.
    """
    if os.environ.get("ASSUME_CLOCK_SYNCED") == "1":
        return True
    if not Path("/run/systemd/system").exists():
        return True
    return Path("/run/systemd/timesync/synchronized").exists()


class Sampler:
    def __init__(self, sensor, store, interval=INTERVAL, clock_ok=clock_synced,
                 now=time.time):
        self.sensor = sensor
        self.store = store
        self.interval = interval
        self.clock_ok = clock_ok
        self.now = now
        self._latest: Reading | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Seed from the database so /metrics has a value right after a restart.
        row = store.latest()
        if row:
            self._latest = Reading(*row)

    @property
    def latest(self) -> Reading | None:
        return self._latest

    def is_fresh(self) -> bool:
        r = self._latest
        return r is not None and self.now() - r.ts <= STALE_AFTER

    def run_once(self) -> Reading | None:
        """Take one reading and store it. Returns it, or None if skipped."""
        if not self.clock_ok():
            log.info("clock not synced yet; skipping reading")
            return None
        result = self.sensor.read()
        if result is None:
            log.error("sensor read failed after retries")
            return None
        temp_c, humidity = result
        reading = Reading(int(self.now()), temp_c, humidity)
        self.store.insert(reading.ts, reading.temp_c, reading.humidity)
        self._latest = reading
        return reading

    def _loop(self):
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self.run_once()
            except Exception:  # keep sampling whatever happens
                log.exception("unexpected error while sampling")
            elapsed = time.monotonic() - started
            self._stop.wait(max(1.0, self.interval - elapsed))

    def start(self):
        self._thread = threading.Thread(target=self._loop, name="sampler", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
