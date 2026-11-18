"""Explicit powered test: raise both tracks before running this file."""
import time
from zumo_client import Zumo
import hw_protocol as p

car = Zumo()
try:
    car.stream(0)
    car.stop()
    car.reset_encoders()
    for left, right in ((1200, 0), (0, 1200), (-1200, -1200)):
        print('MOTOR_ACK', car.set_motor_speeds(left, right))
        time.sleep_ms(80)
        car.stop()
        print('ENCODERS', car.read_sensors(p.CORE)['encoders'])
        time.sleep_ms(100)
    previous = car.status()['watchdog_stops']
    car.set_motor_speeds(1200, 1200)
    time.sleep_ms(350)
    snapshot = car.read_sensors(p.CORE)
    print('WATCHDOG', snapshot['motor_pwm'], snapshot['watchdog_stops'])
    assert snapshot['motor_pwm'] == (0, 0), 'motors failed to stop'
    assert snapshot['watchdog_stops'] == ((previous + 1) & 0xffff), 'watchdog failed to trip'
    car.led(True)
    time.sleep_ms(100)
    car.led(False)
    car.display('Zumo hardware\nUART 921600\nReady')
    car.buzzer('L16O5c')
    time.sleep_ms(150)
    car.buzzer()
    print('MOTOR_AND_WATCHDOG_TEST_PASS')
finally:
    car.close()
