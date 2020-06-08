import time
import board
import adafruit_dht
from flask import Flask

dht_device = adafruit_dht.DHT22(board.D14)

app = Flask(__name__)

@app.route("/metrics")
def metrics():
    data = []
    while len(data) != 2:
        try:
            data.append(f'pi_temperature {dht_device.temperature}')
            data.append(f'pi_humidity {dht_device.humidity}')
        except Exception as e:
            app.logger.error(e)
            data = []
            time.sleep(2)
        
    app.logger.info(", ".join(data))

    return "\n".join(data), 200, {'Content-Type': 'text/plain; charset=utf-8'}

if __name__ == "__main__":
    app.run(host='0.0.0.0')
