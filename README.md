# aqi
Measure AQI based on PM2.5 or PM10 with a Raspberry Pi and a SDS011 particle sensor

# Installation for a Raspberry PI:

sudo apt update && apt install python2 python-gpiozero lighttpd -y

curl https://bootstrap.pypa.io/pip/2.7/get-pip.py --output get-pip.py

python2 get-pip.py

python2 -m pip install pyserial

python2 -m pip install colorzero

python2 -m pip install rpi.gpio
