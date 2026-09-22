"""Follow a fixed set of waypoints using pose telemetry from main.py.

Listens for main.py's UDP telemetry broadcast (no subscription needed, just
bind to the port) and drives a robot discovered via
arduino/dual_channel_relay/dual_channel_relay.ino, same as
host_velocity_client.py.
"""

import argparse
import json
import socket
import time

import numpy as np

from host_velocity_client import DifferentialPWMClient, discover, guess_broadcast, select_robot

TELEMETRY_PORT = 5000
ROBOT_ID = 0
KP = 0.75
MAX_W = 0.25
DEADBAND = np.deg2rad(5)
KP_DISTANCE = 5.0
MAX_X = 0.5
DISTANCE_TOLERANCE = 0.04
ANGLE_SETTLE_RADIUS = 0.06  # Below this distance, taper angular authority to stop spinning on noisy bearings.
FULL_STOP_ANGLE = np.deg2rad(15)
WAYPOINTS = np.array([
    [-0.18, -0.22],
    [0.18, -0.22],
    [0.18, 0.22],
    [-0.18, 0.22],
], dtype=np.float32)


class PoseListener:
    """Receives main.py's broadcast telemetry; no subscription handshake needed."""

    def __init__(self, port=TELEMETRY_PORT, stale_seconds=0.5):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(("", port))
        self.socket.setblocking(False)
        self.stale_seconds = stale_seconds
        self.last_received = 0.0
        self.latest = None

    def receive_latest(self):
        now = time.monotonic()
        while True:
            try:
                data, _ = self.socket.recvfrom(65535)
            except BlockingIOError:
                break
            try:
                message = json.loads(data)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if "markers" in message:
                self.latest = message
                self.last_received = now

        if now - self.last_received > self.stale_seconds:
            return None
        return self.latest

    def close(self):
        self.socket.close()


def angle_to_target(position, heading, waypoint):
    target = np.asarray(waypoint) - position
    target_heading = np.arctan2(target[1], target[0])
    return np.arctan2(
        np.sin(target_heading - heading),
        np.cos(target_heading - heading),
    )


def distance_authority(angle_error):
    return float(np.clip(
        1 - abs(angle_error) / FULL_STOP_ANGLE, 0.0, 1.0
    ))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("robot_ip", nargs="?", help="Pico W IPv4 address (auto-discover if omitted)")
    parser.add_argument("--broadcast", default=None, help="robot discovery broadcast address (default: auto-detected)")
    parser.add_argument("--telemetry-port", type=int, default=TELEMETRY_PORT, help="port main.py broadcasts telemetry on")
    parser.add_argument("--robot-id", type=int, default=ROBOT_ID, help="marker ID to track as this robot")
    args = parser.parse_args()

    robot_ip = args.robot_ip
    if robot_ip is None:
        broadcast = args.broadcast or guess_broadcast()
        print(f"Discovering robots via {broadcast}...")
        robots = discover(broadcast)
        robot_ip = select_robot(robots)
        if robot_ip is None:
            print("No robots found. Use --help for usage.")
            return
        print(f"Using robot at {robot_ip}")

    poses = PoseListener(args.telemetry_port)
    client = DifferentialPWMClient(robot_ip)
    waypoint_index = 0
    last_debug = time.monotonic()
    last_seen = time.monotonic()

    try:
        while True:
            command_x = 0.0
            command_w = 0.0
            snapshot = poses.receive_latest()
            robot = None
            if snapshot is not None and snapshot["board_detected"]:
                robot = next(
                    (marker for marker in snapshot["markers"] if marker["id"] == args.robot_id),
                    None,
                )

            now_dbg = time.monotonic()
            if robot is not None:
                last_seen = now_dbg
                position = np.array([robot["x"], robot["y"]])
                heading = np.deg2rad(robot["angle"])
                waypoint = WAYPOINTS[waypoint_index]
                distance = np.linalg.norm(waypoint - position)
                if distance <= DISTANCE_TOLERANCE:
                    waypoint_index = (waypoint_index + 1) % len(WAYPOINTS)
                    waypoint = WAYPOINTS[waypoint_index]
                    distance = np.linalg.norm(waypoint - position)

                error = angle_to_target(position, heading, waypoint)
                authority = distance_authority(error)
                angular_scale = min(1.0, distance / ANGLE_SETTLE_RADIUS)
                if abs(error) >= DEADBAND:
                    command_w = float(np.clip(KP * error, -MAX_W, MAX_W)) * angular_scale
                command_x = float(min(KP_DISTANCE * distance, MAX_X) * authority)

                if now_dbg - last_debug >= 0.2:
                    stalled = abs(command_x) < 1e-3 and abs(command_w) < 1e-3 and distance > DISTANCE_TOLERANCE
                    print(
                        f"{'STALL ' if stalled else ''}wp={waypoint_index} dist={distance:.3f} "
                        f"err={np.degrees(error):+.1f}deg ang_scale={angular_scale:.2f} "
                        f"authority={authority:.2f} cmd_x={command_x:+.3f} cmd_w={command_w:+.3f}",
                        flush=True,
                    )
                    last_debug = now_dbg
            elif now_dbg - last_debug >= 0.2:
                print(f"no robot marker (last seen {now_dbg - last_seen:.1f}s ago)", flush=True)
                last_debug = now_dbg

            client.set_velocity(command_x, command_w)
            time.sleep(0.02)
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        client.close()
        poses.close()


if __name__ == "__main__":
    main()
