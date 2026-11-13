"""Persistent BLE connection to the traffic light's Nordic UART service."""
import asyncio
import json
import threading
from bleak import BleakClient, BleakScanner

SERVICE_UUID = '6e400001-b5a3-f393-e0a9-e50e24dcca9e'
RX_UUID = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'
TX_UUID = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'

class BluetoothLink:
    def __init__(self, name, get_state, on_report, get_session_count=None, get_provider_mask=None, device_id=None):
        self.name = name
        self.device_id = device_id
        self._identity_ready = None
        self._identity_valid = False
        self.get_state = get_state
        self.get_session_count = get_session_count
        self.get_provider_mask = get_provider_mask
        self.on_report = on_report
        self.connected = False
        self.peer = None
        self.last_error = None
        self.client = None
        self.loop = None
        self.buffer = bytearray()
        self._write_lock = None

    def start(self):
        threading.Thread(target=lambda: asyncio.run(self.run()), daemon=True).start()

    def notified(self, characteristic, data):
        self.buffer.extend(data)
        while b'\n' in self.buffer:
            line, _, remaining = self.buffer.partition(b'\n')
            self.buffer = bytearray(remaining)
            try:
                report = json.loads(line)
                if report.get('firmware') in ('traffic-nicenano-v1', 'traffic-esp32c3-v1'):
                    if self.device_id and report.get('device_id') != self.device_id:
                        self.last_error = 'Board identity mismatch; reenroll the intended unit'
                        self.connected = False
                        self._identity_valid = False
                        if self._identity_ready:
                            self._identity_ready.set()
                        continue
                    if self._identity_ready is not None:
                        if report.get('transport') != 'ble':
                            continue
                        self._identity_valid = True
                        self._identity_ready.set()
                    self.on_report(report)
            except (ValueError, AttributeError):
                pass
        if len(self.buffer) > 4096:
            self.buffer.clear()

    async def write(self, data):
        # CoreBluetooth tracks one pending write per characteristic handle.
        # Hook sends and heartbeat writes share this lock on the BLE event loop.
        if self._write_lock is None:
            self._write_lock = asyncio.Lock()
        async with self._write_lock:
            client = self.client
            if not client or not client.is_connected:
                raise ConnectionError('Traffic light Bluetooth disconnected')
            await asyncio.wait_for(
                client.write_gatt_char(RX_UUID, data, response=True), timeout=5)

    def send(self, data):
        if not self.connected or not self.loop:
            return False
        future = asyncio.run_coroutine_threadsafe(self.write(data), self.loop)
        def done(result):
            try:
                result.result()
            except Exception as error:
                self.last_error = type(error).__name__ + ': ' + str(error)
                self.connected = False
                print('Bluetooth write failed: ' + self.last_error, flush=True)
        future.add_done_callback(done)
        return True

    async def discover_device(self):
        # Collect the entire scan window: first-match discovery can connect to
        # the wrong unit when two nearby boards advertise the same name.
        advertisements = await asyncio.wait_for(BleakScanner.discover(
            timeout=10, service_uuids=[SERVICE_UUID], return_adv=True), timeout=15)
        matches = {}
        for device, advertisement in advertisements.values():
            services = {uuid.lower() for uuid in advertisement.service_uuids or []}
            if SERVICE_UUID not in services:
                continue
            if advertisement.local_name == self.name or device.name == self.name:
                matches[device.address.casefold()] = device
        if len(matches) > 1:
            raise RuntimeError('Multiple Bluetooth boards advertise ' + repr(self.name)
                               + '; power off other matching units before connecting')
        return next(iter(matches.values()), None)

    async def run(self):
        self.loop = asyncio.get_running_loop()
        while True:
            try:
                print('Scanning for Bluetooth traffic light ' + self.name, flush=True)
                device = await self.discover_device()
                if not device:
                    self.last_error = 'Board not found; check that it has power'
                    await asyncio.sleep(2)
                    continue
                def disconnected(client):
                    self.connected = False
                    self.on_report(None)
                client = BleakClient(device, timeout=15, disconnected_callback=disconnected)
                self.client = client
                try:
                    await asyncio.wait_for(client.connect(), timeout=20)
                    self.buffer.clear()
                    self._identity_valid = False
                    self._identity_ready = asyncio.Event()
                    await asyncio.wait_for(client.start_notify(TX_UUID, self.notified), timeout=10)
                    await self.write(b'Q')
                    await asyncio.wait_for(self._identity_ready.wait(), timeout=8)
                    if not self._identity_valid:
                        raise RuntimeError('Selected board identity does not match enrollment')
                    self.peer = device.address
                    self.connected = True
                    self.last_error = None
                    print('Bluetooth connected: ' + self.name + ' (' + self.peer + ')', flush=True)
                    while client.is_connected and self.connected:
                        if self.get_session_count is not None:
                            count = max(0, min(9999, int(self.get_session_count())))
                            await self.write(("N%d\n" % count).encode("ascii"))
                        if self.get_provider_mask is not None:
                            mask = max(0, min(15, int(self.get_provider_mask())))
                            await self.write(("P%d\n" % mask).encode("ascii"))
                        await self.write(self.get_state().encode())
                        await asyncio.sleep(3)
                finally:
                    try:
                        await asyncio.wait_for(client.disconnect(), timeout=5)
                    except Exception:
                        pass
            except Exception as error:
                self.last_error = type(error).__name__ + ': ' + str(error) or type(error).__name__
                print('Bluetooth connection error: ' + self.last_error, flush=True)
            finally:
                self.connected = False
                self.client = None
                self.on_report(None)
            await asyncio.sleep(3)
