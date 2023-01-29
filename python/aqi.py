#!/usr/bin/python -u
# coding=utf-8
# "DATASHEET": http://cl.ly/ekot
# https://gist.github.com/kadamski/92653913a53baf9dd1a8
from __future__ import print_function
import serial, struct, time, json, subprocess, signal
from gpiozero import Button
from gpiozero import LED

Warnled = LED(23)
Door = Button(18)

DEBUG = 0
CMD_MODE = 2
CMD_QUERY_DATA = 4
CMD_DEVICE_ID = 5
CMD_SLEEP = 6
CMD_FIRMWARE = 7
CMD_WORKING_PERIOD = 8
MODE_ACTIVE = 0
MODE_QUERY = 1
PERIOD_CONTINUOUS = 0

JSON_FILE = '/var/www/html/aqi.json'
JSON_FILE_ALARM = '/var/www/html/aqialarm.json'
JSON_FILE_BACKUP = '/home/pi/aqi-backup.json'

MQTT_HOST = ''
MQTT_TOPIC = '/weather/particulatematter'

ser = serial.Serial()
ser.port = "/dev/ttyUSB0"
ser.baudrate = 9600

ser.open()
ser.flushInput()

byte, data = 0, ""

class GracefulKiller:
    kill_now = False
    def __init__(self):
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def exit_gracefully(self, *args):
        self.kill_now = True

def getLastAverage(anum):
    try:
        with open(JSON_FILE) as json_data:
            data = json.load(json_data)
    except IOError as e:
        data = []
        return(1000)
    #print(len(data))
    if(len(data) < anum):
        return(1000)
    #print(data[-1])
    #print(data[-2])
    #print(data[-3])
    #print(data[-4])

    #print(type(data))
    #print(type(data[-1]))

    #print(data[-1]["pm25"])

    sum = 0
    for num in range(-1, (-1 * anum) -1, -1):
        #print(data[num])
        #print(data[num]["pm25"])
        sum += data[num]["pm10"]
        #print(sum)
    average = sum / anum
    print("last " + str(anum) + " average 10pm : " + str(average))
    return(average)

def dump(d, prefix=''):
    print(prefix + ' '.join(x.encode('hex') for x in d))

def construct_command(cmd, data=[]):
    assert len(data) <= 12
    data += [0,]*(12-len(data))
    checksum = (sum(data)+cmd-2)%256
    ret = "\xaa\xb4" + chr(cmd)
    ret += ''.join(chr(x) for x in data)
    ret += "\xff\xff" + chr(checksum) + "\xab"

    if DEBUG:
        dump(ret, '> ')
    return ret

def process_data(d):
    r = struct.unpack('<HHxxBB', d[2:])
    pm25 = r[0]/10.0
    pm10 = r[1]/10.0
    checksum = sum(ord(v) for v in d[2:8])%256
    return [pm25, pm10]
    #print("PM 2.5: {} μg/m^3  PM 10: {} μg/m^3 CRC={}".format(pm25, pm10, "OK" if (checksum==r[2] and r[3]==0xab) else "NOK"))

def process_version(d):
    r = struct.unpack('<BBBHBB', d[3:])
    checksum = sum(ord(v) for v in d[2:8])%256
    print("Y: {}, M: {}, D: {}, ID: {}, CRC={}".format(r[0], r[1], r[2], hex(r[3]), "OK" if (checksum==r[4] and r[5]==0xab) else "NOK"))

def read_response():
    byte = 0
    while byte != "\xaa":
        byte = ser.read(size=1)

    d = ser.read(size=9)

    if DEBUG:
        dump(d, '< ')
    return byte + d

def cmd_set_mode(mode=MODE_QUERY):
    ser.write(construct_command(CMD_MODE, [0x1, mode]))
    read_response()

def cmd_query_data():
    ser.write(construct_command(CMD_QUERY_DATA))
    d = read_response()
    values = []
    if d[1] == "\xc0":
        values = process_data(d)
    return values

def cmd_set_sleep(sleep):
    mode = 0 if sleep else 1
    ser.write(construct_command(CMD_SLEEP, [0x1, mode]))
    read_response()

def cmd_set_working_period(period):
    ser.write(construct_command(CMD_WORKING_PERIOD, [0x1, period]))
    read_response()

def cmd_firmware_ver():
    ser.write(construct_command(CMD_FIRMWARE))
    d = read_response()
    process_version(d)

def cmd_set_id(id):
    id_h = (id>>8) % 256
    id_l = id % 256
    ser.write(construct_command(CMD_DEVICE_ID, [0]*10+[id_l, id_h]))
    read_response()

def pub_mqtt(jsonrow):
    cmd = ['mosquitto_pub', '-h', MQTT_HOST, '-t', MQTT_TOPIC, '-s']
    print('Publishing using:', cmd)
    with subprocess.Popen(cmd, shell=False, bufsize=0, stdin=subprocess.PIPE).stdin as f:
        json.dump(jsonrow, f)


if __name__ == "__main__":
    killer = GracefulKiller()
    cmd_set_sleep(0)
    cmd_firmware_ver()
    cmd_set_working_period(PERIOD_CONTINUOUS)
    cmd_set_mode(MODE_QUERY)

    lastalarmepoch = 0

    while not killer.kill_now:
        cmd_set_sleep(0)
        pm10Average = getLastAverage(20)
        isalarm = False
        isSmoke = False
        maxpm25 = 0
        maxpm10 = 0
        valuepm10 = 0
        valuepm25 = 0

        HumidityModifier = 1

        #get current humidity values
        subprocess.call(["python3", "DHT.py", "2"])
        for t in range(40):
            values = cmd_query_data()
            valuepm25 = values[0]
            valuepm10 = values[1]
            if values is not None and len(values) == 2:
                print("PM2.5: ", valuepm25, ", PM10: ", valuepm10)
                if maxpm25 < valuepm25:
                    maxpm25 = valuepm25
                if maxpm10 < valuepm10:
                    maxpm10 = valuepm10
                if valuepm10 > (pm10Average + (15 * HumidityModifier)):
                    #get current humidity values
                    subprocess.call(["python3", "DHT.py", "2"])
                    f = open("/tmp/aqihumidity", "r")
                    humidity = f.readline()
                    f.close()

                    print("Humidity Modifer is now: " + str(HumidityModifier))

                    if humidity > 50:
                        HumidityModifier = 1.5
                    if humidity > 60:
                        HumidityModifier = 2
                    if humidity > 65:
                        HumidityModifier = 2.5
                    if humidity > 70:
                        HumidityModifier = 3
                    if humidity > 75:
                        HumidityModifier = 3.5
                    if humidity > 80:
                        HumidityModifier = 4

                    isSmoke = True
                    if not isalarm:
                        currentepoch = int(time.time())
                        if currentepoch - lastalarmepoch > (5*60):
                            subprocess.call(["amixer", "sset", "Headphone", "100%"])
                            subprocess.call(["mpg123", "/home/pi/alarm2.mp3"])
                        lastalarmepoch = int(time.time())
                        subprocess.call(["amixer", "sset", "Headphone", "85%"])
                    Warnled.blink(120,0,1)
                    if not Door.is_pressed:
                        isalarm = True
                        print("Smoke Alarm")
                        subprocess.call(["mpg123", "/home/pi/alarm1.mp3"])
                        subprocess.call(["amixer", "sset", "Headphone", "5dB+"])
                time.sleep(2)
            if killer.kill_now:
                break

        if killer.kill_now:
            break

        f = open("/tmp/aqihumidity", "r")
        humidity = f.readline()
        f.close()

        f = open("/tmp/aqitemp", "r")
        temp = f.readline()
        f.close()

        # open stored data
        try:
            with open(JSON_FILE) as json_data:
                data = json.load(json_data)
        except IOError as e:
            data = []

        # check if length is more than 10000 and delete first element
        if len(data) > 10000:
            data.pop(0)

        # append new values
        jsonrow = {'humidity': humidity, 'temp': temp, 'smoke': isSmoke, 'alarm' : isalarm, 'pm25': maxpm25, 'pm10': maxpm10, 'time': time.strftime("%d.%m.%Y %H:%M:%S")}
        data.append(jsonrow)

        # save it
        with open(JSON_FILE, 'w') as outfile:
            json.dump(data, outfile)

        if MQTT_HOST != '':
            pub_mqtt(jsonrow)

        if isSmoke:
            # open stored data
            try:
                with open(JSON_FILE_ALARM) as json_data:
                    data = json.load(json_data)
            except IOError as e:
                data = []

            # append new values
            jsonrow = {'smoke': isSmoke, 'alarm' : isalarm, 'epoch' : int(time.time()),'time': time.strftime("%d.%m.%Y %H:%M:%S")}
            data.append(jsonrow)

            # save it
            with open(JSON_FILE_ALARM, 'w') as outfile:
                json.dump(data, outfile)

        #subprocess.call(["cp", JSON_FILE, JSON_FILE_BACKUP])
        cmd_set_sleep(1)
        if not killer.kill_now:
            print("Going to sleep for 10 seconds...")
            time.sleep(10)

    print("End of the program. I was killed gracefully :)")
