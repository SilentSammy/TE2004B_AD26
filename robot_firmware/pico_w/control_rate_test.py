"""Measure continuous sensor streaming with zero-speed motor writes each tick."""
import time
import json
import hw_protocol as p
from zumo_client import Zumo

car = Zumo(timeout_ms=200)
try:
    for name, mask, hz in [('fast', p.FAST, 100), ('all', p.ALL, 50)]:
        car.stream(hz, mask)
        started = time.ticks_us()
        deadline = started
        commands = 0
        periods = []
        previous = None
        while time.ticks_diff(time.ticks_us(), started) < 4000000:
            remaining = time.ticks_diff(deadline, time.ticks_us())
            if remaining > 0:
                time.sleep_us(remaining)
            now = time.ticks_us()
            if previous is not None:
                periods.append(time.ticks_diff(now, previous))
            previous = now
            car.set_motor_speeds(0, 0)
            car.poll()
            commands += 1
            deadline = time.ticks_add(deadline, 1000000 // hz)
        elapsed = time.ticks_diff(time.ticks_us(), started)
        car.stream(0)
        print('CONTROL', json.dumps(dict(profile=name, motor_commands=commands,
                                          elapsed_ms=elapsed / 1000, command_hz=commands * 1000000 / elapsed,
                                          sensor_packets=car.stream_packets, missing=car.stream_missing,
                                          max_loop_gap_us=max(periods), crc_errors=car.parser.bad_crc)))
    print('STATUS', car.status())
finally:
    car.close()
