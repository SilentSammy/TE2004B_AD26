from zumo_2040_robot import robot
import time

proximity_sensors = robot.ProximitySensors()
display = robot.Display()
last_update = 0
count = 0

while True:
    start = time.ticks_us()
    proximity_sensors.read()
    stop = time.ticks_us()

    if time.ticks_diff(stop, last_update) > 1000000:
        last_update = stop
        display.fill_rect(0, 0, 128, 8, 0)
        display.text("{:.1f}ms".format(time.ticks_diff(stop, start) / 1000), 0, 0)
        count = 0

    readings = [
        proximity_sensors.left_counts_with_left_leds(),
        proximity_sensors.left_counts_with_right_leds(),
        0,
        proximity_sensors.front_counts_with_left_leds(),
        proximity_sensors.front_counts_with_right_leds(),
        0,
        proximity_sensors.right_counts_with_left_leds(),
        proximity_sensors.right_counts_with_right_leds(),
    ]

    # 64-40 = 24
    scale = 24/6

    display.fill_rect(0, 32, 128, 32, 0)

    for i, reading in enumerate(readings):
        display.fill_rect(18+i*12, 64-int(reading*scale), 8, int(reading*scale), 1)

    display.show()
