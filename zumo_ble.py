"""Thread-owned asyncio BLE connection; concurrent command/sensor RPCs share it."""
import asyncio
import concurrent.futures
import threading
from robot_firmware.pico_w import ble_protocol as bp


async def scan(timeout=5.0):
    from bleak import BleakScanner
    results = await BleakScanner.discover(timeout=timeout, return_adv=True, service_uuids=[bp.SERVICE_UUID])
    return [device for device, adv in results.values()
            if bp.SERVICE_UUID in [uuid.lower() for uuid in adv.service_uuids]]


class BLETransport:
    def __init__(self, device='zumo1'):
        self.loop = asyncio.new_event_loop()
        self.client = None
        self.pending = {}
        self.sequence = 0
        self.parser = bp.wire.Parser()
        self.thread = threading.Thread(target=self._run, name='zumo-ble', daemon=True)
        self.thread.start()
        try:
            self.call(self._connect(device), 35)
        except BaseException:
            self.close()
            raise

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
        tasks = asyncio.all_tasks(self.loop)
        for task in tasks:
            task.cancel()
        if tasks:
            self.loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
        self.loop.close()

    def call(self, coroutine, timeout):
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise TimeoutError('BLE operation timed out') from None

    async def _connect(self, device):
        from bleak import BleakClient, BleakScanner
        if isinstance(device, str):
            identifier = device.casefold()
            device = await BleakScanner.find_device_by_filter(
                lambda d, a: identifier in (d.address.casefold(), (a.local_name or d.name or '').casefold()),
                timeout=8, service_uuids=[bp.SERVICE_UUID])
            if device is None:
                raise ConnectionError('BLE robot not found; power it on and enable laptop Bluetooth')
        self.device = device
        self.write_lock = asyncio.Lock()
        self.client = BleakClient(device, disconnected_callback=self._disconnected,
                                  timeout=15, winrt={'use_cached_services': False})
        await asyncio.wait_for(self.client.connect(), 18)
        await self.client.start_notify(bp.TX_UUID, self._notification)

    def _disconnected(self, _):
        for future in list(self.pending.values()):
            if not future.done():
                future.set_exception(ConnectionError('BLE disconnected; motors stop automatically'))

    def _notification(self, _, data):
        self.parser.feed(data)
        while True:
            message = self.parser.pop()
            if message is None:
                return
            op, sequence, payload = message
            future = self.pending.get(sequence)
            if future is None or future.done():
                continue
            if op == bp.wire.ERROR:
                future.set_exception(ValueError('Zumo: ' + payload.decode(errors='replace')))
            else:
                future.set_result((op, payload))

    async def _request(self, op, payload, timeout):
        if not self.client or not self.client.is_connected:
            raise ConnectionError('BLE robot is disconnected')
        if len(self.pending) >= 8:
            raise RuntimeError('Too many pending BLE requests')
        self.sequence = self.sequence % 65535 + 1
        sequence = self.sequence
        future = self.loop.create_future()
        self.pending[sequence] = future
        deadline = self.loop.time() + timeout
        locked = False
        try:
            await asyncio.wait_for(self.write_lock.acquire(), timeout)
            locked = True
            packet = bp.wire.frame(op, sequence, payload)
            # 20 bytes works even before an MTU exchange. Motor requests fit
            # in one write; longer peripheral replies are reassembled above.
            for offset in range(0, len(packet), 20):
                await asyncio.wait_for(self.client.write_gatt_char(
                    bp.RX_UUID, packet[offset:offset + 20], response=False),
                    max(.001, deadline - self.loop.time()))
            self.write_lock.release()
            locked = False
            code, reply = await asyncio.wait_for(future, max(.001, deadline - self.loop.time()))
            if code != op | 0x80:
                raise ValueError('Unexpected BLE reply opcode')
            return reply
        finally:
            if locked:
                self.write_lock.release()
            self.pending.pop(sequence, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()  # consume an error if a write failed first

    def request(self, op, payload=b'', timeout=1.5):
        return self.call(self._request(op, payload, timeout), timeout + .5)

    async def _disconnect(self):
        if self.client:
            await self.client.disconnect()

    def close(self):
        if not self.thread.is_alive() or self.loop.is_closed():
            return
        try:
            self.call(self._disconnect(), 5)
        except Exception:
            pass
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(6)
