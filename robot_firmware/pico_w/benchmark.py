"""Run on the Pico W after starting the Zumo server. Never drives the motors."""
import time
import gc
import json
import hw_protocol as p
from zumo_client import Zumo


def summary(values):
    values = sorted(values)
    return dict(min=values[0], mean=sum(values) / len(values),
                p95=values[int((len(values) - 1) * .95)], max=values[-1])


car = Zumo(timeout_ms=200)
try:
    print('INFO', car.info())
    car.stream(0)
    car.stop()
    print('SAMPLE', car.read_sensors(p.ALL))
    for name, mask, hz in [('fast', p.FAST, 100), ('all', p.ALL, 50)]:
        gc.collect()
        rtts, samples = [], []
        start = time.ticks_us()
        deadline = start
        for i in range(200):
            now = time.ticks_us()
            remaining = time.ticks_diff(deadline, now)
            if remaining > 0:
                time.sleep_us(remaining)
            t = time.ticks_us()
            snapshot = car.read_sensors(mask)
            rtts.append(time.ticks_diff(time.ticks_us(), t))
            samples.append(snapshot['sample_us'])
            deadline = time.ticks_add(deadline, 1000000 // hz)
        elapsed = time.ticks_diff(time.ticks_us(), start)
        print('REQUEST', json.dumps(dict(profile=name, target_hz=hz, achieved_hz=200000000 / elapsed,
                                          rtt_us=summary(rtts), sampling_us=summary(samples))))
    for name, mask, hz in [('fast', p.FAST, 100), ('all', p.ALL, 50)]:
        gc.collect()
        car.stream(hz, mask)
        start = time.ticks_ms()
        gaps = []
        previous = None
        while time.ticks_diff(time.ticks_ms(), start) < 4000:
            old = car.stream_packets
            car.poll()
            if car.stream_packets != old:
                if previous is not None:
                    gaps.append(time.ticks_diff(car.latest_received_us, previous))
                previous = car.latest_received_us
            time.sleep_us(100)
        received, missing = car.stream_packets, car.stream_missing
        car.stream(0)
        print('STREAM', json.dumps(dict(profile=name, target_hz=hz, received=received,
                                         missing=missing, gap_us=summary(gaps))))
    print('STATUS', car.status())
finally:
    car.close()
