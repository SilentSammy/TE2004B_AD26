"""100 Hz hardware loop on the Pico W. This example holds motors at zero."""
import time
import hw_protocol as p
from zumo_client import Zumo

with Zumo() as car:
    print(car.info())
    car.stream(100, p.FAST)
    deadline = time.ticks_us()
    last_print = time.ticks_ms()
    while True:
        car.poll()
        sample = car.latest
        # Place sensor fusion/navigation here. Reject old data before moving.
        fresh = (sample is not None and
                 time.ticks_diff(time.ticks_us(), car.latest_received_us) < 50000)
        left, right = 0, 0
        if not fresh:
            left, right = 0, 0
        car.set_motor_speeds(left, right)
        if sample and time.ticks_diff(time.ticks_ms(), last_print) >= 1000:
            print(sample['encoders'], sample['acceleration_g'], sample['battery_mv'])
            last_print = time.ticks_ms()
        deadline = time.ticks_add(deadline, 10000)
        remaining = time.ticks_diff(deadline, time.ticks_us())
        if remaining > 0:
            time.sleep_us(remaining)
        else:
            deadline = time.ticks_us()
