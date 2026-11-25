import importlib.util
import json
from pathlib import Path
import socket
import time
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / 'robot_firmware/pico_w/pose_client.py'
spec = importlib.util.spec_from_file_location('pose_client', path)
pose_client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pose_client)


def packet(markers=None, **fields):
    result = dict(board_detected=True, markers=markers if markers is not None else
                  [dict(id=1, x=0.0, y=1.2, angle=90.0)], stream_id='one', frame_sequence=10,
                  frame_age_ms=0)
    result.update(fields)
    return json.dumps(result).encode()


class PoseTests(unittest.TestCase):
    def setUp(self):
        self.client = pose_client.PoseSubscriber('127.0.0.1')

    def tearDown(self):
        self.client.close()

    def test_missing_marker_and_missing_board_clear_pose(self):
        with patch.object(pose_client, 'ticks_ms', return_value=1000):
            self.client._accept(packet(), 1000)
            self.assertEqual(self.client.pose['x'], 0.0)
            self.client._accept(packet(markers=[dict(id=2, x=1, y=2, angle=3)]), 1000)
            self.assertIsNone(self.client.pose)
            self.assertEqual(self.client.reason, 'marker_not_visible')
            self.client._accept(packet(board_detected=False), 1000)
            self.assertEqual(self.client.reason, 'board_not_detected')

    def test_expiry_includes_camera_frame_age(self):
        self.client._accept(packet(frame_age_ms=400), 1000)
        with patch.object(pose_client, 'ticks_ms', return_value=1101):
            self.assertEqual(self.client.reason, 'stale_camera_frame')
            self.assertIsNone(self.client.pose)
        with patch.object(pose_client, 'ticks_ms', return_value=1501):
            self.assertEqual(self.client.reason, 'stale_telemetry')

    def test_reordering_and_stream_restart(self):
        self.client._accept(packet(), 1000)
        self.client._accept(packet(frame_sequence=9), 1001)
        self.assertEqual(self.client.reordered_packets, 1)
        self.assertEqual(self.client.last_packet_ms, 1000)
        self.client._accept(packet(stream_id='two', frame_sequence=0), 1002)
        self.assertEqual(self.client.frame_sequence, 0)

    def test_real_unicast_subscription_uses_ephemeral_receiving_socket(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.bind(('127.0.0.1', 0))
            server.settimeout(1)
            with pose_client.PoseSubscriber('127.0.0.1', subscription_port=server.getsockname()[1]) as client:
                client.poll()
                message, address = server.recvfrom(1024)
                self.assertEqual(message, b'POSE_SUBSCRIBE')
                self.assertEqual(address[1], client.local_port)
                server.sendto(packet(), address)
                deadline = time.monotonic() + 1
                while client.pose is None and time.monotonic() < deadline:
                    client.poll()
                    time.sleep(.001)
                self.assertEqual(client.pose['id'], 1)
                client.close()
                self.assertEqual(server.recvfrom(1024)[0], b'POSE_UNSUBSCRIBE')
