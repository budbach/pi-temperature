"""SQLite storage for sensor readings.

One row per successful reading: Unix seconds (UTC), °C, % RH.
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
)
"""


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(SCHEMA)
            db.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def insert(self, ts: int, temp_c: float, humidity: float) -> None:
        with closing(self._connect()) as db:
            db.execute(
                "INSERT OR REPLACE INTO readings (ts, temp_c, humidity) VALUES (?, ?, ?)",
                (int(ts), temp_c, humidity),
            )
            db.commit()

    def insert_many(self, rows) -> None:
        with closing(self._connect()) as db:
            db.executemany(
                "INSERT OR REPLACE INTO readings (ts, temp_c, humidity) VALUES (?, ?, ?)",
                rows,
            )
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
        start = int(since) - int(since) % 3600
        with closing(self._connect()) as db:
            return db.execute(
                """
                SELECT (ts / 3600) * 3600 AS hour,
                       ROUND(AVG(temp_c), 2), MIN(temp_c), MAX(temp_c),
                       ROUND(AVG(humidity), 2), MIN(humidity), MAX(humidity)
                FROM readings
                WHERE ts >= ?
                GROUP BY hour
                ORDER BY hour
                """,
                (start,),
            ).fetchall()
