import time
import math
import numpy as np

from host_velocity_client import DifferentialPWMClient
from pose_network import PoseSubscriber


ROBOT_IP = "192.168.137.235"
POSE_SERVER_IP = "127.0.0.1"
ROBOT_ID = 5
KP = 0.75
MAX_W = 0.2
MIN_W = 0.1
DEADBAND = np.deg2rad(5)
KP_DISTANCE = 3.0
MAX_X = 0.2
MIN_X = 0.1
DISTANCE_TOLERANCE = 0.015
FULL_STOP_ANGLE = np.deg2rad(15)
DEBUG_INTERVAL = 0.25
WAYPOINTS = np.array([
    [-0.18, -0.22],
    [0.18, -0.22],
    [0.18, 0.22],
    [-0.18, 0.22],
], dtype=np.float32)


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


def control_command(position, heading, waypoint):
    distance = float(np.linalg.norm(waypoint - position))
    error = float(angle_to_target(position, heading, waypoint))
    authority = distance_authority(error)

    command_w = 0.0
    if abs(error) >= DEADBAND:
        command_w = float(np.clip(KP * error, -MAX_W, MAX_W))
        if abs(command_w) < MIN_W:
            command_w = math.copysign(MIN_W, command_w)

    command_x = min(max(KP_DISTANCE * distance, MIN_X), MAX_X) * authority
    return distance, error, authority, command_x, command_w


def main():
    poses = PoseSubscriber(POSE_SERVER_IP)
    client = DifferentialPWMClient(ROBOT_IP)
    waypoint_index = 0
    last_debug = 0.0
    last_status = None

    try:
        while True:
            now = time.monotonic()
            command_x = 0.0
            command_w = 0.0
            snapshot = poses.receive_latest()
            robot = None
            status = "POSE STALE"
            details = ""

            if snapshot is not None and not snapshot["board_visible"]:
                status = "BOARD MISSING"
            elif snapshot is not None:
                robot = next(
                    (pose for pose in snapshot["poses"] if pose["id"] == ROBOT_ID),
                    None,
                )
                status = "ROBOT MISSING" if robot is None else "CONTROL"

            if robot is not None:
                position = np.array([robot["x"], robot["y"]])
                waypoint = WAYPOINTS[waypoint_index]
                distance = float(np.linalg.norm(waypoint - position))
                if distance <= DISTANCE_TOLERANCE:
                    waypoint_index = (waypoint_index + 1) % len(WAYPOINTS)
                    waypoint = WAYPOINTS[waypoint_index]
                distance, error, authority, command_x, command_w = control_command(
                    position, robot["theta"], waypoint
                )
                source = "flow" if robot["tracked"] else "aruco"
                details = (
                    f"pos=({position[0]:+.3f},{position[1]:+.3f}) "
                    f"heading={np.degrees(robot['theta']):+.1f}deg src={source} "
                    f"wp={waypoint_index + 1} d={distance:.3f}m "
                    f"error={np.degrees(error):+.1f}deg auth={authority:.0%}"
                )

            client.set_velocity(command_x, command_w)
            if snapshot is not None:
                age_ms = (time.monotonic() - poses.last_received) * 1000
                prefix = f"seq={snapshot['sequence']} age={age_ms:.0f}ms"
            else:
                prefix = "seq=- age=>300ms"

            if status != last_status or now - last_debug >= DEBUG_INTERVAL:
                print(
                    f"[{status}] {prefix} {details} "
                    f"cmd=({command_x:+.3f},{command_w:+.3f}) "
                    f"pwm={client.last_pwm} tx_seq={client.last_sequence}",
                    flush=True,
                )
                last_debug = now
                last_status = status
    finally:
        try:
            client.close()
        finally:
            poses.close()


if __name__ == "__main__":
    main()
