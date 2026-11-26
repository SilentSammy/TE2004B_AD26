"""Small bounded binary UART protocol shared by the Zumo and its Pico W brain."""
import struct
import binascii
try:
    from micropython import native
except ImportError:
    def native(function):
        return function

MAGIC = b'\xa5\x5a'
VERSION = 1
MAX_PAYLOAD = 192
PING, READ, MOTORS, RESET_ENCODERS, STREAM, HEARTBEAT, LED, BUZZER, DISPLAY = range(1, 10)
STREAM_DATA, ERROR = 0x90, 0xff
CORE, LINE, PROXIMITY, BATTERY, BUTTONS = 1, 2, 4, 8, 16
FAST = CORE | LINE | BATTERY | BUTTONS
ALL = FAST | PROXIMITY
SNAPSHOT_FORMAT = '<IIii9h5H6BHHhhHHH'
SNAPSHOT_SIZE = struct.calcsize(SNAPSHOT_FORMAT)


def decode_snapshot(data):
    if len(data) != SNAPSHOT_SIZE:
        raise ValueError('invalid snapshot size')
    v = struct.unpack(SNAPSHOT_FORMAT, data)
    return dict(timestamp_us=v[0], sample_us=v[1], encoders=(v[2], v[3]),
                acceleration_g=tuple(x * 0.000061 for x in v[4:7]),
                gyro_dps=tuple(x * 0.07 for x in v[7:10]),
                magnetic_gauss=tuple(x / 6842.0 for x in v[10:13]),
                imu_raw=v[4:13], line=v[13:18], proximity=(v[18:20], v[20:22], v[22:24]),
                battery_mv=v[24], buttons=v[25], motor_pwm=(v[26], v[27]),
                valid_mask=v[28], watchdog_stops=v[29], sample_sequence=v[30])


@native
def frame(op, sequence, payload=b''):
    if len(payload) > MAX_PAYLOAD:
        raise ValueError('payload too long')
    body = struct.pack('<BBHH', VERSION, op, sequence & 0xffff, len(payload)) + payload
    return MAGIC + body + struct.pack('<I', binascii.crc32(body) & 0xffffffff)


class Parser:
    def __init__(self):
        self.buffer = b''
        self.bad_crc = 0
        self.bad_header = 0

    @native
    def feed(self, data):
        if data:
            self.buffer += data
            if len(self.buffer) > 2048:
                self.buffer = self.buffer[-512:]
                self.bad_header += 1

    @native
    def pop(self):
        b = self.buffer
        while len(b) >= 2:
            start = b.find(MAGIC)
            if start < 0:
                self.buffer = b[-1:]
                return None
            if start:
                b = b[start:]
                self.buffer = b
            if len(b) < 8:
                return None
            version, op, sequence, length = struct.unpack('<BBHH', b[2:8])
            if version != VERSION or length > MAX_PAYLOAD:
                self.bad_header += 1
                b = b[1:]
                self.buffer = b
                continue
            total = 12 + length
            if len(b) < total:
                return None
            if (binascii.crc32(b[2:8 + length]) & 0xffffffff) != struct.unpack('<I', b[8 + length:total])[0]:
                self.bad_crc += 1
                b = b[1:]
                self.buffer = b
                continue
            payload = bytes(b[8:8 + length])
            self.buffer = b[total:]
            return op, sequence, payload
        return None
