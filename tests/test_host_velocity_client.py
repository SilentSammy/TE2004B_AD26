import asyncio
import struct
import unittest
from host_velocity_client import DifferentialPWMClient
from robot_firmware.pico_w import ble_protocol as bp
from zumo_ble import BLETransport


def snapshot():
    fields = [0] * 31
    fields[13:18] = [1, 2, 3, 4, 5]
    fields[24] = 6600
    return struct.pack(bp.wire.SNAPSHOT_FORMAT, *fields)


class FakeTransport:
    def __init__(self):
        self.messages = []
        self.closed = False

    def request(self, op, payload=b'', timeout=1):
        self.messages.append((op, payload))
        if op == bp.wire.MOTORS:
            return payload
        if op == bp.wire.READ:
            return snapshot()
        if op == bp.STATUS:
            return bp.status_payload(struct.pack('<IIHH', 921600, 250, 31, 64), snapshot(), 2, 0)
        raise ValueError('unexpected command')

    def close(self):
        self.closed = True


class ClientTests(unittest.TestCase):
    def test_mixing_cache_and_close_stop(self):
        transport = FakeTransport()
        client = DifferentialPWMClient(transport=transport)
        client.set_velocity(.6, .2)
        client.set_velocity(.6, .2)
        self.assertEqual(len(transport.messages), 1)
        self.assertEqual(struct.unpack('<hh', transport.messages[0][1]), (2400, 4800))
        client.close()
        self.assertEqual(struct.unpack('<hh', transport.messages[-1][1]), (0, 0))
        self.assertTrue(transport.closed)

    def test_read_only_and_status_codec(self):
        transport = FakeTransport()
        client = DifferentialPWMClient(transport=transport, read_only=True)
        self.assertEqual(client.get_status()['hardware']['baud'], 921600)
        self.assertEqual(client.get_sensors()['line'], (1, 2, 3, 4, 5))
        with self.assertRaises(RuntimeError):
            client.set_pwm(0, 0)
        client.close()
        self.assertNotIn(bp.wire.MOTORS, [op for op, _ in transport.messages])

    def test_fragmented_notifications_complete_the_matching_request(self):
        async def check():
            transport = BLETransport.__new__(BLETransport)
            transport.parser = bp.wire.Parser()
            future = asyncio.get_running_loop().create_future()
            transport.pending = {7: future}
            packet = bp.wire.frame(bp.wire.MOTORS | 0x80, 7, struct.pack('<hh', 0, 0))
            for offset in range(0, len(packet), 3):
                transport._notification(None, bytearray(packet[offset:offset + 3]))
            self.assertEqual(await future, (bp.wire.MOTORS | 0x80, struct.pack('<hh', 0, 0)))
        asyncio.run(check())
