import time
import numpy as np

from host_velocity_client import DifferentialPWMClient
from pose_network import PoseSubscriber


ROBOT_IP = "192.168.137.74"
POSE_SERVER_IP = "127.0.0.1"
ROBOT_ID = 0
KP = 0.75
MAX_W = 0.2
DEADBAND = np.deg2rad(5)
KP_DISTANCE = 3.0
MAX_X = 0.2
DISTANCE_TOLERANCE = 0.015
FULL_STOP_ANGLE = np.deg2rad(15)
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


def main():
    poses = PoseSubscriber(POSE_SERVER_IP)
    client = DifferentialPWMClient(ROBOT_IP)
    waypoint_index = 0

    try:
        while True:
            command_x = 0.0
            command_w = 0.0
            snapshot = poses.receive_latest()
            robot = None
            if snapshot is not None and snapshot["board_visible"]:
                robot = next(
                    (pose for pose in snapshot["poses"] if pose["id"] == ROBOT_ID),
                    None,
                )

            if robot is not None:
                position = np.array([robot["x"], robot["y"]])
                waypoint = WAYPOINTS[waypoint_index]
                distance = np.linalg.norm(waypoint - position)
                if distance <= DISTANCE_TOLERANCE:
                    waypoint_index = (waypoint_index + 1) % len(WAYPOINTS)
                    waypoint = WAYPOINTS[waypoint_index]
                    distance = np.linalg.norm(waypoint - position)

                error = angle_to_target(position, robot["theta"], waypoint)
                authority = distance_authority(error)
                if abs(error) >= DEADBAND:
                    command_w = float(np.clip(KP * error, -MAX_W, MAX_W))
                command_x = float(min(KP_DISTANCE * distance, MAX_X) * authority)

            client.set_velocity(command_x, command_w)
            time.sleep(0.02)
    finally:
        try:
            client.close()
        finally:
            poses.close()


if __name__ == "__main__":
    main()
