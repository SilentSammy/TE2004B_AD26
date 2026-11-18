"""Non-moving corruption/recovery and range-check test on the real UART."""
import time
import struct
from zumo_client import Zumo
import hw_protocol as p

car = Zumo()
try:
    car.stop()
    before = car.status()['server_crc_errors']
    bad = bytearray(p.frame(p.MOTORS, 123, struct.pack('<hh', 1200, 1200)))
    bad[-1] ^= 1
    car.uart.write(b'garbage' + bad)
    time.sleep_ms(30)
    assert car.info()['baud'] == 921600
    assert car.status()['server_crc_errors'] == before + 1
    assert car.read_sensors(p.CORE)['motor_pwm'] == (0, 0)
    # A header cut off mid-payload must expire without poisoning later requests.
    car.uart.write(p.frame(p.READ, 124, b'x' * 100)[:12])
    time.sleep_ms(35)
    assert car.info()['baud'] == 921600
    try:
        car.request(p.MOTORS, struct.pack('<hh', 6001, 0))
        raise AssertionError('server accepted invalid motor PWM')
    except ValueError:
        pass
    print('PROTOCOL_RECOVERY_PASS', car.status())
finally:
    car.close()
