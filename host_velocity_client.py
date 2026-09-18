"""Send raw wheel PWM to a car, with an optional normalized x,w abstraction."""

from __future__ import annotations

import argparse
import socket
import struct
import sys
import time
from pathlib import Path

PACKET = struct.Struct(">2sHhh")
MAGIC = b"PW"
UDP_PORT = 42001
RESOLUTION = 0.05
HEARTBEAT_SECONDS = 0.10
UPDATE_SECONDS = 0.02
PWM_LIMIT = 6000



def _quantize(value: float) -> float:
    value = max(-1.0, min(1.0, value))
    return round(value / RESOLUTION) * RESOLUTION


def _user_velocity(inp, gamepad_index: int) -> tuple[float, float]:
    suffix = str(gamepad_index)
    boost = inp.get_bipolar_ctrl(high_key="c", high_game=f"RT{suffix}")
    scale = 0.5 + 0.5 * boost
    x = inp.get_bipolar_ctrl("w", "s", f"LY{suffix}") * scale
    w = -inp.get_bipolar_ctrl("d", "a", f"RX{suffix}") * scale
    return x, w


def _packet(sequence: int, left_pwm: int, right_pwm: int) -> bytes:
    return PACKET.pack(MAGIC, sequence & 0xFFFF, left_pwm, right_pwm)


class DifferentialPWMClient:
    """Cached UDP client for raw PWM, with normalized differential mixing."""

    def __init__(
        self,
        robot_ip: str,
        port: int = UDP_PORT,
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
        self._sequence = 0
        self._cached_pwm: tuple[int, int] | None = None
        self._last_send = 0.0
        self._closed = False

    @staticmethod
    def _clamp_pwm(value: int | float) -> int:
        return max(-PWM_LIMIT, min(PWM_LIMIT, round(value)))

    def set_pwm(self, left_pwm: int | float, right_pwm: int | float, force: bool = False) -> None:
        """Send raw Zumo PWM values in the documented -6000..6000 range."""
        if self._closed:
            raise RuntimeError("Client is closed")
        command = (self._clamp_pwm(left_pwm), self._clamp_pwm(right_pwm))
        now = time.monotonic()
        if not force and command == self._cached_pwm and now - self._last_send < self.heartbeat_seconds:
            return
        self._socket.sendto(_packet(self._sequence, *command), self.target)
        self._sequence = (self._sequence + 1) & 0xFFFF
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
    parser.add_argument("--port", type=int, default=UDP_PORT)
    parser.add_argument("--gamepad", type=int, default=0)
    parser.add_argument("--max-pwm", type=int, default=3000, help="PWM limit, 1..6000 (default: 1800)")
    args = parser.parse_args()

    if args.robot_ip is None:
        from robot_discovery import discover, select_robot
        print("Discovering robots...")
        robots = discover()
        selected = select_robot(robots)
        if selected is None:
            print("No robots found. Use --help for usage.")
            return
        args.robot_ip = selected["ip"]
        print(f"Using robot: {selected['name']} at {args.robot_ip}")

    client = DifferentialPWMClient(args.robot_ip, args.port, max_pwm=args.max_pwm)

    print(f"Sending raw wheel PWM to {args.robot_ip}:{args.port} (limit {args.max_pwm})")
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
