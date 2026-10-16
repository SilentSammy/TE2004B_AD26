import argparse
import json
import math
import socket
import time
from pathlib import Path

import cv2
import numpy as np

from marker_tracker import MarkerTracker
from vision_setup import DEFAULT_SETUP, VISION_SETUPS

DEFAULT_TELEMETRY_PORT = 5000


def load_marker_config(path):
    """Return validated appearance and height overrides; errors use defaults."""
    appearances, heights = {}, {}
    try:
        path = Path(path).resolve()
        with path.open(encoding="utf-8-sig") as file:
            entries = json.load(file)
        if not isinstance(entries, dict):
            raise ValueError("expected an object keyed by marker ID")
    except (OSError, UnicodeError, ValueError, RuntimeError, RecursionError) as error:
        print(f"Marker config unavailable; using defaults: {error}")
        return appearances, heights

    def number(value, minimum, inclusive=True):
        if type(value) not in (int, float):
            return False
        try:
            return math.isfinite(value) and (value >= minimum if inclusive else value > minimum)
        except OverflowError:
            return False

    for key, entry in entries.items():
        try:
            marker_id = int(key)
            if marker_id < 0 or not isinstance(entry, dict):
                raise ValueError("expected a nonnegative ID and an object")
        except (TypeError, ValueError):
            print(f"Ignoring invalid marker config entry: {key!r}")
            continue

        def ignored(field):
            print(f"Marker {marker_id}: invalid {field}; using its default")

        if "height_m" in entry:
            if number(entry["height_m"], 0):
                heights[marker_id] = entry["height_m"]
            else:
                ignored("height_m")
        style = {}
        if "text" in entry:
            text = entry["text"]
            if isinstance(text, str) and all(c == "\n" or " " <= c <= "~" for c in text):
                style["text"] = text
            else:
                ignored("text")
        if "color" in entry:
            color = entry["color"]
            if (isinstance(color, list) and len(color) == 3
                    and all(type(c) is int and 0 <= c <= 255 for c in color)):
                style["color"] = tuple(color)
            else:
                ignored("color")
        if "image" in entry:
            try:
                if not isinstance(entry["image"], str) or not entry["image"]:
                    raise ValueError("expected an image path")
                image_path = Path(entry["image"])
                if not image_path.is_absolute():
                    image_path = path.parent / image_path
                # Load now so a broken image cannot interrupt the tracking loop.
                image = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
                if (image is None or image.dtype not in (np.uint8, np.uint16)
                        or not (image.ndim == 2 or image.ndim == 3 and image.shape[2] in (3, 4))):
                    raise ValueError("unsupported image")
                style["image"] = image
            except (OSError, ValueError, cv2.error) as error:
                print(f"Marker {marker_id}: cannot load image; using label defaults: {error}")
        if "scale" in entry:
            if number(entry["scale"], 0, inclusive=False):
                style["scale"] = entry["scale"]
            else:
                ignored("scale")
        if style:
            appearances[marker_id] = style
    return appearances, heights


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--marker-config", type=Path,
        help="override the selected vision setup's marker config JSON",
    )
    parser.add_argument(
        "--setup",
        choices=VISION_SETUPS,
        help="vision setup (uses DEFAULT_SETUP from vision_setup.py if omitted)",
    )
    parser.add_argument(
        "--broadcast",
        default=None,
        help="telemetry broadcast address; telemetry is not sent if omitted",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_TELEMETRY_PORT,
        help=f"telemetry UDP port (default: {DEFAULT_TELEMETRY_PORT})",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=10.0,
        help="telemetry send rate in Hz (default: 10)",
    )
    args = parser.parse_args()
    setup = VISION_SETUPS[args.setup] if args.setup is not None else DEFAULT_SETUP

    if args.broadcast is None:
        print("No --broadcast address given; telemetry will not be sent.")
    telemetry_interval = 1 / args.rate if args.rate > 0 else float("inf")

    camera = setup.camera
    estimator = setup.board_estimator
    detector = setup.detector
    plotter = setup.plotter
    config_path = args.marker_config if args.marker_config is not None else setup.marker_config_path
    appearances, marker_heights = load_marker_config(config_path)
    plotter.marker_overrides = {
        marker_id: {**plotter.marker_overrides.get(marker_id, {}), **style}
        for marker_id, style in (plotter.marker_overrides | appearances).items()
    }
    tracker = MarkerTracker()

    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    cv2.namedWindow("Camera", cv2.WINDOW_NORMAL)
    cv2.namedWindow("Board", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Board", 400, round(400 * plotter.height / plotter.width))

    stats_at = last_plot = last_telemetry = time.monotonic()
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
            tracked_markers = tracker.update(frame, corners, ids)
            markers = []
            positions = []
            telemetry_markers = []

            for marker_id, image_corners, is_tracked in tracked_markers:
                if board_result is not None:
                    _, pnp = board_result
                    marker_height = marker_heights.get(marker_id, setup.marker_height_m)
                    board_corners = np.array([
                        estimator.project_point_to_board(
                            pnp, point, frame.shape, marker_height
                        )
                        for point in image_corners
                    ])
                    markers.append((marker_id, board_corners, False))
                    x, y = board_corners.mean(axis=0)
                    # Heading is the outward normal of the marker's top edge.
                    # The reported frame is Cartesian: +X is 0 degrees, +Y is
                    # 90 degrees, and positive rotation is counterclockwise.
                    forward = (board_corners[0] + board_corners[1]) / 2 - (x, y)
                    angle = np.degrees(np.arctan2(-forward[1], forward[0]))
                    positions.append(
                        f"ID {marker_id} ({x:.2f}, {-y:.2f}) m {angle:.0f} deg"
                    )
                    telemetry_markers.append(
                        {"id": marker_id, "x": round(x, 3), "y": round(-y, 3), "angle": round(angle, 0)}
                    )

                color = (0, 255, 255) if is_tracked else (0, 255, 0)
                cv2.polylines(frame, [image_corners.astype(np.int32)], True, color, 2)
                marker_text = str(marker_id)
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.6
                thickness = 2
                (text_width, text_height), baseline = cv2.getTextSize(
                    marker_text, font, font_scale, thickness
                )
                center_x, center_y = image_corners.mean(axis=0).astype(int)
                text_at = (
                    center_x - text_width // 2,
                    center_y + (text_height - baseline) // 2,
                )
                cv2.putText(
                    frame, marker_text, text_at, font, font_scale,
                    color, thickness, cv2.LINE_AA,
                )

            vision_done = time.monotonic()
            cv2.imshow("Camera", frame)
            if vision_done - last_plot >= 0.1:
                cv2.imshow("Board", plotter.render(markers))
                last_plot = vision_done
            if args.broadcast is not None and vision_done - last_telemetry >= telemetry_interval:
                telemetry = {
                    "timestamp": round(time.time(), 3),
                    "board_detected": board_result is not None,
                    "markers": telemetry_markers,
                }
                udp.sendto(json.dumps(telemetry).encode(), (args.broadcast, args.port))
                last_telemetry = vision_done
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
        udp.close()
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
