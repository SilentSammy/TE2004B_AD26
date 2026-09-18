import math
import time

import cv2
import numpy as np

import vision_setup
from pose_network import PoseSubscriber


PLOT_FPS = 10
PROCESS_NAME = "Pose Plotter"


def pose_to_corners(pose):
    center = np.array([pose["x"], -pose["y"]], dtype=np.float32)
    half_size = pose.get("size", 0.05) / 2
    top = np.array([
        math.cos(pose["theta"]),
        -math.sin(pose["theta"]),
    ], dtype=np.float32) * half_size
    right = np.array([-top[1], top[0]], dtype=np.float32)
    return np.array([
        center + top - right,
        center + top + right,
        center - top + right,
        center - top - right,
    ])


def main():
    plotter = vision_setup.VISION.plotter
    subscriber = PoseSubscriber()
    last_print = 0.0

    cv2.namedWindow("Board", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Board", 400, round(400 * plotter.height / plotter.width))
    print(f"[{PROCESS_NAME}] Waiting for poses...", flush=True)

    try:
        while True:
            started = time.monotonic()
            snapshot = subscriber.receive_latest()
            poses = [] if snapshot is None else snapshot["poses"]
            markers = [
                (pose["id"], pose_to_corners(pose), pose["tracked"])
                for pose in poses
            ]

            if started - last_print >= 1.0:
                if snapshot is None:
                    print(f"[{PROCESS_NAME}] No fresh positions", flush=True)
                else:
                    positions = " | ".join(
                        f"ID {pose['id']}: x={pose['x']:+.3f}, "
                        f"y={pose['y']:+.3f}, "
                        f"theta={math.degrees(pose['theta']):+.1f} deg"
                        for pose in poses
                    )
                    print(
                        f"[{PROCESS_NAME}] seq={snapshot['sequence']} "
                        f"board_visible={snapshot['board_visible']} "
                        f"{positions or 'no markers'}",
                        flush=True,
                    )
                last_print = started

            cv2.imshow("Board", plotter.render(markers))
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
            time.sleep(max(0.0, 1 / PLOT_FPS - (time.monotonic() - started)))
    finally:
        subscriber.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
