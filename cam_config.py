"""Camera configuration, direct capture, and local stream consumption."""

import copy
from pathlib import Path

import cv2
import numpy as np
import threading
import time

from frame_stream import CameraStreamError, FileMutex, SharedFrameReader, default_stream_dir, service_running

def rotate_intrinsics(rotation, K, image_size):
    """Rotate camera intrinsics for rotated image.
    
    Args:
        rotation: cv2.ROTATE_* constant
        K: 3x3 intrinsic matrix
        image_size: (height, width) of original image before rotation
        
    Returns:
        K_rotated: Rotated intrinsic matrix
    """
    h, w = image_size
    K_rot = K.copy()
    
    if rotation == cv2.ROTATE_90_CLOCKWISE:
        # (h, w) -> (w, h)
        # (x, y) -> (h - y, x)
        K_rot[0, 2] = h - K[1, 2]  # new_cx = h - old_cy
        K_rot[1, 2] = K[0, 2]       # new_cy = old_cx
        
    elif rotation == cv2.ROTATE_90_COUNTERCLOCKWISE:
        # (h, w) -> (w, h)
        # (x, y) -> (y, w - x)
        K_rot[0, 2] = K[1, 2]       # new_cx = old_cy
        K_rot[1, 2] = w - K[0, 2]  # new_cy = w - old_cx
        
    elif rotation == cv2.ROTATE_180:
        # (h, w) -> (h, w)
        # (x, y) -> (w - x, h - y)
        K_rot[0, 2] = w - K[0, 2]  # new_cx = w - old_cx
        K_rot[1, 2] = h - K[1, 2]  # new_cy = h - old_cy
    
    return K_rot

# TODO: for cams such as droidcam, where we might need to rotate the frame, we should specify the unrotated intrinsics, then if user requires rotation, we can compute the new intrinsics accordingly.
class Camera:
    """Camera configuration with intrinsics and frame acquisition."""
    
    def __init__(self, K, D, frame_getter, rotation=None, image_shape_hw=None,
                 device_candidates=None):
        """Initialize camera.
        
        Args:
            K: Camera intrinsic matrix
            D: Distortion coefficients
            frame_getter: Callable that returns a frame
            rotation: Optional cv2.ROTATE_* constant to apply to frames
            image_shape_hw: Optional (height, width) tuple. Required if rotation is specified.
        """
        # Validate that rotation and image_shape_hw are provided together
        if (rotation is None) != (image_shape_hw is None):
            raise ValueError("rotation and image_shape_hw must both be provided or both be None")
        
        self.frame_getter = frame_getter
        self.device_candidates = device_candidates
        self.rotation = rotation
        self.D = D  # Distortion coefficients don't change (radially symmetric)
        self._released = False
        
        # Compute rotated intrinsics if rotation specified
        if rotation is not None:
            self.K = rotate_intrinsics(rotation, K, image_shape_hw)
        else:
            self.K = K
    
    def open_capture(self, width=None, height=None, fps=None):
        """Open original, unrotated device frames for a streaming publisher.

        Rotation stays with consumers, together with their calibrated intrinsics.
        The publisher must acquire the camera ownership lock before calling this.
        """
        if self.device_candidates is None:
            raise CameraStreamError("This camera setup does not declare a local capture device")
        return LatestCamera(self.device_candidates, width, height, fps)

    def get_frame(self):
        """Get frame from frame_getter."""
        if self._released:
            return None

        frame = self.frame_getter()
        if frame is not None and self.rotation is not None:
            frame = cv2.rotate(frame, self.rotation)
        return frame

    def read(self):
        """Return a frame using the cv2.VideoCapture interface."""
        frame = self.get_frame()
        return frame is not None, frame

    def isOpened(self):
        """Return whether this camera has not been released."""
        return not self._released

    def release(self):
        """Release the underlying source when it supports release()."""
        configured_source = getattr(self.frame_getter, "source", None)
        if configured_source is not None and hasattr(configured_source, "release"):
            configured_source.release()
        else:
            source = getattr(self.frame_getter, "cap", None)
            if source is not None and hasattr(source, "release"):
                source.release()
        self._released = True


def device_value(value):
    return int(value) if str(value).isdigit() else str(value)


class LatestCamera:
    """One capture thread; consumers receive the latest frame, never a FIFO."""

    def __init__(self, devices=(1, 0), width=None, height=None, fps=None):
        self.cap = None
        for device in devices:
            cap = cv2.VideoCapture(device_value(device))
            if cap.isOpened():
                self.cap, self.device = cap, str(device)
                break
            cap.release()
        if self.cap is None:
            raise CameraStreamError(f"Could not open camera; tried {tuple(devices)}")
        if width is not None:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if fps is not None:
            self.cap.set(cv2.CAP_PROP_FPS, fps)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.condition = threading.Condition()
        self.frame = None
        self._sequence = 0
        self.last_sequence = self.last_capture_ns = 0
        self.closed = False
        self.thread = threading.Thread(target=self._capture, daemon=True)
        self.thread.start()

    def _capture(self):
        try:
            while not self.closed:
                success, image = self.cap.read()
                captured = time.perf_counter_ns()
                if not success:
                    break
                with self.condition:
                    self.frame, self._captured = image, captured
                    self._sequence += 1
                    self.condition.notify_all()
        finally:
            with self.condition:
                self.closed = True
                self.condition.notify_all()

    def read(self):
        with self.condition:
            self.condition.wait_for(
                lambda: self._sequence != self.last_sequence or self.closed, timeout=1)
            if self._sequence == self.last_sequence:
                return None
            self.last_sequence, self.last_capture_ns = self._sequence, self._captured
            return self.frame

    def release(self):
        self.closed = True
        with self.condition:
            self.condition.notify_all()
        # Normal capture should finish before destroying its OpenCV handle.
        self.thread.join(timeout=2)
        self.cap.release()
        if self.thread.is_alive():
            self.thread.join(timeout=1)


class CameraInput:
    def __init__(self, devices=(1, 0), mode="auto", directory=None):
        self.directory = Path(directory or default_stream_dir())
        self.owner = None
        self.source = None
        if mode == "stream" or (mode == "auto" and service_running(self.directory)):
            self.source = SharedFrameReader(self.directory)
            source_info = self.source.info.get("source", {})
            if source_info.get("kind") == "camera" and str(source_info.get("device")) not in map(str, devices):
                self.source.release()
                raise CameraStreamError("Camera service uses a different device from this vision setup")
            self.mode = "stream"
        else:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.owner = FileMutex(self.directory / "owner.lock")
            if not self.owner.acquire(0):
                self.owner.close()
                self.owner = None
                raise CameraStreamError("A camera service or direct reader already owns this camera")
            try:
                self.source = LatestCamera(devices)
            except BaseException:
                self.owner.close()
                self.owner = None
                raise
            self.mode = "direct"

    @property
    def last_capture_ns(self):
        return self.source.last_capture_ns

    @property
    def sequence(self):
        return self.source.sequence if self.mode == "stream" else self.source.last_sequence

    def read(self):
        return self.source.read()

    def release(self):
        try:
            if self.source is not None:
                self.source.release()
        finally:
            if self.owner is not None:
                self.owner.close()
                self.owner = None


def camera_for_setup(template, mode="auto", directory=None):
    """Preserve calibration/rotation while replacing only frame acquisition."""
    devices = getattr(template, "device_candidates", None)
    if devices is None:
        if mode == "stream":
            raise CameraStreamError("This camera setup does not declare a local capture device")
        return template, None
    source = CameraInput(devices, mode, directory)

    def getter():
        return source.read()

    getter.source = source  # Existing Camera.release() owns its source cleanup.
    camera = copy.copy(template)
    camera.frame_getter, camera._released = getter, False
    return camera, source
