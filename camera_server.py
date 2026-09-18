import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

import vision_setup
from frame_ipc import FRAME_SHAPE, FramePublisher


HTTP_PORT = 8081
VIDEO_FPS = 15
JPEG_QUALITY = 80
PROCESS_NAME = "Camera Server"


class JPEGStream:
    def __init__(self):
        self.condition = threading.Condition()
        self.jpeg = None
        self.sequence = 0
        self.closed = False

    def update(self, frame):
        success, encoded = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
        )
        if not success:
            return
        with self.condition:
            self.jpeg = encoded.tobytes()
            self.sequence += 1
            self.condition.notify_all()

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()


class StreamHandler(BaseHTTPRequestHandler):
    stream = None

    def do_GET(self):
        if self.path == "/":
            body = b'<img src="/video.mjpg">'
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path != "/video.mjpg":
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header(
            "Content-Type", "multipart/x-mixed-replace; boundary=frame"
        )
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        last_sequence = -1
        try:
            while True:
                with self.stream.condition:
                    self.stream.condition.wait_for(
                        lambda: self.stream.sequence != last_sequence
                        or self.stream.closed
                    )
                    if self.stream.closed:
                        return
                    jpeg = self.stream.jpeg
                    last_sequence = self.stream.sequence
                self.wfile.write(
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    + f"Content-Length: {len(jpeg)}\r\n\r\n".encode()
                    + jpeg
                    + b"\r\n"
                )
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, _format, *_args):
        pass


def main():
    camera = vision_setup.VISION.camera
    jpeg_stream = JPEGStream()
    StreamHandler.stream = jpeg_stream
    frames = None
    server = None

    try:
        frames = FramePublisher()
        server = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), StreamHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        last_jpeg = 0.0
        host = socket.gethostname()
        print(
            f"[{PROCESS_NAME}] Video: http://{host}:{HTTP_PORT}/video.mjpg",
            flush=True,
        )
        while camera.isOpened():
            success, frame = camera.read()
            if not success:
                break
            if frame.shape != FRAME_SHAPE:
                frame = cv2.resize(frame, (FRAME_SHAPE[1], FRAME_SHAPE[0]))

            frames.publish(frame, time.time_ns())
            now = time.monotonic()
            if now - last_jpeg >= 1 / VIDEO_FPS:
                jpeg_stream.update(frame)
                last_jpeg = now
    except KeyboardInterrupt:
        pass
    finally:
        jpeg_stream.close()
        if server is not None:
            server.shutdown()
            server.server_close()
        if frames is not None:
            frames.close()
        camera.release()


if __name__ == "__main__":
    main()
