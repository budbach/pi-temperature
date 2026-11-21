import sqlite3

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


# --- hourly summary table ----------------------------------------------------

H = 3600 * 1000  # an arbitrary whole UTC hour


def brute_force_hourly(store, since=0):
    """What the summary should contain, computed straight from raw rows."""
    with sqlite3.connect(store.path) as db:
        return db.execute(
            """
            SELECT (ts / 3600) * 3600 AS hour,
                   ROUND(AVG(temp_c), 2), MIN(temp_c), MAX(temp_c),
                   ROUND(AVG(humidity), 2), MIN(humidity), MAX(humidity)
            FROM readings WHERE ts >= ? GROUP BY hour ORDER BY hour
            """,
            (since,),
        ).fetchall()


def test_summary_tracks_single_inserts(store):
    for i, ts in enumerate(range(H, H + 3 * 3600, 60)):
        store.insert(ts, 20 + (i % 7) * 0.1, 50 + (i % 5) * 0.3)
    assert store.hourly(0) == brute_force_hourly(store)
    assert len(store.hourly(0)) == 3


def test_summary_is_exact_when_a_reading_is_replaced(store):
    store.insert(H, 20.0, 50.0)
    store.insert(H + 60, 22.0, 52.0)
    store.insert(H + 60, 30.0, 60.0)  # same ts: replaces, must not double count
    assert store.hourly(0) == [(H, 25.0, 20.0, 30.0, 55.0, 50.0, 60.0)]


def test_summary_tracks_bulk_inserts(store):
    rows = [(H + i * 60, 20 + (i % 9) * 0.1, 40 + (i % 4)) for i in range(500)]
    store.insert_many(rows)
    assert store.hourly(0) == brute_force_hourly(store)


def test_summary_rebuilt_on_startup_after_manual_delete(tmp_path):
    path = tmp_path / "r.db"
    s = Store(path)
    s.insert_many([(H + i * 60, 20.0 + i, 50.0) for i in range(120)])
    with sqlite3.connect(path) as db:  # e.g. pruning bad readings by hand
        db.execute("DELETE FROM readings WHERE ts < ?", (H + 3600 + 600,))
    s2 = Store(path)
    assert s2.hourly(0) == brute_force_hourly(s2)
    assert [r[0] for r in s2.hourly(0)] == [H + 3600]


def test_summary_built_for_existing_database(tmp_path):
    # A database created before the summary table existed.
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE readings (ts INTEGER PRIMARY KEY, temp_c REAL NOT NULL,"
                   " humidity REAL NOT NULL)")
        db.executemany("INSERT INTO readings VALUES (?, ?, ?)",
                       [(H + i * 60, 18.0, 45.0) for i in range(90)])
    s = Store(path)
    assert s.hourly(0) == brute_force_hourly(s)
    assert len(s.hourly(0)) == 2
