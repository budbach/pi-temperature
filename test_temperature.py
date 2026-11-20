import errno
from pathlib import Path

import pytest

import sensor
import temperature
from sampler import Sampler
from store import Store


# --- sensor -----------------------------------------------------------------

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
    assert sensor.find_device(tmp_path) == dev


def test_find_device_with_unit_address(tmp_path):
    # Raspberry Pi OS Trixie kernels name the device "dht11@e".
    make_device(tmp_path, 0, "dht11x")
    dev = make_device(tmp_path, 1, "dht11@e")
    assert sensor.find_device(tmp_path) == dev


def test_find_device_missing(tmp_path):
    make_device(tmp_path, 0, "some_adc")
    with pytest.raises(FileNotFoundError):
        sensor.find_device(tmp_path)


def test_read_sensor_converts_milli_units(tmp_path):
    dev = make_device(tmp_path, 0, "dht11", temp=21300, hum=45600)
    assert sensor.read_sensor(dev) == (21.3, 45.6)


def test_read_with_retries_recovers(tmp_path, monkeypatch):
    calls = []

    def flaky(_device):
        calls.append(1)
        if len(calls) < 3:
            raise OSError(errno.ETIMEDOUT, "timed out")
        return (20.0, 50.0)

    monkeypatch.setattr(sensor, "read_sensor", flaky)
    assert sensor.read_with_retries(tmp_path, retries=5, delay=0) == (20.0, 50.0)
    assert len(calls) == 3


def test_read_with_retries_gives_up(tmp_path, monkeypatch):
    def broken(_device):
        raise OSError(errno.EIO, "io error")

    monkeypatch.setattr(sensor, "read_sensor", broken)
    assert sensor.read_with_retries(tmp_path, retries=2, delay=0) is None


def test_kernel_sensor_without_device(tmp_path, monkeypatch):
    monkeypatch.setattr(sensor, "IIO_ROOT", tmp_path)
    assert sensor.KernelSensor().read() is None


def test_fake_reading_is_plausible():
    t, h = sensor.fake_reading(1_800_000_000)
    assert 10 < t < 35 and 20 < h < 90


# --- sampler ----------------------------------------------------------------

class StubSensor:
    def __init__(self, *results):
        self.results = list(results)

    def read(self):
        return self.results.pop(0)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "r.db")


def test_sampler_records_reading(store):
    clock = Clock(1000)
    s = Sampler(StubSensor((21.5, 40.0)), store, clock_ok=lambda: True, now=clock)
    r = s.run_once()
    assert (r.ts, r.temp_c, r.humidity) == (1000, 21.5, 40.0)
    assert store.raw(0) == [(1000, 21.5, 40.0)]
    assert s.latest == r


def test_sampler_waits_for_clock_sync(store):
    s = Sampler(StubSensor((21.5, 40.0)), store, clock_ok=lambda: False)
    assert s.run_once() is None
    assert store.raw(0) == []


def test_sampler_skips_failed_read(store):
    s = Sampler(StubSensor(None), store, clock_ok=lambda: True)
    assert s.run_once() is None
    assert store.raw(0) == []


def test_sampler_freshness(store):
    clock = Clock(1000)
    s = Sampler(StubSensor((20.0, 50.0)), store, clock_ok=lambda: True, now=clock)
    assert not s.is_fresh()
    s.run_once()
    assert s.is_fresh()
    clock.t = 1000 + 301
    assert not s.is_fresh()


def test_sampler_seeds_latest_from_store(store):
    store.insert(500, 19.0, 45.0)
    s = Sampler(StubSensor(), store)
    assert (s.latest.ts, s.latest.temp_c) == (500, 19.0)


# --- app --------------------------------------------------------------------

def make_client(store, results=((19.5, 40.25),), t=10_000_000):
    clock = Clock(t)
    s = Sampler(StubSensor(*results), store, clock_ok=lambda: True, now=clock)
    app = temperature.create_app(store, s, now=clock)
    return app.test_client(), s, clock


def test_metrics_serves_latest(store):
    client, s, _ = make_client(store)
    s.run_once()
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "pi_temperature 19.5" in body
    assert "pi_humidity 40.25" in body


def test_metrics_503_without_reading(store):
    client, _, _ = make_client(store)
    assert client.get("/metrics").status_code == 503


def test_metrics_503_when_stale(store):
    client, s, clock = make_client(store)
    s.run_once()
    clock.t += 600
    assert client.get("/metrics").status_code == 503


def test_api_current(store):
    client, s, _ = make_client(store)
    assert client.get("/api/current").status_code == 503
    s.run_once()
    data = client.get("/api/current").get_json()
    assert data == {"ts": 10_000_000, "temp_c": 19.5, "humidity": 40.25, "fresh": True}


def test_api_history_24h_raw(store):
    t = 10_000_000
    store.insert_many([(t - 90000, 1.0, 1.0), (t - 600, 20.0, 50.0), (t - 60, 21.0, 51.0)])
    client, _, _ = make_client(store, t=t)
    data = client.get("/api/history?range=24h").get_json()
    assert data["fields"] == ["ts", "temp_c", "humidity"]
    assert data["points"] == [[t - 600, 20.0, 50.0], [t - 60, 21.0, 51.0]]


def test_api_history_30d_hourly(store):
    t = 3600 * 3000
    store.insert_many([(t - 7200, 20.0, 50.0), (t - 7140, 22.0, 52.0), (t - 60, 21.0, 51.0)])
    client, _, _ = make_client(store, t=t)
    data = client.get("/api/history?range=30d").get_json()
    assert data["fields"][0:4] == ["ts", "temp_avg", "temp_min", "temp_max"]
    assert data["points"] == [
        [t - 7200, 21.0, 20.0, 22.0, 51.0, 50.0, 52.0],
        [t - 3600, 21.0, 21.0, 21.0, 51.0, 51.0, 51.0],
    ]


def test_api_history_rejects_bad_range(store):
    client, _, _ = make_client(store)
    assert client.get("/api/history?range=7y").status_code == 400


def test_index_serves_page(store):
    client, _, _ = make_client(store)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"<html" in resp.data.lower()
