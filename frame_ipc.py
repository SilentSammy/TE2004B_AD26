import json
import socket
import time
from multiprocessing import shared_memory

import numpy as np


FRAME_PORT = 42004
FRAME_SHAPE = (480, 640, 3)
FRAME_DTYPE = np.uint8


class FramePublisher:
    def __init__(self, port=FRAME_PORT):
        size = int(np.prod(FRAME_SHAPE) * np.dtype(FRAME_DTYPE).itemsize)
        self.blocks = [
            shared_memory.SharedMemory(create=True, size=size)
            for _ in range(2)
        ]
        self.frames = [
            np.ndarray(FRAME_SHAPE, dtype=FRAME_DTYPE, buffer=block.buf)
            for block in self.blocks
        ]
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.target = ("127.0.0.1", port)
        self.sequence = 0

    def publish(self, frame, capture_time_ns=None):
        if frame.shape != FRAME_SHAPE or frame.dtype != FRAME_DTYPE:
            raise ValueError(
                f"Expected {FRAME_SHAPE} {FRAME_DTYPE}, got {frame.shape} {frame.dtype}"
            )

        index = self.sequence % 2
        np.copyto(self.frames[index], frame)
        message = json.dumps({
            "version": 1,
            "names": [block.name for block in self.blocks],
            "index": index,
            "sequence": self.sequence,
            "capture_time_ns": capture_time_ns or time.time_ns(),
            "shape": FRAME_SHAPE,
        }, separators=(",", ":")).encode()
        self.socket.sendto(message, self.target)
        self.sequence += 1

    def close(self):
        self.frames.clear()
        for block in self.blocks:
            block.close()
            block.unlink()
        self.blocks.clear()
        self.socket.close()


class FrameSubscriber:
    def __init__(self, port=FRAME_PORT):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("127.0.0.1", port))
        self.blocks = []
        self.frames = []
        self.names = None

    def _attach(self, names, shape):
        if names == self.names:
            return
        self._close_blocks()
        self.blocks = [shared_memory.SharedMemory(name=name) for name in names]
        self.frames = [
            np.ndarray(shape, dtype=FRAME_DTYPE, buffer=block.buf)
            for block in self.blocks
        ]
        self.names = names

    def read(self, timeout=1.0):
        self.socket.settimeout(timeout)
        try:
            data, _ = self.socket.recvfrom(1024)
        except socket.timeout:
            return False, None, None

        self.socket.setblocking(False)
        while True:
            try:
                data, _ = self.socket.recvfrom(1024)
            except BlockingIOError:
                break

        message = json.loads(data)
        if message.get("version") != 1:
            return False, None, None

        shape = tuple(message["shape"])
        self._attach(message["names"], shape)
        frame = self.frames[message["index"]].copy()
        return True, frame, message

    def _close_blocks(self):
        self.frames.clear()
        for block in self.blocks:
            block.close()
        self.blocks.clear()

    def close(self):
        self._close_blocks()
        self.socket.close()

