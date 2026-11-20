"""Read a DHT22 through the Linux kernel's dht11 IIO driver.

Enable the driver on Raspberry Pi OS with this line in
/boot/firmware/config.txt (then reboot):

    dtoverlay=dht11,gpiopin=14

The kernel handles the timing-critical bit-banging, so no Python sensor
library is needed: readings appear as files under /sys/bus/iio/devices.
"""

import logging
import math
import os
import random
import time
from pathlib import Path

log = logging.getLogger(__name__)

IIO_ROOT = Path(os.environ.get("IIO_ROOT", "/sys/bus/iio/devices"))
DEVICE_NAME = "dht11"  # the kernel driver's name, used for DHT22 too
RETRIES = 5
RETRY_DELAY = 2.0  # the sensor needs ~2s between reads


def find_device(root: Path | None = None) -> Path:
    """Return the IIO device directory for the dht11 driver."""
    root = root or IIO_ROOT
    for name_file in sorted(root.glob("iio:device*/name")):
        # Newer kernels append the device-tree unit address, e.g. "dht11@e".
        name = name_file.read_text().strip()
        if name == DEVICE_NAME or name.startswith(DEVICE_NAME + "@"):
            return name_file.parent
    raise FileNotFoundError(
        f"no {DEVICE_NAME} device under {root}; is dtoverlay=dht11 enabled?"
    )


def read_sensor(device: Path) -> tuple[float, float]:
    """Return (temperature in °C, relative humidity in %) from one read.

    The driver reports milli-units. A failed read raises OSError
    (usually EIO or ETIMEDOUT), which is normal for these sensors.
    """
    temperature = int((device / "in_temp_input").read_text()) / 1000
    humidity = int((device / "in_humidityrelative_input").read_text()) / 1000
    return temperature, humidity


def read_with_retries(
    device: Path, retries: int = RETRIES, delay: float = RETRY_DELAY
) -> tuple[float, float] | None:
    for attempt in range(1, retries + 1):
        try:
            return read_sensor(device)
        except OSError as err:
            log.warning("DHT read %d/%d failed: %s", attempt, retries, err)
            if attempt < retries:
                time.sleep(delay)
    return None


class KernelSensor:
    """The real sensor. Looks the device up on each read, so it copes with
    the driver loading after the app starts."""

    def read(self) -> tuple[float, float] | None:
        try:
            device = find_device()
        except FileNotFoundError as err:
            log.error("%s", err)
            return None
        return read_with_retries(device)


class FakeSensor:
    """Plausible synthetic readings for local development (SENSOR=fake)."""

    def read(self) -> tuple[float, float] | None:
        return fake_reading(time.time())


def fake_reading(ts: float, rng: random.Random | None = None) -> tuple[float, float]:
    """A daily temperature curve with a slow drift, and humidity that
    moves roughly opposite to it."""
    rng = rng or random
    day = 2 * math.pi * ((ts % 86400) / 86400)
    season = 2 * math.pi * (ts / (86400 * 120))
    temp = 21.0 + 1.8 * math.sin(day - 1.9) + 1.5 * math.sin(season) + rng.gauss(0, 0.04)
    hum = 55.0 - 6 * math.sin(day - 1.9) + 8 * math.sin(season + 1) + rng.gauss(0, 0.25)
    return round(temp, 1), round(hum, 1)


def make_sensor():
    return FakeSensor() if os.environ.get("SENSOR") == "fake" else KernelSensor()
