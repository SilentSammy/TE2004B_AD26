"""Versioned UDP pose telemetry with optional broadcast and reliable unicast."""

import json
import socket
import time


SUBSCRIBE = b"POSE_SUBSCRIBE"
UNSUBSCRIBE = b"POSE_UNSUBSCRIBE"
SUBSCRIBER_TTL = 5.0
MAX_SUBSCRIBERS = 256
MAX_DISCOVERY_MESSAGES_PER_SEND = 64


class TelemetryPublisher:
    """Publish current state, never queueing or retransmitting stale poses.

    Clients send ``POSE_SUBSCRIBE`` to data_port + 1 from the UDP socket on
    which they want telemetry. Renew once per second; registrations expire
    after five seconds.
    """

    def __init__(self, broadcast, port, subscription_port=None):
        self.destination = (broadcast, port) if broadcast else None
        self.subscription_port = port + 1 if subscription_port is None else subscription_port
        self._subscribers = {}
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.socket.bind(("", self.subscription_port))
            self.socket.setblocking(False)
            self.broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except BaseException:
            self.close()
            raise

    @property
    def subscriber_count(self):
        return len(self._subscribers)

    def _receive_subscriptions(self, now):
        for _ in range(MAX_DISCOVERY_MESSAGES_PER_SEND):
            try:
                message, address = self.socket.recvfrom(64)
            except BlockingIOError:
                break
            except (ConnectionResetError, ConnectionAbortedError):
                continue
            if message == SUBSCRIBE:
                if address in self._subscribers or len(self._subscribers) < MAX_SUBSCRIBERS:
                    self._subscribers[address] = now + SUBSCRIBER_TTL
            elif message == UNSUBSCRIBE:
                self._subscribers.pop(address, None)

    def send(self, packet):
        now = time.monotonic()
        self._receive_subscriptions(now)
        payload = json.dumps(packet, separators=(",", ":")).encode()
        for address, expires in list(self._subscribers.items()):
            if expires <= now:
                self._subscribers.pop(address, None)
                continue
            try:
                self.socket.sendto(payload, address)
            except OSError:
                pass
        if self.destination:
            try:
                self.broadcast_socket.sendto(payload, self.destination)
            except OSError as error:
                print(f"Telemetry broadcast failed: {error}", flush=True)

    def close(self):
        self.socket.close()
        self.broadcast_socket.close()

