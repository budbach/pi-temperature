import time
import Adafruit_DHT

from flask import Flask

dht_device = Adafruit_DHT.DHT22
pin = 14

app = Flask(__name__)

@app.route("/metrics")
def metrics():
    data = []
    retries = 3
    while retries > 0:
        retries -= 1
        humidity, temperature = Adafruit_DHT.read_retry(dht_device, pin)
        if humidity and temperature:
            data.append(f'pi_temperature {temperature}')
            data.append(f'pi_humidity {humidity}')
            break
        app.logger.error('Incomplete data from DHT Device')
        time.sleep(2)
        
    app.logger.info(", ".join(data))

    return "\n".join(data), 200, {'Content-Type': 'text/plain; charset=utf-8'}

if __name__ == "__main__":
    app.run(host='0.0.0.0')
