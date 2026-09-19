import time

import cv2
import numpy as np

from vision_setup import VISION


def main():
    camera = VISION.camera
    estimator = VISION.board_estimator
    detector = VISION.detector
    plotter = VISION.plotter

    cv2.namedWindow("Camera", cv2.WINDOW_NORMAL)
    cv2.namedWindow("Board", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Board", 400, round(400 * plotter.height / plotter.width))

    stats_at = last_plot = time.monotonic()
    frames = read_time = vision_time = plot_time = 0.0

    try:
        while True:
            started = time.monotonic()
            success, frame = camera.read()
            if not success:
                print("Camera stopped or could not be opened.")
                break
            read_done = time.monotonic()

            board_result = estimator.get_board_transform(frame)
            corners, ids, _ = detector.detectMarkers(frame)
            markers = []
            positions = []

            if ids is not None:
                for marker_id, detected_corners in zip(ids.flatten(), corners):
                    marker_id = int(marker_id)
                    image_corners = detected_corners.reshape(4, 2)
                    label = f"ID {marker_id}"
                    if board_result is not None:
                        _, pnp = board_result
                        board_corners = np.array([
                            estimator.project_point_to_board(
                                pnp, point, frame.shape, VISION.marker_height_m
                            )
                            for point in image_corners
                        ])
                        markers.append((marker_id, board_corners, False))
                        x, y = board_corners.mean(axis=0)
                        forward = (board_corners[0] + board_corners[1]) / 2 - (x, y)
                        angle = np.degrees(np.arctan2(-forward[1], forward[0]))
                        label += f" ({x:.2f}, {-y:.2f}) m"
                        positions.append(f"{label} {angle:.0f} deg")

                    cv2.polylines(frame, [image_corners.astype(np.int32)], True, (0, 255, 0), 2)
                    cv2.putText(frame, label, tuple(image_corners.mean(axis=0).astype(int)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

            vision_done = time.monotonic()
            cv2.imshow("Camera", frame)
            if vision_done - last_plot >= 0.1:
                cv2.imshow("Board", plotter.render(markers))
                last_plot = vision_done
            plot_done = time.monotonic()

            frames += 1
            read_time += read_done - started
            vision_time += vision_done - read_done
            plot_time += plot_done - vision_done
            if plot_done - stats_at >= 1.0:
                print(
                    f"{frames / (plot_done - stats_at):.1f} FPS | "
                    f"read {read_time / frames * 1000:.1f} ms | "
                    f"detect {vision_time / frames * 1000:.1f} ms | "
                    f"display {plot_time / frames * 1000:.1f} ms | "
                    f"board {'yes' if board_result else 'no'} | "
                    f"{', '.join(positions) or 'no markers'}",
                    flush=True,
                )
                stats_at = plot_done
                frames = read_time = vision_time = plot_time = 0.0

            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
