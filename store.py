"""SQLite storage for sensor readings.

One row per successful reading: Unix seconds (UTC), °C, % RH.

An `hourly` table keeps a running summary per UTC hour (count, sums, min,
max), so the 30- and 90-day views read a few thousand pre-computed rows
instead of aggregating hundreds of thousands of readings on every request.
Each insert recomputes its hour from the raw readings (at most ~60 rows),
so the summary stays exact even when a reading is replaced. On startup the
summary is rebuilt if it doesn't match the raw table (e.g. after rows were
deleted by hand).

A fresh connection is opened per call, so the store is safe to share
between the sampler thread and request threads.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    ts       INTEGER PRIMARY KEY,
    temp_c   REAL NOT NULL,
    humidity REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS hourly (
    hour  INTEGER PRIMARY KEY,
    n     INTEGER NOT NULL,
    t_sum REAL NOT NULL,
    t_min REAL NOT NULL,
    t_max REAL NOT NULL,
    h_sum REAL NOT NULL,
    h_min REAL NOT NULL,
    h_max REAL NOT NULL
);
"""

# Recompute the summary rows for every hour from `start` up to (not
# including) `end` from the raw readings. Hours with no readings left are
# removed by the DELETE.
REBUILD_SQL = """
DELETE FROM hourly WHERE hour >= :start AND hour < :end;
INSERT INTO hourly (hour, n, t_sum, t_min, t_max, h_sum, h_min, h_max)
SELECT (ts / 3600) * 3600, COUNT(*), SUM(temp_c), MIN(temp_c), MAX(temp_c),
       SUM(humidity), MIN(humidity), MAX(humidity)
FROM readings
WHERE ts >= :start AND ts < :end
GROUP BY ts / 3600;
"""


def _hour(ts: int) -> int:
    return int(ts) - int(ts) % 3600


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
            raw_n = db.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
            sum_n = db.execute("SELECT COALESCE(SUM(n), 0) FROM hourly").fetchone()[0]
            if raw_n != sum_n:
                self._rebuild(db, 0, 2**62)
            db.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    @staticmethod
    def _rebuild(db: sqlite3.Connection, start: int, end: int) -> None:
        for stmt in REBUILD_SQL.strip().split(";"):
            if stmt.strip():
                db.execute(stmt, {"start": start, "end": end})

    def insert(self, ts: int, temp_c: float, humidity: float) -> None:
        self.insert_many([(ts, temp_c, humidity)])

    def insert_many(self, rows) -> None:
        rows = [(int(ts), t, h) for ts, t, h in rows]
        if not rows:
            return
        with closing(self._connect()) as db:
            db.executemany(
                "INSERT OR REPLACE INTO readings (ts, temp_c, humidity) VALUES (?, ?, ?)",
                rows,
            )
            hours = sorted({_hour(ts) for ts, _, _ in rows})
            if len(hours) == 1:
                self._rebuild(db, hours[0], hours[0] + 3600)
            else:  # bulk load (e.g. seeding): one pass over the whole span
                self._rebuild(db, hours[0], hours[-1] + 3600)
            db.commit()

    def latest(self) -> tuple[int, float, float] | None:
        with closing(self._connect()) as db:
            return db.execute(
                "SELECT ts, temp_c, humidity FROM readings ORDER BY ts DESC LIMIT 1"
            ).fetchone()

    def raw(self, since: int) -> list[tuple[int, float, float]]:
        """Every reading at or after `since`, oldest first."""
        with closing(self._connect()) as db:
            return db.execute(
                "SELECT ts, temp_c, humidity FROM readings WHERE ts >= ? ORDER BY ts",
                (int(since),),
            ).fetchall()

    def hourly(self, since: int) -> list[tuple]:
        """Readings grouped by UTC hour, at or after the hour containing
        `since`, oldest first. The current partial hour is included.

        Each row: (hour_start, temp_avg, temp_min, temp_max,
                   hum_avg, hum_min, hum_max), averages rounded to 0.01.
        """
        with closing(self._connect()) as db:
            return db.execute(
                """
                SELECT hour, ROUND(t_sum / n, 2), t_min, t_max,
                       ROUND(h_sum / n, 2), h_min, h_max
                FROM hourly
                WHERE hour >= ?
                ORDER BY hour
                """,
                (_hour(since),),
            ).fetchall()
