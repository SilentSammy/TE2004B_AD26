import cv2
import numpy as np


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
            marker = cv2.aruco.generateImageMarker(
                self.marker_dictionary, marker_id, 128
            )
            marker = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
            self.marker_images[marker_id] = marker

        local_destination = destination - (x0, y0)
        transform = cv2.getPerspectiveTransform(
            self.marker_source, local_destination.astype(np.float32)
        )
        roi_size = (x1 - x0, y1 - y0)
        warped = cv2.warpPerspective(
            marker, transform, roi_size,
            flags=cv2.INTER_NEAREST,
        )
        mask = cv2.warpPerspective(
            self.marker_mask,
            transform,
            roi_size,
            flags=cv2.INTER_NEAREST,
        )
        region = canvas[y0:y1, x0:x1]
        region[mask > 0] = warped[mask > 0]

        label_at = self._to_pixels([center])[0].astype(int)
        cv2.putText(
            canvas,
            f"ID {marker_id} | {size * 100:.1f} cm",
            (label_at[0] + 5, label_at[1] - 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 0, 255),
            1,
            cv2.LINE_AA,
        )

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
