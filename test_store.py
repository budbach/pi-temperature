import pytest

from store import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "sub" / "readings.db")


def test_creates_parent_directory(tmp_path):
    Store(tmp_path / "a" / "b" / "r.db")
    assert (tmp_path / "a" / "b" / "r.db").exists()


def test_empty(store):
    assert store.latest() is None
    assert store.raw(0) == []
    assert store.hourly(0) == []


def test_insert_and_latest(store):
    store.insert(100, 20.0, 50.0)
    store.insert(160, 21.0, 51.0)
    assert store.latest() == (160, 21.0, 51.0)


def test_raw_window_is_inclusive_and_ordered(store):
    store.insert_many([(300, 3.0, 30.0), (100, 1.0, 10.0), (200, 2.0, 20.0)])
    assert store.raw(200) == [(200, 2.0, 20.0), (300, 3.0, 30.0)]


def test_hourly_buckets(store):
    h = 3600 * 1000  # an arbitrary whole UTC hour
    store.insert_many(
        [
            (h + 0, 20.0, 50.0),
            (h + 60, 22.0, 54.0),
            (h + 3599, 24.0, 52.0),
            (h + 3600, 10.0, 40.0),  # next hour, partial
        ]
    )
    rows = store.hourly(h + 1800)  # mid-hour start still includes that hour
    assert rows == [
        (h, 22.0, 20.0, 24.0, 52.0, 50.0, 54.0),
        (h + 3600, 10.0, 10.0, 10.0, 40.0, 40.0, 40.0),
    ]


def test_hourly_excludes_earlier_hours(store):
    h = 3600 * 1000
    store.insert_many([(h - 1, 1.0, 1.0), (h, 2.0, 2.0)])
    assert [r[0] for r in store.hourly(h)] == [h]


def test_insert_same_ts_replaces(store):
    store.insert(100, 20.0, 50.0)
    store.insert(100, 21.0, 51.0)
    assert store.raw(0) == [(100, 21.0, 51.0)]
