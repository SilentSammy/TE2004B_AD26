"""Zumo hardware endpoint; application/navigation logic belongs on the Pico W."""
import struct
import time
from machine import Pin, UART, ADC
from zumo_2040_robot import robot
import hw_protocol as p

BAUD = 921600
MOTOR_TIMEOUT_MS = 250


class HardwareServer:
    def __init__(self, uart=None):
        self.motors = robot.Motors()
        self.motors.off()
        self.speeds = (0, 0)
        self.last_motor_ms = time.ticks_ms()
        self.watchdog_stops = 0
        self.uart = uart or UART(0, BAUD, tx=Pin(28), rx=Pin(29), rxbuf=2048, txbuf=1024, timeout=0, timeout_char=1)
        self.parser = p.Parser()
        self.last_rx_ms = time.ticks_ms()
        self.encoders = robot.Encoders()
        self.imu = robot.IMU()
        self.imu.reset()
        self.imu.enable_default()
        self.imu.acc.set_output_data_rate(208)
        self.imu.gyro.set_output_data_rate(208)
        self.imu.mag.set_output_data_rate(80)
        self.lines = robot.LineSensors()
        self.proximity = robot.ProximitySensors()
        self.battery = robot.Battery()
        self.buttons = (robot.ButtonA(), robot.ButtonB(), robot.ButtonC())
        self.yellow = robot.YellowLED()
        self.buzzer = None
        self.display = None
        self.stream_interval = 0
        self.stream_mask = p.FAST
        self.next_stream = time.ticks_us()
        self.stream_sequence = 0
        self.sample_count = 0
        if self.uart.any():
            self.uart.read(self.uart.any())

    def stop(self):
        self.motors.off()
        self.speeds = (0, 0)

    @p.native
    def watchdog(self):
        if self.speeds != (0, 0) and time.ticks_diff(time.ticks_ms(), self.last_motor_ms) >= MOTOR_TIMEOUT_MS:
            self.stop()
            self.watchdog_stops = (self.watchdog_stops + 1) & 0xffff

    @p.native
    def send(self, op, seq, payload=b''):
        data = p.frame(op, seq, payload)
        offset = 0
        deadline = time.ticks_add(time.ticks_ms(), 30)
        while offset < len(data):
            offset += self.uart.write(memoryview(data)[offset:]) or 0
            if time.ticks_diff(time.ticks_ms(), deadline) >= 0:
                raise OSError('UART transmit timeout')

    def snapshot(self, mask):
        start = time.ticks_us()
        counts, imu, lines, prox = (0, 0), [0] * 9, [0] * 5, [0] * 6
        battery = buttons = 0
        if mask & p.BATTERY:
            # Sample before driving the downward emitters on this shared pin.
            # Immediately after an emitter pulse, the divider has not settled.
            self.battery.adc = ADC(Pin(26))
            battery = self.battery.get_level_millivolts()
        if mask & p.CORE:
            counts = self.encoders.get_counts()
            # Read raw register vectors; conversion happens on the Pico W.
            # Avoid calculating nine unused software floating-point values here.
            imu = (self.imu.acc._read_axes_s16(0x28) +
                   self.imu.gyro._read_axes_s16(0x22) +
                   self.imu.mag._read_axes_s16(0x28))
        if mask & p.LINE:
            lines = self.lines.read()
        if mask & p.PROXIMITY:
            self.proximity.read()
            prox = [value for pair in self.proximity.counts for value in pair]
        if mask & p.BUTTONS:
            buttons = sum((1 << i) for i, button in enumerate(self.buttons) if button.is_pressed())
        self.sample_count = (self.sample_count + 1) & 0xffff
        self.watchdog()
        values = [start & 0xffffffff, time.ticks_diff(time.ticks_us(), start), counts[0], counts[1]]
        values.extend(imu)
        values.extend(lines)
        values.extend(prox)
        values.extend([battery, buttons, self.speeds[0], self.speeds[1], mask, self.watchdog_stops, self.sample_count])
        return struct.pack(p.SNAPSHOT_FORMAT, *values)

    def dispatch(self, op, seq, data):
        try:
            reply = b''
            if op == p.PING and not data:
                reply = struct.pack('<IIHH', BAUD, MOTOR_TIMEOUT_MS, p.ALL, p.SNAPSHOT_SIZE)
            elif op == p.READ and len(data) == 2:
                mask = struct.unpack('<H', data)[0]
                if mask & ~p.ALL:
                    raise ValueError('unknown sensor mask')
                reply = self.snapshot(mask)
            elif op == p.MOTORS and len(data) == 4:
                speeds = struct.unpack('<hh', data)
                if any(abs(s) > 6000 for s in speeds):
                    raise ValueError('motor PWM outside -6000..6000')
                if self.buttons[0].is_pressed() and speeds != (0, 0):
                    self.stop()
                    raise ValueError('button A emergency stop held')
                self.motors.set_speeds(*speeds)
                self.speeds = speeds
                self.last_motor_ms = time.ticks_ms()
                reply = data
            elif op == p.RESET_ENCODERS and not data:
                self.encoders.get_counts(reset=True)
            elif op == p.STREAM and len(data) == 4:
                hz, mask = struct.unpack('<HH', data)
                if hz > 100 or mask & ~p.ALL:
                    raise ValueError('stream rate 0..100, valid sensor mask required')
                self.stream_interval = 1000000 // hz if hz else 0
                self.stream_mask = mask
                self.next_stream = time.ticks_add(time.ticks_us(), self.stream_interval)
            elif op == p.HEARTBEAT and not data:
                # Reading/pinging deliberately cannot keep stale motor PWM alive.
                reply = struct.pack('<HHH', self.watchdog_stops, self.parser.bad_crc & 0xffff, self.parser.bad_header & 0xffff)
            elif op == p.LED and len(data) == 1:
                self.yellow.value(bool(data[0]))
            elif op == p.BUZZER and len(data) <= 96:
                if self.buzzer is None:
                    self.buzzer = robot.Buzzer()
                if data:
                    self.buzzer.play_in_background(data.decode())
                else:
                    self.buzzer.off()
            elif op == p.DISPLAY and len(data) <= 96:
                if self.display is None:
                    self.display = robot.Display()
                self.display.fill(0)
                for i, line in enumerate(data.decode().split('\n')[:6]):
                    self.display.text(line[:16], 0, i * 10)
                self.display.show()
            else:
                raise ValueError('unknown command or invalid payload length')
            self.send(op | 0x80, seq, reply)
        except Exception as error:
            self.stop()
            self.send(p.ERROR, seq, str(error).encode()[:p.MAX_PAYLOAD])

    def run(self):
        print('ZUMO_HARDWARE_READY baud={} tx=28 rx=29'.format(BAUD))
        try:
            while True:
                self.watchdog()
                if self.buttons[0].is_pressed():
                    self.stop()
                if self.uart.any():
                    self.parser.feed(self.uart.read(min(self.uart.any(), 512)))
                    self.last_rx_ms = time.ticks_ms()
                elif self.parser.buffer and time.ticks_diff(time.ticks_ms(), self.last_rx_ms) > 20:
                    # A truncated frame cannot hold the parser indefinitely.
                    self.parser.buffer = b''
                    self.parser.bad_header += 1
                for _ in range(8):
                    message = self.parser.pop()
                    if message is None:
                        break
                    self.dispatch(*message)
                    self.watchdog()
                now = time.ticks_us()
                if self.stream_interval and time.ticks_diff(now, self.next_stream) >= 0:
                    self.stream_sequence = (self.stream_sequence + 1) & 0xffff
                    payload = self.snapshot(self.stream_mask)
                    self.send(p.STREAM_DATA, self.stream_sequence, payload)
                    self.next_stream = time.ticks_add(self.next_stream, self.stream_interval)
                    late = time.ticks_diff(time.ticks_us(), self.next_stream)
                    # Keep the phase after short GC pauses, rather than adding
                    # another full interval and losing rate on every pause.
                    # Skip missed periods when over a complete interval late.
                    if late >= self.stream_interval:
                        self.next_stream = time.ticks_add(self.next_stream, (late // self.stream_interval + 1) * self.stream_interval)
                time.sleep_us(100)
        finally:
            self.stop()
            self.proximity.ir_pulses.off()
            if self.buzzer:
                self.buzzer.off()


def main():
    server = None
    try:
        server = HardwareServer()
        server.run()
    finally:
        if server:
            server.stop()
        else:
            robot.Motors().off()
