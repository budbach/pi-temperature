## Pi Temperature

Simple web app that gets the temperature from a dht22 on a raspberry pi in a format suitable for querying with prometheus

Requires python3.

## Setup

Install CircuitPython:  https://learn.adafruit.com/circuitpython-on-raspberrypi-linux/installing-circuitpython-on-raspberry-pi

Install libgpio2:  `sudo apt -y install libgpiod2`

Create a virtualenv:  `python3 -m venv venv`

Activate the virtualenv:  `source venv/bin/activete`

Install the requirements: `pip install -r requirements.txt

Run the app:  `python temperature.py`
