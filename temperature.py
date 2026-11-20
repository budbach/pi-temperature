"""DHT22 temperature dashboard and Prometheus exporter.

A background sampler reads the sensor once a minute and stores readings
in SQLite. This app serves:

    /              the dashboard page
    /api/current   the latest reading as JSON
    /api/history   ?range=24h (raw) or 30d / 90d (hourly avg/min/max)
    /metrics       the latest reading in Prometheus text format
"""

import logging
import os
import time
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

from sampler import Sampler
from sensor import make_sensor
from store import Store

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_DB = Path.home() / ".local/share/pi-temperature/readings.db"
RANGES = {"24h": 86400, "30d": 30 * 86400, "90d": 90 * 86400}
METRICS_HEADERS = {"Content-Type": "text/plain; version=0.0.4; charset=utf-8"}


def create_app(store: Store, sampler: Sampler, now=time.time) -> Flask:
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/api/current")
    def current():
        r = sampler.latest
        if r is None:
            return jsonify(error="no reading yet"), 503
        body = {"ts": r.ts, "temp_c": r.temp_c, "humidity": r.humidity,
                "fresh": sampler.is_fresh()}
        return jsonify(body), 200 if body["fresh"] else 503

    @app.get("/api/history")
    def history():
        rng = request.args.get("range", "24h")
        if rng not in RANGES:
            abort(400, f"range must be one of {', '.join(RANGES)}")
        since = int(now()) - RANGES[rng]
        if rng == "24h":
            points = [list(row) for row in store.raw(since)]
            fields = ["ts", "temp_c", "humidity"]
        else:
            points = [list(row) for row in store.hourly(since)]
            fields = ["ts", "temp_avg", "temp_min", "temp_max",
                      "hum_avg", "hum_min", "hum_max"]
        return jsonify(range=rng, fields=fields, points=points, now=int(now()))

    @app.get("/metrics")
    def metrics():
        r = sampler.latest
        if r is None or not sampler.is_fresh():
            return "# no recent sensor reading\n", 503, METRICS_HEADERS
        return format_metrics(r.temp_c, r.humidity), 200, METRICS_HEADERS

    return app


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


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    store = Store(os.environ.get("DB_PATH", DEFAULT_DB))
    sampler = Sampler(make_sensor(), store)
    sampler.start()
    app = create_app(store, sampler)

    from waitress import serve

    # One process, so there is only ever one sampler writing.
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), threads=4)


if __name__ == "__main__":
    main()
