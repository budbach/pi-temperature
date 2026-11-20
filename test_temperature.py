import errno
from pathlib import Path

import pytest

import temperature


def make_device(root: Path, index: int, name: str, temp=None, hum=None) -> Path:
    dev = root / f"iio:device{index}"
    dev.mkdir(parents=True)
    (dev / "name").write_text(name + "\n")
    if temp is not None:
        (dev / "in_temp_input").write_text(f"{temp}\n")
    if hum is not None:
        (dev / "in_humidityrelative_input").write_text(f"{hum}\n")
    return dev


def test_find_device_picks_dht11(tmp_path):
    make_device(tmp_path, 0, "some_adc")
    dev = make_device(tmp_path, 1, "dht11")
    assert temperature.find_device(tmp_path) == dev


def test_find_device_with_unit_address(tmp_path):
    # Raspberry Pi OS Trixie kernels name the device "dht11@e".
    make_device(tmp_path, 0, "dht11x")
    dev = make_device(tmp_path, 1, "dht11@e")
    assert temperature.find_device(tmp_path) == dev


def test_find_device_missing(tmp_path):
    make_device(tmp_path, 0, "some_adc")
    with pytest.raises(FileNotFoundError):
        temperature.find_device(tmp_path)


def test_read_sensor_converts_milli_units(tmp_path):
    dev = make_device(tmp_path, 0, "dht11", temp=21300, hum=45600)
    assert temperature.read_sensor(dev) == (21.3, 45.6)


def test_read_with_retries_recovers(tmp_path, monkeypatch):
    dev = make_device(tmp_path, 0, "dht11")
    calls = []

    def flaky(_device):
        calls.append(1)
        if len(calls) < 3:
            raise OSError(errno.ETIMEDOUT, "timed out")
        return (20.0, 50.0)

    monkeypatch.setattr(temperature, "read_sensor", flaky)
    assert temperature.read_with_retries(dev, retries=5, delay=0) == (20.0, 50.0)
    assert len(calls) == 3


def test_read_with_retries_gives_up(tmp_path, monkeypatch):
    def broken(_device):
        raise OSError(errno.EIO, "io error")

    monkeypatch.setattr(temperature, "read_sensor", broken)
    assert temperature.read_with_retries(tmp_path, retries=2, delay=0) is None


def test_metrics_endpoint(tmp_path, monkeypatch):
    make_device(tmp_path, 0, "dht11", temp=19500, hum=40250)
    monkeypatch.setattr(temperature, "IIO_ROOT", tmp_path)
    client = temperature.app.test_client()
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "pi_temperature 19.5" in body
    assert "pi_humidity 40.25" in body


def test_metrics_endpoint_no_device(tmp_path, monkeypatch):
    monkeypatch.setattr(temperature, "IIO_ROOT", tmp_path)
    resp = temperature.app.test_client().get("/metrics")
    assert resp.status_code == 503
