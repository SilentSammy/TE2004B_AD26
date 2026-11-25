"""Optional non-blocking ArUco GPS unicast subscriber for MicroPython apps."""
import json
import socket
import time
import math

try:
    ticks_ms, ticks_diff = time.ticks_ms, time.ticks_diff
except AttributeError:  # Also usable by host-side transport tests.
    def ticks_ms():
        return int(time.monotonic() * 1000)

    def ticks_diff(a, b):
        return a - b


class PoseSubscriber:
    """Retain one marker's current pose; never treats missing/stale data as valid."""
    def __init__(self, server, marker_id=1, port=5000, subscription_port=None, stale_ms=500):
        if type(marker_id) is not int or marker_id < 0:
            raise ValueError('marker_id must be a nonnegative integer')
        if type(port) is not int or not 1 <= port <= 65534 or type(stale_ms) is not int or stale_ms <= 0:
            raise ValueError('invalid data port or stale_ms')
        subscription_port = port + 1 if subscription_port is None else subscription_port
        if type(subscription_port) is not int or not 1 <= subscription_port <= 65535:
            raise ValueError('invalid subscription port')
        self.server = socket.getaddrinfo(server, subscription_port, socket.AF_INET, socket.SOCK_DGRAM)[0][-1]
        self.marker_id, self.port, self.stale_ms = marker_id, port, stale_ms
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # The server replies to this receiving socket, not fixed port 5000.
            self.socket.bind(('0.0.0.0', 0))
            self.local_port = self.socket.getsockname()[1] if hasattr(self.socket, 'getsockname') else None
            self.socket.setblocking(False)
        except BaseException:
            self.socket.close()
            raise
        self.closed = False
        self.last_renewal_ms = None
        self.last_packet_ms = self.last_seen_ms = None
        self.board_detected = False
        self.frame_age_ms = 0
        self.stream_id = self.frame_sequence = None
        self._pose = None
        self.packets = self.invalid_packets = self.reordered_packets = self.send_errors = 0

    def _accept(self, raw, now):
        try:
            message = json.loads(raw)
            if not isinstance(message, dict) or not isinstance(message.get('markers'), list):
                raise ValueError('invalid pose packet')
            stream, sequence = message.get('stream_id'), message.get('frame_sequence')
            if type(sequence) is not int or sequence < 0:
                sequence = None
            if (stream is not None and stream == self.stream_id and sequence is not None
                    and self.frame_sequence is not None and sequence < self.frame_sequence):
                self.reordered_packets += 1
                return
            source_age = message.get('frame_age_ms', 0)
            if type(source_age) not in (int, float) or not math.isfinite(source_age) or source_age < 0:
                raise ValueError('invalid source frame age')
            pose = None
            board_detected = message.get('board_detected') is True
            if board_detected:
                for marker in message['markers']:
                    if (not isinstance(marker, dict) or type(marker.get('id')) is not int
                            or marker.get('id') != self.marker_id):
                        continue
                    values = [marker.get(key) for key in ('x', 'y', 'angle')]
                    if not all(type(v) in (int, float) and math.isfinite(v) for v in values):
                        raise ValueError('invalid marker coordinates')
                    pose = dict(id=self.marker_id, x=values[0], y=values[1], angle=values[2],
                                timestamp=message.get('timestamp'), frame_sequence=sequence)
                    break
            self.packets += 1
            self.last_packet_ms = now
            self.board_detected = board_detected
            self.frame_age_ms = source_age
            self.stream_id, self.frame_sequence = stream, sequence
            self._pose = pose
            if pose is not None:
                self.last_seen_ms = now
        except (ValueError, TypeError, OverflowError):
            self.invalid_packets += 1

    def poll(self, max_packets=4):
        """Renew once per second and drain bounded work without blocking control."""
        if self.closed:
            return None
        now = ticks_ms()
        if self.last_renewal_ms is None or ticks_diff(now, self.last_renewal_ms) >= 1000:
            self.last_renewal_ms = now
            try:
                self.socket.sendto(b'POSE_SUBSCRIBE', self.server)
            except OSError:
                self.send_errors += 1
        for _ in range(max_packets):
            try:
                raw, sender = self.socket.recvfrom(8193)
            except OSError:
                break
            if sender != self.server:
                continue
            if len(raw) > 8192:
                self.invalid_packets += 1
                continue
            self._accept(raw, ticks_ms())
        return self.pose

    @property
    def reason(self):
        if self.closed:
            return 'closed'
        if self.last_packet_ms is None:
            return 'no_telemetry'
        age = ticks_diff(ticks_ms(), self.last_packet_ms)
        if age > self.stale_ms:
            return 'stale_telemetry'
        if not self.board_detected:
            return 'board_not_detected'
        if self.frame_age_ms + age > self.stale_ms:
            return 'stale_camera_frame'
        if self._pose is None:
            return 'marker_not_visible'
        return None

    @property
    def pose(self):
        return self._pose if self.reason is None else None

    def status(self):
        now = ticks_ms()
        return dict(enabled=not self.closed, server=self.server[0], marker_id=self.marker_id,
                    data_port=self.port, subscription_port=self.server[1], local_port=self.local_port,
                    packets=self.packets, invalid_packets=self.invalid_packets,
                    reordered_packets=self.reordered_packets, subscription_errors=self.send_errors,
                    camera_frame_age_ms=self.frame_age_ms, frame_sequence=self.frame_sequence,
                    feed_age_ms=None if self.last_packet_ms is None else ticks_diff(now, self.last_packet_ms),
                    marker_age_ms=None if self.last_seen_ms is None else ticks_diff(now, self.last_seen_ms),
                    reason=self.reason, pose=self.pose)

    def close(self):
        if not self.closed:
            try:
                self.socket.sendto(b'POSE_UNSUBSCRIBE', self.server)
            except OSError:
                pass
            self.socket.close()
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
