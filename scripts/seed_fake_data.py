"""Fill a database with synthetic readings, for working on the page locally.

    DB_PATH=/tmp/fake.db uv run scripts/seed_fake_data.py [days]

Writes one reading a minute for the last `days` days (default 90), with a
few gaps so the chart's gap handling can be seen.
"""

import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sensor import fake_reading  # noqa: E402
from store import Store  # noqa: E402


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    path = os.environ.get("DB_PATH")
    if not path:
        sys.exit("set DB_PATH to the database to fill (it won't touch the default)")
    store = Store(path)
    rng = random.Random(42)
    now = int(time.time()) // 60 * 60
    start = now - days * 86400
    gaps = [(now - 3 * 86400, now - 3 * 86400 + 5400), (now - 40 * 86400, now - 38 * 86400)]
    rows = []
    for ts in range(start, now, 60):
        if any(a <= ts < b for a, b in gaps):
            continue
        t, h = fake_reading(ts, rng)
        rows.append((ts, t, h))
    store.insert_many(rows)
    print(f"wrote {len(rows)} readings to {path}")


if __name__ == "__main__":
    main()
