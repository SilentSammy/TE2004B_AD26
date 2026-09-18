import vision_setup
import cv2
import numpy as np
import time
from marker_tracker import MarkerTracker
from pose_network import PosePublisher


SHOW_BOARD_PLOT = True

vision = vision_setup.VISION
camera = vision.camera
detector = vision.detector
board_estimator = vision.board_estimator
marker_tracker = MarkerTracker()
plotter = vision.plotter
publisher = PosePublisher()
fps_started = time.monotonic()
fps_frames = 0
capture_sequence = 0
board_plot = plotter.render() if SHOW_BOARD_PLOT else None
last_plot = 0.0

if SHOW_BOARD_PLOT:
    cv2.namedWindow("Board", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Board", 400, round(400 * plotter.height / plotter.width))

try:
    while camera.isOpened():
        success, frame = camera.read()
        if not success:
            break

        board_result = board_estimator.get_board_transform(frame)
        corners, ids, _ = detector.detectMarkers(frame)
        robots = marker_tracker.update(frame, corners, ids)
        plot_markers = []
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
                plot_markers.append((marker_id, board_corners, is_tracked))
                board_center = board_corners.mean(axis=0)
                forward = (board_corners[0] + board_corners[1]) / 2 - board_center
                poses.append({
                    "id": marker_id,
                    "x": float(board_center[0]),
                    "y": float(-board_center[1]),
                    "theta": float(np.arctan2(-forward[1], forward[0])),
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
        publisher.publish(board_result is not None, poses)
        fps_frames += 1
        now = time.monotonic()
        if now - fps_started >= 2.0:
            elapsed = now - fps_started
            source = getattr(camera.frame_getter, "source", None)
            captured = source.sequence - capture_sequence if source is not None else fps_frames
            print(
                f"Vision: {fps_frames / elapsed:.1f} FPS "
                f"(camera {captured / elapsed:.1f} FPS)",
                flush=True,
            )
            capture_sequence = source.sequence if source is not None else capture_sequence
            fps_started = now
            fps_frames = 0
        cv2.imshow("Camera 1", frame)
        if SHOW_BOARD_PLOT:
            if now - last_plot >= 0.1:
                board_plot = plotter.render(plot_markers)
                last_plot = now
            cv2.imshow("Board", board_plot)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
finally:
    publisher.close()
    camera.release()
    cv2.destroyAllWindows()
