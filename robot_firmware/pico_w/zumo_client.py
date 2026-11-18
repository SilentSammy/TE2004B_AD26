"""MicroPython UART client for the Zumo hardware server; no Wi-Fi dependency."""
import struct
import time
from machine import UART, Pin
import hw_protocol as p


def decode_snapshot(data):
    if len(data) != p.SNAPSHOT_SIZE:
        raise ValueError('invalid snapshot size')
    v = struct.unpack(p.SNAPSHOT_FORMAT, data)
    return dict(timestamp_us=v[0], sample_us=v[1], encoders=(v[2], v[3]),
                acceleration_g=tuple(x * 0.000061 for x in v[4:7]),
                gyro_dps=tuple(x * 0.07 for x in v[7:10]),
                magnetic_gauss=tuple(x / 6842.0 for x in v[10:13]),
                imu_raw=v[4:13], line=v[13:18], proximity=(v[18:20], v[20:22], v[22:24]),
                battery_mv=v[24], buttons=v[25], motor_pwm=(v[26], v[27]),
                valid_mask=v[28], watchdog_stops=v[29], sample_sequence=v[30])


class Zumo:
    def __init__(self, uart=None, uart_id=0, tx=0, rx=1, baud=921600, timeout_ms=100):
        self.uart = uart or UART(uart_id, baud, tx=Pin(tx), rx=Pin(rx), rxbuf=4096, txbuf=1024, timeout=0, timeout_char=1)
        self.timeout_ms = timeout_ms
        self.sequence = 0
        self.parser = p.Parser()
        self.last_rx_ms = time.ticks_ms()
        self.latest = None
        self.latest_sequence = None
        self.latest_received_us = None
        self.stream_packets = 0
        self.stream_missing = 0
        if self.uart.any():
            self.uart.read(self.uart.any())

    @p.native
    def _write(self, data):
        offset = 0
        deadline = time.ticks_add(time.ticks_ms(), self.timeout_ms)
        while offset < len(data):
            offset += self.uart.write(memoryview(data)[offset:]) or 0
            if time.ticks_diff(time.ticks_ms(), deadline) >= 0:
                raise OSError('UART transmit timeout')

    @p.native
    def poll(self, expected=None):
        if self.uart.any():
            self.parser.feed(self.uart.read(min(self.uart.any(), 1024)))
            self.last_rx_ms = time.ticks_ms()
        elif self.parser.buffer and time.ticks_diff(time.ticks_ms(), self.last_rx_ms) > 20:
            self.parser.buffer = b''
            self.parser.bad_header += 1
        reply = None
        while True:
            message = self.parser.pop()
            if message is None:
                break
            op, seq, payload = message
            if op == p.STREAM_DATA:
                if self.latest_sequence is not None:
                    self.stream_missing += max(0, ((seq - self.latest_sequence) & 0xffff) - 1)
                self.latest_sequence = seq
                self.stream_packets += 1
                self.latest = decode_snapshot(payload)
                self.latest_received_us = time.ticks_us()
            elif expected is not None and seq == expected:
                reply = message
        return reply

    @p.native
    def request(self, op, payload=b''):
        self.sequence = (self.sequence + 1) & 0xffff
        self.poll()
        self._write(p.frame(op, self.sequence, payload))
        deadline = time.ticks_add(time.ticks_ms(), self.timeout_ms)
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            reply = self.poll(expected=self.sequence)
            if reply:
                code, _, data = reply
                if code == p.ERROR:
                    raise ValueError('Zumo: ' + data.decode())
                if code != op | 0x80:
                    raise ValueError('unexpected reply opcode')
                return data
            time.sleep_us(50)
        raise OSError('Zumo UART reply timeout')

    def info(self):
        baud, watchdog, mask, size = struct.unpack('<IIHH', self.request(p.PING))
        return dict(baud=baud, motor_timeout_ms=watchdog, sensor_mask=mask, snapshot_bytes=size)

    def read_sensors(self, mask=p.FAST):
        return decode_snapshot(self.request(p.READ, struct.pack('<H', mask)))

    def read_raw(self, mask=p.FAST):
        """Return the 31-field wire tuple without float/dictionary conversions."""
        return struct.unpack(p.SNAPSHOT_FORMAT, self.request(p.READ, struct.pack('<H', mask)))

    def set_motor_speeds(self, left, right):
        """Pololu PWM units -6000..6000. Renew at least once every 250 ms."""
        if not -6000 <= left <= 6000 or not -6000 <= right <= 6000:
            raise ValueError('motor PWM outside -6000..6000')
        return struct.unpack('<hh', self.request(p.MOTORS, struct.pack('<hh', round(left), round(right))))

    def stop(self):
        return self.set_motor_speeds(0, 0)

    def reset_encoders(self):
        self.request(p.RESET_ENCODERS)

    def stream(self, hz=100, mask=p.FAST):
        """Request push snapshots; call poll() frequently to keep the latest."""
        self.request(p.STREAM, struct.pack('<HH', hz, mask))
        if hz:
            self.latest_sequence = None
            self.stream_packets = self.stream_missing = 0

    def status(self):
        stops, crc, headers = struct.unpack('<HHH', self.request(p.HEARTBEAT))
        return dict(watchdog_stops=stops, server_crc_errors=crc, server_header_errors=headers,
                    client_crc_errors=self.parser.bad_crc)

    def led(self, on):
        self.request(p.LED, bytes([bool(on)]))

    def buzzer(self, notes=''):
        self.request(p.BUZZER, notes.encode())

    def display(self, text):
        self.request(p.DISPLAY, text.encode())

    def close(self):
        try:
            self.stop()
            self.stream(0)
        finally:
            self.uart.deinit()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
