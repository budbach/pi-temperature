"""Serve DHT22 readings as Prometheus metrics.

The sensor is read through the Linux kernel's dht11 IIO driver (which also
supports the DHT22), enabled on Raspberry Pi OS with this line in
/boot/firmware/config.txt:

    dtoverlay=dht11,gpiopin=14

The kernel handles the timing-critical bit-banging, so no Python sensor
library is needed: readings appear as files under /sys/bus/iio/devices.
"""

import os
import time
from pathlib import Path

from flask import Flask

IIO_ROOT = Path(os.environ.get("IIO_ROOT", "/sys/bus/iio/devices"))
DEVICE_NAME = "dht11"  # the kernel driver's name, used for DHT22 too
RETRIES = 5
RETRY_DELAY = 2.0  # the sensor needs ~2s between reads

app = Flask(__name__)


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
            app.logger.warning("DHT read %d/%d failed: %s", attempt, retries, err)
            if attempt < retries:
                time.sleep(delay)
    return None


def format_metrics(temperature: float, humidity: float) -> str:
    return "\n".join(
        [
            "# HELP pi_temperature Temperature in degrees Celsius.",
            "# TYPE pi_temperature gauge",
            f"pi_temperature {temperature}",
            "# HELP pi_humidity Relative humidity in percent.",
            "# TYPE pi_humidity gauge",
            f"pi_humidity {humidity}",
            "",
        ]
    )


@app.route("/metrics")
def metrics():
    headers = {"Content-Type": "text/plain; version=0.0.4; charset=utf-8"}
    try:
        device = find_device()
    except FileNotFoundError as err:
        app.logger.error("%s", err)
        return f"# {err}\n", 503, headers

    reading = read_with_retries(device)
    if reading is None:
        app.logger.error("Incomplete data from DHT device")
        return "# sensor read failed\n", 503, headers

    temperature, humidity = reading
    app.logger.info("temperature=%s humidity=%s", temperature, humidity)
    return format_metrics(temperature, humidity), 200, headers


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
