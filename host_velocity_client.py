"""BLE WASD/gamepad control and hardware reads through the Pico W Zumo bridge."""
from __future__ import annotations
import argparse
import asyncio
import struct
import time
from robot_firmware.pico_w import ble_protocol as bp
from zumo_ble import BLETransport, scan

PWM_LIMIT = 6000
RESOLUTION = .05
HEARTBEAT_SECONDS = .10
UPDATE_SECONDS = .02
PROTOCOL = bp.PROTOCOL


def _user_velocity(inp, gamepad_index):
    suffix = str(gamepad_index)
    boost = inp.get_bipolar_ctrl(high_key='c', high_game=f'RT{suffix}')
    scale = .5 + .5 * boost
    x = inp.get_bipolar_ctrl('w', 's', f'LY{suffix}') * scale
    w = -inp.get_bipolar_ctrl('d', 'a', f'RX{suffix}') * scale
    return x, w


class DifferentialPWMClient:
    """Synchronous application API over one shared, thread-safe BLE connection."""
    def __init__(self, device='zumo1', max_pwm=6000, resolution=RESOLUTION,
                 heartbeat_seconds=HEARTBEAT_SECONDS, read_only=False, transport=None):
        if not 0 < max_pwm <= PWM_LIMIT:
            raise ValueError('max_pwm must be 1..6000')
        if resolution <= 0 or not 0 < heartbeat_seconds < .25:
            raise ValueError('resolution must be positive and heartbeat below 250 ms')
        self.max_pwm, self.resolution = max_pwm, resolution
        self.heartbeat_seconds, self.read_only = heartbeat_seconds, read_only
        self._cached_pwm = None
        self._last_send = 0.0
        self._closed = False
        self._transport = transport or BLETransport(device)

    @property
    def last_pwm(self):
        return self._cached_pwm

    def get_status(self, timeout=3):
        return bp.decode_status(self._transport.request(bp.STATUS, timeout=timeout))

    def get_sensors(self, mask=6, timeout=1.5):
        return bp.wire.decode_snapshot(self._transport.request(bp.wire.READ, struct.pack('<H', mask), timeout))

    def reset_encoders(self):
        self._transport.request(bp.wire.RESET_ENCODERS)

    def led(self, on):
        self._transport.request(bp.wire.LED, bytes([bool(on)]))

    def buzzer(self, notes=''):
        self._transport.request(bp.wire.BUZZER, notes.encode())

    def display(self, text):
        self._transport.request(bp.wire.DISPLAY, text.encode())

    def set_pwm(self, left_pwm, right_pwm, force=False):
        if self._closed:
            raise RuntimeError('Client is closed')
        if self.read_only:
            raise RuntimeError('This connection only reads hardware')
        command = tuple(max(-PWM_LIMIT, min(PWM_LIMIT, round(v))) for v in (left_pwm, right_pwm))
        now = time.monotonic()
        if not force and command == self._cached_pwm:
            if command == (0, 0) or now - self._last_send < self.heartbeat_seconds:
                return
        reply = self._transport.request(bp.wire.MOTORS, struct.pack('<hh', *command), timeout=.4)
        if struct.unpack('<hh', reply) != command:
            raise RuntimeError('Motor acknowledgment does not match the command')
        self._cached_pwm = command
        self._last_send = now

    def set_velocity(self, x, w, force=False):
        x = max(-1.0, min(1.0, round(x / self.resolution) * self.resolution))
        w = max(-1.0, min(1.0, round(w / self.resolution) * self.resolution))
        left, right = x - w, x + w
        scale = max(1.0, abs(left), abs(right))
        self.set_pwm(left * self.max_pwm / scale, right * self.max_pwm / scale, force)

    def stop(self):
        self.set_pwm(0, 0, force=True)

    def close(self):
        if self._closed:
            return
        try:
            if not self.read_only:
                try:
                    self.stop()
                except Exception:
                    pass  # disconnect and the independent Zumo timeout stop it
        finally:
            self._closed = True
            self._transport.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def format_ir_readings(sample):
    line = ' '.join(f'{value:4d}' for value in sample['line'])
    proximity = sample['proximity']
    return (f'IR line raw (L->R): [{line}]\n'
            f'IR proximity (left-emitter, right-emitter counts): '
            f'left={tuple(proximity[0])} front={tuple(proximity[1])} right={tuple(proximity[2])}\n'
            f"Acquisition: {sample['sample_us'] / 1000:.2f} ms")


def choose_device(identifier=None):
    print('Scanning for BLE Zumo hardware servers...')
    devices = asyncio.run(scan())
    if identifier:
        devices = [d for d in devices if identifier.casefold() in
                   ((d.name or '').casefold(), d.address.casefold())]
    if not devices:
        raise ConnectionError('No BLE Zumo found; power it on and enable Bluetooth')
    if len(devices) == 1:
        return devices[0]
    for i, device in enumerate(devices, 1):
        print(f'  {i}) {device.name} [{device.address}]')
    while True:
        answer = input('Choose robot: ').strip()
        if answer.isdigit() and 1 <= int(answer) <= len(devices):
            return devices[int(answer) - 1]


def main(ir_hotkey=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('device', nargs='?', help='BLE robot name or address (discover if omitted)')
    parser.add_argument('--gamepad', type=int, default=0)
    parser.add_argument('--max-pwm', type=int, default=3000)
    parser.add_argument('--check', action='store_true', help='verify BLE/UART and stopped motors, then exit')
    if ir_hotkey is not None:
        parser.add_argument('--ir-key', default=ir_hotkey)
        parser.add_argument('--read-ir', action='store_true', help='print one IR snapshot without keyboard control')
    args = parser.parse_args()
    client = worker = None
    future = None
    try:
        device = choose_device(args.device)
        print(f'Connecting to {device.name} [{device.address}] via BLE')
        read_only = ir_hotkey is not None and args.read_ir
        client = DifferentialPWMClient(device, max_pwm=args.max_pwm, read_only=read_only)
        status = client.get_status()
        print(f"Connected: {status['protocol']}; Zumo UART {status['hardware']['baud']} baud; battery {status['battery_mv']} mV")
        position = status['position']
        if position['enabled']:
            print(f"Position marker {position['marker_id']}: {position['pose'] or position['reason']}")
        if read_only:
            print(format_ir_readings(client.get_sensors()))
            return
        client.stop()
        if args.check:
            if client.get_status()['hardware_pwm'] != [0, 0]:
                raise RuntimeError('Zumo did not report stopped motors')
            print('BLE -> Pico W -> Zumo verified; motors stopped.')
            return
        import combined_input as inp
        if ir_hotkey is not None:
            from concurrent.futures import ThreadPoolExecutor
            worker = ThreadPoolExecutor(max_workers=1)
            print(f'{args.ir_key.upper()}: print IR sensor readings (once per press)')
        print('W/S: forward/reverse; A/D: rotate; C/RT: boost; Ctrl+C: stop')
        while True:
            x, w = _user_velocity(inp, args.gamepad)
            client.set_velocity(x, w)
            if worker:
                if future and future.done():
                    try:
                        print(format_ir_readings(future.result()))
                    except Exception as error:
                        print(f'IR read failed: {error}')
                    future = None
                if inp.rising_edge(args.ir_key) and future is None:
                    # One BLE connection, concurrent request IDs: do not create
                    # a second central connection for sensor reads.
                    future = worker.submit(client.get_sensors)
            time.sleep(UPDATE_SECONDS)
    except KeyboardInterrupt:
        print('\nStopping.')
    except Exception as error:
        parser.exit(1, f'Control stopped: {error}\n')
    finally:
        if client:
            client.close()
        if worker:
            worker.shutdown(wait=False, cancel_futures=True)


if __name__ == '__main__':
    main()
