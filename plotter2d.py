import cv2
import numpy as np
from pathlib import Path


# Pastel marker fills. Values are stored in OpenCV's BGR order.
MARKER_COLORS = (
    (173, 173, 255),  # coral
    (165, 214, 255),  # peach
    (182, 255, 253),  # soft yellow
    (191, 255, 202),  # mint
    (255, 246, 155),  # aqua
    (255, 196, 160),  # powder blue
    (255, 178, 189),  # lavender
)


class BoardPlotter2D:
    def __init__(self, board_config, marker_dictionary, margin=0.05, width_px=800):
        self.board_config = board_config
        self.marker_dictionary = marker_dictionary
        self.board_width, self.board_height = board_config.get_board_dimensions()
        print_width, print_height = board_config.get_print_dimensions()

        world_width = max(print_width, self.board_width + 2 * margin)
        world_height = max(print_height, self.board_height + 2 * margin)
        self.scale = width_px / world_width
        self.width = width_px
        self.height = round(world_height * self.scale)
        self.marker_sizes = {}
        self.marker_images = {}
        self.marker_source = np.array(
            [[0, 0], [127, 0], [127, 127], [0, 127]], np.float32
        )
        self.marker_mask = np.full((128, 128), 255, np.uint8)
        self.background = np.full((self.height, self.width, 3), 255, np.uint8)

        image_path = Path(board_config.image_path)
        if image_path.is_file():
            board_image = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
            if board_image is None:
                raise OSError(f"Could not load board image: {image_path}")
            if board_image.ndim == 2:
                board_image = cv2.cvtColor(board_image, cv2.COLOR_GRAY2BGR)

            target_size = (
                round(print_width * self.scale),
                round(print_height * self.scale),
            )
            interpolation = (
                cv2.INTER_AREA
                if board_image.shape[1] > target_size[0]
                or board_image.shape[0] > target_size[1]
                else cv2.INTER_LINEAR
            )
            board_image = cv2.resize(board_image, target_size,
                                     interpolation=interpolation)
        else:
            board_image = board_config.generate_image(
                width_px=round(self.board_width * self.scale)
            )
        self._paste_center(board_image)

        half_w = round(print_width * self.scale / 2)
        half_h = round(print_height * self.scale / 2)
        center = (self.width // 2, self.height // 2)
        cv2.rectangle(
            self.background,
            (center[0] - half_w, center[1] - half_h),
            (center[0] + half_w, center[1] + half_h),
            (0, 0, 255),
            2,
        )

    def _paste_center(self, image):
        height, width = image.shape[:2]
        x = (self.width - width) // 2
        y = (self.height - height) // 2
        region = self.background[y:y + height, x:x + width]

        if image.shape[2] == 4:
            alpha = image[:, :, 3:4].astype(np.float32) / 255
            region[:] = image[:, :, :3] * alpha + region * (1 - alpha)
        else:
            region[:] = image

    def _to_pixels(self, points):
        pixels = np.asarray(points, dtype=np.float32) * self.scale
        pixels += (self.width / 2, self.height / 2)
        return pixels.astype(np.float32)

    def _draw_marker(self, canvas, marker_id, corners, is_tracked):
        edges = np.roll(corners, -1, axis=0) - corners
        measured_size = float(np.median(np.linalg.norm(edges, axis=1)))
        if not is_tracked:
            self.marker_sizes[marker_id] = round(measured_size / 0.005) * 0.005
        size = self.marker_sizes.get(marker_id, measured_size)
        if size <= 0:
            return

        center = corners.mean(axis=0)
        direction = corners[1] - corners[0]
        norm = np.linalg.norm(direction)
        if norm == 0:
            return
        right = direction / norm * (size / 2)
        down = np.array([-right[1], right[0]], dtype=np.float32)
        square = np.array([
            center - right - down,
            center + right - down,
            center + right + down,
            center - right + down,
        ], dtype=np.float32)

        destination = self._to_pixels(square)
        x0 = max(0, int(np.floor(destination[:, 0].min())))
        y0 = max(0, int(np.floor(destination[:, 1].min())))
        x1 = min(self.width, int(np.ceil(destination[:, 0].max())) + 1)
        y1 = min(self.height, int(np.ceil(destination[:, 1].max())) + 1)
        if x1 <= x0 or y1 <= y0:
            return

        marker = self.marker_images.get(marker_id)
        if marker is None:
            text = str(marker_id)
            fill_color = MARKER_COLORS[marker_id % len(MARKER_COLORS)]
            marker = np.full((128, 128, 3), fill_color, np.uint8)
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 2.55 if len(text) == 1 else 2.1
            thickness = 7
            (text_width, text_height), baseline = cv2.getTextSize(
                text, font, font_scale, thickness
            )
            # Fit IDs of any length inside the square without changing their
            # aspect ratio. Two-digit ArUco IDs retain the full 2.1 scale.
            fit = min(1.0, 108 / text_width, 90 / (text_height + baseline))
            font_scale *= fit
            (text_width, text_height), baseline = cv2.getTextSize(
                text, font, font_scale, thickness
            )
            text_x = (128 - text_width) // 2
            # Center the complete text bounds, including OpenCV's baseline.
            text_y = round(64 + (text_height - baseline) / 2)
            cv2.putText(
                marker,
                text,
                (text_x, text_y),
                font,
                font_scale,
                (0, 0, 0),
                thickness,
                cv2.LINE_AA,
            )
            underline_y = min(116, text_y + 11)
            cv2.line(
                marker,
                (max(10, text_x - 4), underline_y),
                (min(117, text_x + text_width + 4), underline_y),
                (0, 0, 0),
                5,
                cv2.LINE_AA,
            )
            self.marker_images[marker_id] = marker

        local_destination = destination - (x0, y0)
        transform = cv2.getPerspectiveTransform(
            self.marker_source, local_destination.astype(np.float32)
        )
        roi_size = (x1 - x0, y1 - y0)
        warped = cv2.warpPerspective(
            marker, transform, roi_size,
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_REPLICATE,
        )
        mask = cv2.warpPerspective(
            self.marker_mask,
            transform,
            roi_size,
            flags=cv2.INTER_NEAREST,
        )
        region = canvas[y0:y1, x0:x1]
        region[mask > 0] = warped[mask > 0]

    def render(self, markers=()):
        """Render (id, board_corners, is_tracked) marker tuples."""
        canvas = self.background.copy()
        for marker_id, corners, is_tracked in markers:
            self._draw_marker(
                canvas,
                int(marker_id),
                np.asarray(corners, dtype=np.float32).reshape(4, 2),
                is_tracked,
            )
        return canvas


def _square_corners(center, size, heading):
    """Return marker corners for a Cartesian heading in radians.

    Heading zero points along +X. Positive angles turn counterclockwise in
    Cartesian coordinates, while board-image Y points downward. The heading
    points from the marker center toward the midpoint of its top edge.
    """
    center = np.asarray(center, dtype=np.float32)
    half = size / 2
    # Corner 0 -> corner 1 runs along the top edge. Rotate the heading 90
    # degrees clockwise to obtain that edge direction in board-image space.
    right = np.array([np.sin(heading), np.cos(heading)], dtype=np.float32) * half
    down = np.array([-right[1], right[0]], dtype=np.float32)
    return np.array([
        center - right - down,
        center + right - down,
        center + right + down,
        center - right + down,
    ], dtype=np.float32)


def _dummy_markers(plotter, elapsed, tracked=True):
    """Keep ID 49 centered while IDs 1-6 orbit at equal intervals."""
    marker_size = 0.09
    x_radius = max(marker_size, plotter.board_width / 2 - marker_size)
    y_radius = max(marker_size, plotter.board_height / 2 - marker_size)
    circle_radius = 0.72 * min(x_radius, y_radius)
    base_phase = 0.65 * elapsed
    markers = [(49, _square_corners((0.0, 0.0), marker_size, 0.0), tracked)]
    orbiting_count = len(MARKER_COLORS) - 1
    for marker_id in range(1, len(MARKER_COLORS)):
        phase = base_phase + (marker_id - 1) * 2 * np.pi / orbiting_count
        center = (
            circle_radius * np.cos(phase),
            -circle_radius * np.sin(phase),
        )
        heading = phase + np.pi / 2
        markers.append(
            (marker_id, _square_corners(center, marker_size, heading), tracked)
        )
    return markers


def _run_dummy_demo(plotter):
    """Animate dummy marker data until Escape, Q, or the window close button."""
    import time

    window_name = "BoardPlotter2D dummy test"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 600, round(600 * plotter.height / plotter.width))
    started = time.monotonic()
    first_frame = True

    try:
        while True:
            elapsed = time.monotonic() - started
            markers = _dummy_markers(plotter, elapsed, tracked=not first_frame)
            first_frame = False
            frame = plotter.render(markers)
            cv2.putText(
                frame,
                "ID 49: origin, 0 deg | IDs 1-6: equally spaced circle | "
                "Underline shows orientation | Q/Esc to exit",
                (12, 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                (40, 40, 40),
                1,
                cv2.LINE_AA,
            )
            cv2.imshow(window_name, frame)

            if cv2.waitKey(16) & 0xFF in (ord("q"), 27):
                break
            if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                break
    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyWindow(window_name)


if __name__ == "__main__":
    # vision_setup imports plotter2d. Register this already-loaded module under
    # that name so running this file directly does not create a second copy.
    import sys

    sys.modules.setdefault("plotter2d", sys.modules[__name__])
    from vision_setup import VISION

    _run_dummy_demo(VISION.plotter)
