"""Discover Pico W robots on the network and send JSON wheel PWM commands.

Works with arduino/generic_udp_relay/generic_udp_relay.ino: this script
broadcasts a DISCOVER packet to the sketch's fixed discovery port, each
Pico W replies HELLO <mac>, and once a robot is selected commands are
unicast to its command port (must match what the robot itself subscribes
to, e.g. arduino/generic_udp_relay/remote_control.py's COMMAND_PORT).
"""

from __future__ import annotations

import argparse
import json
import socket
import time

DISCOVERY_PORT = 5001  # Fixed by the sketch; always on regardless of subscriptions.
COMMAND_PORT = 5002    # Must match the robot's own COMMAND_PORT.
DISCOVER_TIMEOUT = 1.5
RESOLUTION = 0.05
HEARTBEAT_SECONDS = 0.10
UPDATE_SECONDS = 0.02
PWM_LIMIT = 6000


def guess_broadcast():
    # Assumes a /24 subnet, true for every hotspot tested so far; pass
    # --broadcast explicitly if your network uses a different subnet size.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))  # No packet sent; just picks a local route.
            local_ip = probe.getsockname()[0]
    except OSError:
        return "192.168.137.255"
    return local_ip.rsplit(".", 1)[0] + ".255"


def discover(broadcast, timeout=DISCOVER_TIMEOUT):
    """Return {mac: ip} for every Pico W that replies within timeout."""
    robots = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        udp.settimeout(0.2)
        udp.sendto(b"DISCOVER", (broadcast, DISCOVERY_PORT))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, (ip, _) = udp.recvfrom(128)
            except socket.timeout:
                continue
            if data.startswith(b"HELLO "):
                mac = data[6:].decode("ascii", errors="replace")
                robots[mac] = ip
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
    """Cached UDP client sending JSON {"l", "r"} wheel PWM to one Pico W."""

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
        self.target = (robot_ip, port)
        self.max_pwm = max_pwm
        self.resolution = resolution
        self.heartbeat_seconds = heartbeat_seconds
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._cached_pwm: tuple[int, int] | None = None
        self._last_send = 0.0
        self._closed = False

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
        command = (self._clamp_pwm(left_pwm), self._clamp_pwm(right_pwm))
        now = time.monotonic()
        changed = command != self._cached_pwm
        if not force and not changed:
            if command == (0, 0):
                return  # Already stopped and unchanged; no need to resend zeros.
            if now - self._last_send < self.heartbeat_seconds:
                return  # Still moving unchanged; only resend as a watchdog heartbeat.
        packet = json.dumps({"l": command[0], "r": command[1]}).encode()
        self._socket.sendto(packet, self.target)
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

    def close(self) -> None:
        if not self._closed:
            self.stop()
            self._socket.close()
            self._closed = True


def main() -> None:
    import combined_input as inp

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("robot_ip", nargs="?", help="Pico W IPv4 address (auto-discover if omitted)")
    parser.add_argument("--broadcast", default=None, help="discovery broadcast address (default: auto-detected)")
    parser.add_argument("--port", type=int, default=COMMAND_PORT)
    parser.add_argument("--gamepad", type=int, default=0)
    parser.add_argument("--max-pwm", type=int, default=3000, help="PWM limit, 1..6000 (default: 3000)")
    args = parser.parse_args()

    if args.robot_ip is None:
        broadcast = args.broadcast or guess_broadcast()
        print(f"Discovering robots via {broadcast}...")
        robots = discover(broadcast)
        args.robot_ip = select_robot(robots)
        if args.robot_ip is None:
            print("No robots found. Use --help for usage.")
            return
        print(f"Using robot at {args.robot_ip}")

    client = DifferentialPWMClient(args.robot_ip, args.port, max_pwm=args.max_pwm)

    print(f"Sending wheel PWM to {args.robot_ip}:{args.port} (limit {args.max_pwm})")
    print("W/S or left stick: forward/reverse")
    print("A/D or right stick: rotate; C/RT: boost; Ctrl+C: stop")

    try:
        while True:
            x, w = _user_velocity(inp, args.gamepad)
            client.set_velocity(x, w)
            time.sleep(UPDATE_SECONDS)
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        client.close()


if __name__ == "__main__":
    main()

