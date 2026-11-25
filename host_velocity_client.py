"""Control a Pico W running velocity_server.py over its Zumo hardware UART.

Discovery uses UDP 5001; commands and acknowledgments use UDP 5002.
The Pico W validates commands and calls Zumo.set_motor_speeds() over UART.
"""

from __future__ import annotations

import argparse
import json
import socket
import secrets
import time

DISCOVERY_PORT = 5001  # Pico W velocity_server.py discovery socket.
COMMAND_PORT = 5002    # Wheel commands, acknowledgments and hardware status.
DISCOVER_TIMEOUT = 1.5
RESOLUTION = 0.05
HEARTBEAT_SECONDS = 0.10
UPDATE_SECONDS = 0.02
PWM_LIMIT = 6000
PROTOCOL = 'zumo-hw-udp-v1'


def discovery_broadcasts():
    """Use actual LAN masks and prefer a hotspot when one is detectable."""
    try:
        from aruco_gps.network_config import discover as interfaces
        networks = interfaces()
        hotspots = [n for n in networks if n['hotspot']]
        addresses = list(dict.fromkeys(n['broadcast'] for n in (hotspots or networks)))
        if addresses:
            return addresses
    except (ImportError, OSError, ValueError):
        pass
    return ['255.255.255.255']


def guess_broadcast():
    return discovery_broadcasts()[0]


def discover(broadcast, timeout=DISCOVER_TIMEOUT):
    """Return {mac: ip} for every Pico W that replies within timeout."""
    robots = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        udp.settimeout(0.2)
        broadcasts = [broadcast] if isinstance(broadcast, str) else broadcast
        deadline = time.monotonic() + timeout
        next_discovery = 0.0
        while time.monotonic() < deadline:
            if time.monotonic() >= next_discovery:
                for address in broadcasts:
                    udp.sendto(b"DISCOVER", (address, DISCOVERY_PORT))
                next_discovery = time.monotonic() + .4
            try:
                data, (ip, _) = udp.recvfrom(128)
            except socket.timeout:
                continue
            if data.startswith(b"HELLO "):
                fields = data[6:].decode("ascii", errors="replace").strip().split()
                if fields:
                    robots[fields[0]] = ip
    return robots


def select_robot(robots):
    if not robots:
        return None
    items = sorted(robots.items())
    if len(items) == 1:
        return items[0][1]
    print("Multiple robots found:")
    for i, (mac, ip) in enumerate(items):
        print(f"  {i}: {mac} at {ip}")
    while True:
        choice = input(f"Select robot [0-{len(items) - 1}]: ").strip()
        if choice.isdigit() and 0 <= int(choice) < len(items):
            return items[int(choice)][1]


def _user_velocity(inp, gamepad_index: int) -> tuple[float, float]:
    suffix = str(gamepad_index)
    boost = inp.get_bipolar_ctrl(high_key="c", high_game=f"RT{suffix}")
    scale = 0.5 + 0.5 * boost
    x = inp.get_bipolar_ctrl("w", "s", f"LY{suffix}") * scale
    w = -inp.get_bipolar_ctrl("d", "a", f"RX{suffix}") * scale
    return x, w


class DifferentialPWMClient:
    """UDP wheel commands with session/sequence IDs and Pico W acknowledgments."""

    def __init__(
        self,
        robot_ip: str,
        port: int = COMMAND_PORT,
        max_pwm: int = 6000,
        resolution: float = RESOLUTION,
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
    ) -> None:
        if not 0 < max_pwm <= PWM_LIMIT:
            raise ValueError(f"max_pwm must be between 1 and {PWM_LIMIT}")
        if resolution <= 0 or not 0 < heartbeat_seconds < 0.25:
            raise ValueError('resolution must be positive and heartbeat must be below the 250 ms watchdog')
        self.target = (robot_ip, port)
        self.max_pwm = max_pwm
        self.resolution = resolution
        self.heartbeat_seconds = heartbeat_seconds
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setblocking(False)
        self.session = secrets.token_hex(8)
        self._sequence = 0
        self.last_ack = None
        self._last_ack_sequence = -1
        self._last_ack_at = time.monotonic()
        self._cached_pwm: tuple[int, int] | None = None
        self._last_send = 0.0
        self._closed = False

    def _send(self, message):
        self._sequence += 1
        message.update(seq=self._sequence, session=self.session)
        self._socket.sendto(json.dumps(message).encode(), self.target)
        return self._sequence

    def _receive(self):
        for _ in range(128):
            try:
                raw, sender = self._socket.recvfrom(4096)
            except BlockingIOError:
                break
            except ConnectionResetError:
                continue
            if sender != self.target:
                continue
            try:
                reply = json.loads(raw)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(reply, dict) or reply.get('session') != self.session:
                continue
            if reply.get('protocol') != PROTOCOL:
                continue
            sequence = reply.get('seq')
            if type(sequence) is not int or sequence < self._last_ack_sequence:
                continue
            self._last_ack_sequence = sequence
            self.last_ack = reply
            self._last_ack_at = time.monotonic()
            if not reply.get('ok'):
                raise RuntimeError('Pico W rejected command: ' + str(reply.get('error')))

    def get_status(self, timeout=1.5):
        """Verify the Wi-Fi endpoint and its physical Zumo hardware connection."""
        sequence = self._send(dict(op='status'))
        deadline = time.monotonic() + timeout
        retry_at = time.monotonic() + .2
        while time.monotonic() < deadline:
            self._receive()
            if self.last_ack and self.last_ack.get('seq') == sequence:
                return self.last_ack
            if time.monotonic() >= retry_at:
                # Status requests are idempotent; UDP can drop a burst.
                self._socket.sendto(json.dumps(dict(op='status', seq=sequence, session=self.session)).encode(), self.target)
                retry_at = time.monotonic() + .2
            time.sleep(0.005)
        raise TimeoutError('No Zumo hardware endpoint replied; check Pico W Wi-Fi and UART wiring.')

    @property
    def last_pwm(self) -> tuple[int, int] | None:
        return self._cached_pwm

    @staticmethod
    def _clamp_pwm(value: int | float) -> int:
        return max(-PWM_LIMIT, min(PWM_LIMIT, round(value)))

    def set_pwm(self, left_pwm: int | float, right_pwm: int | float, force: bool = False) -> None:
        """Send wheel PWM values in the documented -6000..6000 range."""
        if self._closed:
            raise RuntimeError("Client is closed")
        self._receive()
        if self._cached_pwm not in (None, (0, 0)) and time.monotonic() - self._last_ack_at > 0.5:
            raise TimeoutError('Pico W acknowledgments stopped; ending control.')
        command = (self._clamp_pwm(left_pwm), self._clamp_pwm(right_pwm))
        now = time.monotonic()
        changed = command != self._cached_pwm
        if not force and not changed:
            if command == (0, 0):
                return  # Already stopped and unchanged; no need to resend zeros.
            if now - self._last_send < self.heartbeat_seconds:
                return  # Still moving unchanged; only resend as a watchdog heartbeat.
        self._send(dict(l=command[0], r=command[1]))
        self._cached_pwm = command
        self._last_send = now

    def set_velocity(self, x: float, w: float, force: bool = False) -> None:
        """Convert normalized x,w values to proportionally mixed wheel PWM."""
        x = max(-1.0, min(1.0, round(x / self.resolution) * self.resolution))
        w = max(-1.0, min(1.0, round(w / self.resolution) * self.resolution))
        left = x - w
        right = x + w
        scale = max(1.0, abs(left), abs(right))
        self.set_pwm(left * self.max_pwm / scale, right * self.max_pwm / scale, force=force)

    def stop(self) -> None:
        for _ in range(3):
            self.set_pwm(0, 0, force=True)
            time.sleep(.02)

    def close(self) -> None:
        if not self._closed:
            try:
                # Send stops even if an earlier rejection is waiting unread.
                for _ in range(3):
                    self._send(dict(l=0, r=0))
                    time.sleep(.02)
            finally:
                self._socket.close()
                self._closed = True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("robot_ip", nargs="?", help="Pico W IPv4 address (auto-discover if omitted)")
    parser.add_argument("--broadcast", default=None, help="discovery broadcast address (default: auto-detected)")
    parser.add_argument("--port", type=int, default=COMMAND_PORT)
    parser.add_argument("--gamepad", type=int, default=0)
    parser.add_argument("--max-pwm", type=int, default=3000, help="PWM limit, 1..6000 (default: 3000)")
    parser.add_argument('--check', action='store_true', help='verify Wi-Fi/UART and send stop commands, then exit')
    args = parser.parse_args()

    if args.robot_ip is None:
        broadcast = args.broadcast or discovery_broadcasts()
        print(f"Discovering robots via {broadcast}...")
        robots = discover(broadcast)
        args.robot_ip = select_robot(robots)
        if args.robot_ip is None:
            parser.exit(1, "No robots found. Wait for Pico W Wi-Fi startup or supply its IP.\n")
        print(f"Using robot at {args.robot_ip}")

    client = DifferentialPWMClient(args.robot_ip, args.port, max_pwm=args.max_pwm)

    try:
        status = client.get_status()
        print(f"Connected to {args.robot_ip}:{args.port}: {status['protocol']}")
        print(f"Zumo UART: {status['hardware']['baud']} baud; battery {status['battery_mv']} mV")
        client.stop()
        if args.check:
            # A second status confirms the zero command reached the hardware.
            status = client.get_status()
            if status.get('hardware_pwm') != [0, 0]:
                raise RuntimeError('Zumo did not report stopped motors')
            print('Wi-Fi -> Pico W -> Zumo verified; motors stopped.')
            return
        import combined_input as inp
        print(f"Sending wheel PWM (limit {args.max_pwm})")
        print("W/S or left stick: forward/reverse")
        print("A/D or right stick: rotate; C/RT: boost; Ctrl+C: stop")
        while True:
            x, w = _user_velocity(inp, args.gamepad)
            client.set_velocity(x, w)
            time.sleep(UPDATE_SECONDS)
    except KeyboardInterrupt:
        print("\nStopping.")
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f'Control stopped: {error}\n')
    finally:
        client.close()


if __name__ == "__main__":
    main()

