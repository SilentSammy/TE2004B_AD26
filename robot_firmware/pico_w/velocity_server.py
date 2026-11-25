"""UDP teleoperation endpoint backed by the Zumo binary UART hardware server."""
import json
import network
import socket
import time
import select
import binascii
from zumo_client import Zumo
import hw_protocol as p

DISCOVERY_PORT = 5001
COMMAND_PORT = 5002
COMMAND_TIMEOUT_MS = 250
PROTOCOL = 'zumo-hw-udp-v1'


class VelocityServer:
    def __init__(self, car, wlan):
        self.car, self.wlan = car, wlan
        self.mac = binascii.hexlify(wlan.config('mac')).decode()
        self.owner = None
        self.last_sequence = -1
        self.sequences = {}
        self.last_command_ms = time.ticks_ms()
        self.pwm = (0, 0)
        self.commands = 0
        self.network_stops = 0
        self.sockets = []
        self.poller = select.poll()
        try:
            for port in (DISCOVERY_PORT, COMMAND_PORT):
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sockets.append(sock)
                sock.bind(('0.0.0.0', port))
                sock.setblocking(False)
                self.poller.register(sock, select.POLLIN)
            self.car.stream(0)
            self.car.stop()
        except BaseException:
            self.close()
            raise

    def close(self):
        for sock in self.sockets:
            sock.close()
        self.sockets = []
        self.car.stop()

    def reply(self, sock, address, message):
        try:
            sock.sendto(json.dumps(message).encode(), address)
        except OSError:
            pass

    def stop(self):
        self.car.stop()
        self.pwm = (0, 0)
        self.owner = None
        self.last_sequence = -1

    def handle(self, sock, address, raw):
        seq, session = None, None
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError('expected a JSON object')
            seq, session = data.get('seq'), data.get('session')
            if type(seq) is not int or not 0 <= seq <= 0xffffffff:
                raise ValueError('seq must be a uint32')
            if not isinstance(session, str) or not 1 <= len(session) <= 32:
                raise ValueError('session must be a nonempty string up to 32 characters')
            if data.get('op') == 'status':
                info = self.car.info()
                sample = self.car.read_sensors(p.CORE | p.BATTERY)
                self.reply(sock, address, dict(ok=True, seq=seq, session=session, protocol=PROTOCOL,
                                               ip=self.wlan.ifconfig()[0], hardware=info,
                                               pwm=self.pwm, hardware_pwm=sample['motor_pwm'],
                                               encoders=sample['encoders'], battery_mv=sample['battery_mv'],
                                               commands=self.commands, network_stops=self.network_stops))
                return
            left, right = data.get('l'), data.get('r')
            if type(left) is not int or type(right) is not int or abs(left) > 6000 or abs(right) > 6000:
                raise ValueError('l and r must be integers in -6000..6000')
            owner = (address, session)
            now = time.ticks_ms()
            if self.owner and time.ticks_diff(now, self.last_command_ms) >= COMMAND_TIMEOUT_MS:
                self.stop()
                self.network_stops += 1
            # Any client may stop the robot. Nonzero control has one owner.
            if (left, right) == (0, 0):
                self.stop()
            else:
                if self.owner is not None and self.owner != owner:
                    raise ValueError('robot is controlled by another client')
                if seq <= self.sequences.get(owner, -1):
                    raise ValueError('stale command sequence')
                self.car.set_motor_speeds(left, right)
                self.owner = owner
                self.last_sequence = seq
                self.last_command_ms = now
                self.pwm = (left, right)
            if owner not in self.sequences and len(self.sequences) >= 8:
                del self.sequences[next(iter(self.sequences))]
            self.sequences[owner] = max(seq, self.sequences.get(owner, -1))
            self.commands += 1
            self.reply(sock, address, dict(ok=True, seq=seq, session=session, protocol=PROTOCOL, pwm=self.pwm))
        except (ValueError, TypeError, OSError) as error:
            # Invalid/foreign commands never renew the current motor lease.
            self.reply(sock, address, dict(ok=False, seq=seq, session=session, protocol=PROTOCOL, error=str(error)))

    def run(self):
        print('VELOCITY_READY ip={} discovery={} commands={} protocol={}'.format(
            self.wlan.ifconfig()[0], DISCOVERY_PORT, COMMAND_PORT, PROTOCOL))
        try:
            while self.wlan.isconnected():
                if self.owner and time.ticks_diff(time.ticks_ms(), self.last_command_ms) >= COMMAND_TIMEOUT_MS:
                    self.stop()
                    self.network_stops += 1
                for sock, event in self.poller.poll(5):
                    if not event & select.POLLIN:
                        continue
                    # Bound work so a packet flood cannot starve the timeout.
                    for _ in range(8):
                        try:
                            raw, address = sock.recvfrom(513)
                        except OSError:
                            break
                        if len(raw) > 512:
                            continue
                        if sock is self.sockets[0]:
                            if raw == b'DISCOVER':
                                sock.sendto(('HELLO ' + self.mac).encode(), address)
                        else:
                            self.handle(sock, address, raw)
        finally:
            self.close()


def main():
    try:
        with open('wifi_config.json') as file:
            config = json.load(file)
    except OSError:
        config = dict(ssid='embedded', password='12345678')
    car = Zumo(timeout_ms=100)
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    try:
        if hasattr(network.WLAN, 'PM_NONE'):
            wlan.config(pm=network.WLAN.PM_NONE)
        while True:
            try:
                car.stop()
                print('Zumo hardware:', car.info())
                if not wlan.isconnected():
                    print('Connecting Wi-Fi:', config['ssid'])
                    wlan.connect(config['ssid'], config['password'])
                    deadline = time.ticks_add(time.ticks_ms(), 20000)
                    while not wlan.isconnected() and time.ticks_diff(deadline, time.ticks_ms()) > 0:
                        time.sleep_ms(100)
                    if not wlan.isconnected():
                        raise OSError('Wi-Fi connection timeout')
                VelocityServer(car, wlan).run()
            except OSError as error:
                print('Velocity server retry:', error)
                try:
                    car.stop()
                except OSError:
                    pass
                time.sleep_ms(1000)
    finally:
        car.close()
