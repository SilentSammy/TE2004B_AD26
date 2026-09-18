import json
import socket
import time


POSE_PORT = 42005
SUBSCRIBE = b"POSE_SUBSCRIBE_V1"


class PosePublisher:
    def __init__(self, port=POSE_PORT, lease_seconds=3.0):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("", port))
        self.socket.setblocking(False)
        self.lease_seconds = lease_seconds
        self.subscribers = {}
        self.sequence = 0

    def publish(self, board_visible, poses):
        now = time.monotonic()

        while True:
            try:
                data, address = self.socket.recvfrom(256)
            except OSError:
                break
            if data == SUBSCRIBE:
                self.subscribers[address] = now + self.lease_seconds

        self.subscribers = {
            address: expiry
            for address, expiry in self.subscribers.items()
            if expiry > now
        }
        self.sequence += 1
        message = json.dumps({
            "version": 1,
            "type": "poses",
            "sequence": self.sequence,
            "sent_time_ns": time.time_ns(),
            "board_visible": board_visible,
            "poses": poses,
        }, separators=(",", ":")).encode()

        for address in self.subscribers:
            try:
                self.socket.sendto(message, address)
            except OSError:
                pass

    def close(self):
        self.socket.close()


class PoseSubscriber:
    def __init__(self, host="127.0.0.1", port=POSE_PORT, stale_seconds=0.3):
        self.server = (host, port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("", 0))
        self.socket.setblocking(False)
        self.stale_seconds = stale_seconds
        self.last_subscription = 0.0
        self.last_received = 0.0
        self.latest = None

    def receive_latest(self):
        now = time.monotonic()
        if now - self.last_subscription >= 1.0:
            try:
                self.socket.sendto(SUBSCRIBE, self.server)
            except OSError:
                pass
            self.last_subscription = now

        while True:
            try:
                data, _ = self.socket.recvfrom(65535)
            except OSError:
                break
            try:
                message = json.loads(data)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if message.get("version") == 1 and message.get("type") == "poses":
                self.latest = message
                self.last_received = now

        if now - self.last_received > self.stale_seconds:
            return None
        return self.latest

    def close(self):
        self.socket.close()
