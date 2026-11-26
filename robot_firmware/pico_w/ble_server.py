"""BLE control/sensors for the Zumo; optional Wi-Fi is only for ArUco telemetry."""
import bluetooth
import struct
import json
import time
from zumo_client import Zumo
import hw_protocol as p
import ble_protocol as bp


class BLEHardwareServer:
    def __init__(self, car, name='zumo1'):
        if not 1 <= len(name.encode()) <= 8:
            raise ValueError('BLE name must be 1..8 UTF-8 bytes')
        self.car = car
        self.car.stream(0)
        self.car.stop()
        self.ble = bluetooth.BLE()
        self.ble.active(True)
        self.ble.config(mtu=247, gap_name=name)
        service = bluetooth.UUID(bp.SERVICE_UUID)
        ((self.rx, self.tx),) = self.ble.gatts_register_services(((service, (
            (bluetooth.UUID(bp.RX_UUID), bluetooth.FLAG_WRITE | bluetooth.FLAG_WRITE_NO_RESPONSE),
            (bluetooth.UUID(bp.TX_UUID), bluetooth.FLAG_NOTIFY),)),))
        self.ble.gatts_set_buffer(self.rx, 1024, True)
        self.parser = p.Parser()
        self.conn = None
        self.notify_size = 20
        self.rx_pending = False
        self.stop_pending = False
        self.count_stop = False
        self.advertise_pending = True
        self.tx_queue = []
        self.tx_offset = 0
        self.last_rx_ms = time.ticks_ms()
        self.last_motor_ms = time.ticks_ms()
        self.pwm = (0, 0)
        self.stops = 0
        self.pose = None
        self.wlan = None
        self.last_wifi_try = None
        self.pose_settings = self.config('pose_config.json', {})
        self.wifi_settings = self.config('wifi_config.json', dict(ssid='embedded', password='12345678'))
        name_bytes = name.encode()
        self.advertisement = b'\x02\x01\x06' + bytes([len(name_bytes) + 1, 9]) + name_bytes + b'\x11\x07' + bytes(service)
        self.ble.irq(self.irq)
        print('BLE_READY name={} UART=921600; Wi-Fi pose={}'.format(name, self.pose_settings.get('enabled') is True))

    @staticmethod
    def config(path, default):
        try:
            with open(path) as file:
                value = json.load(file)
            return value if isinstance(value, dict) else default
        except (OSError, ValueError):
            return default

    def irq(self, event, data):
        # IRQ only records events. UART/I2C work is handled by the main loop.
        if event == 1:  # central connect
            conn = data[0]
            if self.conn is None:
                self.conn = conn
                self.notify_size = 20
                self.stop_pending = True
                self.count_stop = False
            else:
                self.ble.gap_disconnect(conn)
        elif event == 2 and data[0] == self.conn:  # disconnect
            self.conn = None
            self.stop_pending = True
            self.count_stop = True
            self.advertise_pending = True
        elif event == 3 and data[1] == self.rx:  # GATT write
            self.rx_pending = True
        elif event == 21 and data[0] == self.conn:  # negotiated MTU
            self.notify_size = max(20, min(244, data[1] - 3))

    def stop(self):
        self.car.stop()
        self.pwm = (0, 0)

    def send(self, op, sequence, payload=b''):
        if len(self.tx_queue) >= 8:
            raise OSError('BLE reply queue full')
        self.tx_queue.append(p.frame(op, sequence, payload))

    def dispatch(self, op, sequence, payload):
        try:
            if op == bp.STATUS and not payload:
                info = self.car.request(p.PING)
                snapshot = self.car.request(p.READ, struct.pack('<H', p.CORE | p.BATTERY))
                answer = bp.status_payload(info, snapshot, self.stops, self.parser.bad_crc,
                                           self.pose.status() if self.pose else None)
            elif op in (p.PING, p.READ, p.RESET_ENCODERS, p.LED, p.BUZZER, p.DISPLAY):
                answer = self.car.request(op, payload)
            elif op == p.MOTORS and len(payload) == 4:
                left, right = struct.unpack('<hh', payload)
                if abs(left) > 6000 or abs(right) > 6000:
                    raise ValueError('PWM outside -6000..6000')
                answer = self.car.request(op, payload)
                self.pwm = (left, right)
                self.last_motor_ms = time.ticks_ms()
            else:
                raise ValueError('unsupported BLE command')
            self.send(op | 0x80, sequence, answer)
        except (ValueError, OSError) as error:
            self.stop()
            self.send(p.ERROR, sequence, str(error).encode()[:p.MAX_PAYLOAD])

    def service_wifi(self):
        if self.pose_settings.get('enabled') is not True:
            return
        if self.wlan is None:
            import network
            self.wlan = network.WLAN(network.STA_IF)
            self.wlan.active(True)
            if hasattr(network.WLAN, 'PM_NONE'):
                self.wlan.config(pm=network.WLAN.PM_NONE)
        if self.wlan.isconnected():
            if self.pose is None:
                try:
                    from pose_client import PoseSubscriber
                    c = self.pose_settings
                    self.pose = PoseSubscriber(c.get('server', '192.168.12.1'), c.get('marker_id', 1),
                                               port=c.get('port', 5000), subscription_port=c.get('subscription_port'),
                                               stale_ms=c.get('stale_ms', 500))
                except (OSError, ValueError, TypeError, ImportError) as error:
                    print('Optional pose unavailable:', error)
                    self.pose_settings['enabled'] = False
            if self.pose:
                self.pose.poll()
        else:
            if self.pose:
                self.pose.close()
                self.pose = None
            now = time.ticks_ms()
            if self.last_wifi_try is None or time.ticks_diff(now, self.last_wifi_try) >= 10000:
                self.last_wifi_try = now
                try:
                    self.wlan.connect(self.wifi_settings['ssid'], self.wifi_settings['password'])
                except OSError as error:
                    print('Optional Wi-Fi unavailable:', error)

    def run(self):
        try:
            while True:
                if self.stop_pending:
                    self.stop_pending = False
                    self.stop()
                    if self.count_stop:
                        self.stops = (self.stops + 1) & 0xffff
                    self.count_stop = False
                    self.parser.buffer = b''
                    self.ble.gatts_read(self.rx)
                    self.rx_pending = False
                    self.tx_queue = []
                    self.tx_offset = 0
                if self.advertise_pending and self.conn is None:
                    self.advertise_pending = False
                    self.ble.gap_advertise(100000, adv_data=self.advertisement)
                if self.pwm != (0, 0) and time.ticks_diff(time.ticks_ms(), self.last_motor_ms) >= 250:
                    self.stop()
                    self.stops = (self.stops + 1) & 0xffff
                if self.rx_pending:
                    self.rx_pending = False
                    self.parser.feed(self.ble.gatts_read(self.rx))
                    self.last_rx_ms = time.ticks_ms()
                elif self.parser.buffer and time.ticks_diff(time.ticks_ms(), self.last_rx_ms) > 500:
                    self.parser.buffer = b''
                    self.parser.bad_header += 1
                for _ in range(4):
                    message = self.parser.pop()
                    if message is None:
                        break
                    if self.conn is not None:
                        self.dispatch(*message)
                for _ in range(2):
                    if self.conn is None or not self.tx_queue:
                        break
                    packet = self.tx_queue[0]
                    chunk = packet[self.tx_offset:self.tx_offset + self.notify_size]
                    try:
                        self.ble.gatts_notify(self.conn, self.tx, chunk)
                    except OSError:
                        break  # retry later when controller credits are available
                    self.tx_offset += len(chunk)
                    if self.tx_offset == len(packet):
                        self.tx_queue.pop(0)
                        self.tx_offset = 0
                try:
                    self.service_wifi()
                except (OSError, ValueError, TypeError, KeyError) as error:
                    print('Disabling optional Wi-Fi pose:', error)
                    if self.pose:
                        self.pose.close()
                        self.pose = None
                    self.pose_settings['enabled'] = False
                time.sleep_ms(1)
        finally:
            self.stop()
            if self.pose:
                self.pose.close()
            self.ble.active(False)


def main():
    car = Zumo(timeout_ms=100)
    try:
        while True:
            try:
                car.stop()
                print('Zumo hardware:', car.info())
                break
            except OSError as error:
                print('Waiting for Zumo UART:', error)
                time.sleep_ms(1000)
        settings = BLEHardwareServer.config('ble_config.json', {})
        BLEHardwareServer(car, settings.get('name', 'zumo1')).run()
    finally:
        car.close()
