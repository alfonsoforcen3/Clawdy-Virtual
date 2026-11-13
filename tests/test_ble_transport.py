import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
try:
    from scripts.ble_transport import BluetoothLink, RX_UUID, SERVICE_UUID
except ImportError:
    raise unittest.SkipTest('bleak is not installed; skipping BLE transport tests')


class SinglePendingClient:
    """Mimic the CoreBluetooth backend's single future per characteristic."""
    is_connected = True
    def __init__(self):
        self.active = 0
        self.writes = []
    async def write_gatt_char(self, uuid, data, response):
        if self.active:
            raise KeyError(29)
        self.active += 1
        try:
            await asyncio.sleep(.005)
            self.writes.append((uuid, data, response))
        finally:
            self.active -= 1


class BluetoothWriteTests(unittest.IsolatedAsyncioTestCase):
    def link(self):
        return BluetoothLink('test', lambda: 'Y', lambda report: None)

    async def test_concurrent_hooks_heartbeat_and_metadata_never_overlap(self):
        link = self.link()
        client = link.client = SinglePendingClient()
        packets = [b'Y', b'N12\n', b'P7\n', b'G', b'Q'] * 5
        await asyncio.gather(*(link.write(packet) for packet in packets))
        self.assertEqual(client.writes, [(RX_UUID, packet, True) for packet in packets])

    async def test_disconnect_is_checked_after_waiting_for_lock(self):
        link = self.link()
        link._write_lock = asyncio.Lock()
        client = link.client = SinglePendingClient()
        await link._write_lock.acquire()
        task = asyncio.create_task(link.write(b'Y'))
        await asyncio.sleep(0)
        client.is_connected = False
        link._write_lock.release()
        with self.assertRaises(ConnectionError):
            await task
        self.assertEqual(client.writes, [])

    async def test_cancellation_releases_lock_for_next_write(self):
        link = self.link()
        client = link.client = SinglePendingClient()
        task = asyncio.create_task(link.write(b'Y'))
        while not client.active:
            await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await link.write(b'Q')
        self.assertEqual(client.writes, [(RX_UUID, b'Q', True)])

    async def test_connection_reports_identity_then_sends_only_count_apps_and_state(self):
        reports = []
        link = BluetoothLink('test', lambda: 'Y', reports.append,
                             get_session_count=lambda: 12, get_provider_mask=lambda: 7)
        class Client:
            is_connected = False
            def __init__(self): self.writes = []; self.disconnects = 0
            async def connect(self): self.is_connected = True
            async def start_notify(self, _uuid, callback):
                callback(None, (json.dumps({'firmware': 'traffic-nicenano-v1', 'transport': 'ble'}) + '\n').encode())
            async def write_gatt_char(self, _uuid, data, response): self.writes.append(data)
            async def disconnect(self): self.is_connected = False; self.disconnects += 1
        client = Client()
        with patch.object(link, 'discover_device', new=AsyncMock(return_value=SimpleNamespace(address='fixture'))), \
                patch('scripts.ble_transport.BleakClient', return_value=client), \
                patch('scripts.ble_transport.asyncio.sleep', new=AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError): await link.run()
        self.assertEqual(client.writes, [b'Q', b'N12\n', b'P7\n', b'Y'])
        self.assertEqual(client.disconnects, 1)
        self.assertIsNone(reports[-1])


class BluetoothDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    def advertisement(self, address, name='test', services=None, local_name='test'):
        return (SimpleNamespace(address=address, name=name),
                SimpleNamespace(local_name=local_name,
                                service_uuids=[SERVICE_UUID] if services is None else services))

    async def discover(self, advertisements):
        link = BluetoothLink('test', lambda: 'Y', lambda report: None)
        with patch('scripts.ble_transport.BleakScanner.discover',
                   new=AsyncMock(return_value=advertisements)) as scan:
            result = await link.discover_device()
            scan.assert_awaited_once_with(timeout=10, service_uuids=[SERVICE_UUID], return_adv=True)
            return result

    async def test_selects_only_exact_name_and_uart_service(self):
        expected = self.advertisement('AA', services=[SERVICE_UUID.upper()])
        found = await self.discover({
            'other-name': self.advertisement('BB', name='test-extra', local_name='test-extra'),
            'other-service': self.advertisement('CC', services=['unrelated']),
            'missing-service': self.advertisement('DD', services=[]),
            'selected': expected})
        self.assertIs(found, expected[0])

    async def test_supports_device_name_when_local_name_missing(self):
        expected = self.advertisement('AA', local_name=None)
        self.assertIs(await self.discover({'selected': expected}), expected[0])

    async def test_repeated_address_does_not_count_as_two_units(self):
        found = await self.discover({'first': self.advertisement('aa'),
                                     'repeat': self.advertisement('AA')})
        self.assertEqual(found.address, 'AA')

    async def test_no_matching_board_returns_none(self):
        self.assertIsNone(await self.discover({}))

    async def test_duplicate_name_refuses_connection_and_reports_error(self):
        reports = []
        link = BluetoothLink('test', lambda: 'Y', reports.append)
        advertisements = {'first': self.advertisement('AA'),
                          'second': self.advertisement('BB')}
        with patch('scripts.ble_transport.BleakScanner.discover',
                   new=AsyncMock(return_value=advertisements)), \
             patch('scripts.ble_transport.BleakClient') as client, \
             patch('scripts.ble_transport.asyncio.sleep',
                   new=AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await link.run()
        client.assert_not_called()
        self.assertIn('Multiple Bluetooth boards', link.last_error)
        self.assertFalse(link.connected)
        self.assertIsNone(link.client)
        self.assertEqual(reports, [None])
