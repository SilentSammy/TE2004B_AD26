import vision_setup
import cv2
import numpy as np
import time
from frame_ipc import FrameSubscriber
from marker_tracker import MarkerTracker
from pose_network import PosePublisher


PROCESS_NAME = "Pose Detector"

vision = vision_setup.VISION
detector = vision.detector
board_estimator = vision.board_estimator
marker_tracker = MarkerTracker()
publisher = PosePublisher()
frames = FrameSubscriber()
marker_sizes = {}
fps_started = time.monotonic()
fps_frames = 0
capture_sequence = None
last_wait_message = 0.0

try:
    while True:
        success, frame, frame_info = frames.read()
        if not success:
            now = time.monotonic()
            if now - last_wait_message >= 1.0:
                print(f"[{PROCESS_NAME}] Waiting for camera stream...", flush=True)
                last_wait_message = now
            continue

        board_result = board_estimator.get_board_transform(frame)
        corners, ids, _ = detector.detectMarkers(frame)
        robots = marker_tracker.update(frame, corners, ids)
        poses = []

        for marker_id, marker_corners, is_tracked in robots:
            color = (0, 165, 255) if is_tracked else (0, 255, 0)
            center = marker_corners.mean(axis=0)
            label = f"ID {marker_id}"
            if board_result is not None:
                _, pnp_result = board_result
                x, y = board_estimator.project_point_to_board(
                    pnp_result, center, frame.shape, vision.marker_height_m
                )
                label += f": ({x:.3f}, {y:.3f}) m"
                board_corners = np.array([
                    board_estimator.project_point_to_board(
                        pnp_result, corner, frame.shape, vision.marker_height_m
                    )
                    for corner in marker_corners
                ])
                board_center = board_corners.mean(axis=0)
                forward = (board_corners[0] + board_corners[1]) / 2 - board_center
                measured_size = float(np.median(np.linalg.norm(
                    np.roll(board_corners, -1, axis=0) - board_corners,
                    axis=1,
                )))
                if not is_tracked:
                    marker_sizes[marker_id] = round(measured_size / 0.005) * 0.005
                poses.append({
                    "id": marker_id,
                    "x": float(board_center[0]),
                    "y": float(-board_center[1]),
                    "theta": float(np.arctan2(-forward[1], forward[0])),
                    "size": marker_sizes.get(marker_id, measured_size),
                    "tracked": is_tracked,
                })

            cv2.polylines(
                frame,
                [marker_corners.astype(np.int32).reshape(-1, 1, 2)],
                True,
                color,
                2,
            )
            cv2.putText(
                frame, label, tuple(center.astype(int)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2,
            )
        publisher.publish(
            board_result is not None,
            poses,
            frame_sequence=frame_info["sequence"],
            capture_time_ns=frame_info["capture_time_ns"],
        )
        fps_frames += 1
        now = time.monotonic()
        if now - fps_started >= 2.0:
            elapsed = now - fps_started
            captured = (
                frame_info["sequence"] - capture_sequence
                if capture_sequence is not None
                else fps_frames
            )
            print(
                f"[{PROCESS_NAME}] {fps_frames / elapsed:.1f} FPS "
                f"(camera {captured / elapsed:.1f} FPS)",
                flush=True,
            )
            capture_sequence = frame_info["sequence"]
            fps_started = now
            fps_frames = 0
except KeyboardInterrupt:
    pass
finally:
    publisher.close()
    frames.close()
