import json
import socket
import threading
import time
import unittest
from host_velocity_client import DifferentialPWMClient, PROTOCOL


class ClientTransportTests(unittest.TestCase):
    def test_status_mixing_cached_heartbeat_and_final_stop_over_udp(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server.bind(('127.0.0.1', 0))
        server.settimeout(.02)
        messages = []
        finished = threading.Event()

        def serve():
            while not finished.is_set():
                try:
                    raw, address = server.recvfrom(4096)
                except (socket.timeout, ConnectionResetError):
                    continue
                message = json.loads(raw)
                messages.append(message)
                response = dict(ok=True, seq=message['seq'], session=message['session'],
                                protocol=PROTOCOL)
                if message.get('op') == 'status':
                    response.update(hardware={'baud': 921600}, hardware_pwm=[0, 0], battery_mv=6600)
                server.sendto(json.dumps(response).encode(), address)

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        client = DifferentialPWMClient('127.0.0.1', server.getsockname()[1])
        try:
            self.assertEqual(client.get_status()['hardware']['baud'], 921600)
            client.set_velocity(.6, .2)
            client.set_velocity(.6, .2)
            time.sleep(.03)
            client.close()
            time.sleep(.03)
            motors = [m for m in messages if 'l' in m]
            self.assertEqual((motors[0]['l'], motors[0]['r']), (2400, 4800))
            self.assertEqual(len(motors), 4)  # one update, three explicit final stops
            self.assertTrue(all((m['l'], m['r']) == (0, 0) for m in motors[-3:]))
            self.assertEqual(len({m['session'] for m in messages}), 1)
            self.assertEqual([m['seq'] for m in messages], sorted({m['seq'] for m in messages}))
        finally:
            if not client._closed:
                client.close()
            finished.set()
            worker.join(1)
            server.close()

    def test_missing_endpoint_fails_status_check(self):
        client = DifferentialPWMClient('127.0.0.1', 9)
        try:
            with self.assertRaises(TimeoutError):
                client.get_status(timeout=.05)
        finally:
            client.close()
