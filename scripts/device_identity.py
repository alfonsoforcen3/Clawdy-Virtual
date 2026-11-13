"""Explicit BLE enrollment and optional selected USB identity; no provisioning.

A UID check prevents accidental rename of another selected board. Nordic UART
is not an authenticated ownership protocol: proximity is not proof of ownership.
Bleak is imported lazily so offline setup previews need no BLE dependencies.
"""
import asyncio
import json
import math
import re
from pathlib import Path
import subprocess
import sys
import time
import unicodedata

RX_UUID = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'
TX_UUID = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'
SERVICE_UUID = '6e400001-b5a3-f393-e0a9-e50e24dcca9e'
SUPPORTED_FIRMWARE = ('traffic-nicenano-v1', 'traffic-esp32c3-v1')
SCAN_CLEANUP_TIMEOUT = 2.0
# USB descriptors identify candidate interfaces, never an exact PCB or firmware.
USB_IDENTITY_INTERFACES = {(0x303A, 0x1001): 'Espressif USB Serial/JTAG candidate'}


def usb_inventory():
    """Explicit metadata inventory only: never open a port or infer a board model."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return {'available': False, 'ports': [], 'reason': 'pyserial is not installed; no packages were downloaded'}
    ports = []
    for port in list_ports.comports():
        descriptor = (getattr(port, 'vid', None), getattr(port, 'pid', None))
        ports.append({'port': port.device, 'vid': descriptor[0], 'pid': descriptor[1],
                      'serial_number': getattr(port, 'serial_number', None),
                      'description': getattr(port, 'description', None),
                      'identity_query_supported': descriptor in USB_IDENTITY_INTERFACES,
                      'firmware_verified': False, 'board_model_verified': False})
    return {'available': True, 'ports': sorted(ports, key=lambda item: item['port']), 'reason': None}


def _inspect_usb_device(port, serial_number, timeout):
    """Child-only Q transaction after rechecking the selected descriptor/serial."""
    timeout = _validated_timeout(timeout)
    if timeout > 12:
        raise ValueError('USB identity timeout must be at most 12 seconds')
    candidates = [entry for entry in usb_inventory()['ports']
                  if entry['port'] == port and entry['serial_number'] == serial_number
                  and entry['identity_query_supported']]
    if len(candidates) != 1 or not isinstance(serial_number, str) or not serial_number.strip():
        raise ValueError('USB identity requires one exact allowlisted port and its nonempty USB serial number; no port opened')
    import serial
    reports = _ReportBuffer()
    device = serial.Serial(port=None, baudrate=115200, timeout=min(.1, timeout), write_timeout=min(1., timeout))
    # Do not intentionally reset the chip into a bootloader when querying Q.
    device.dtr = False
    device.rts = False
    device.port = port
    deadline = time.monotonic() + timeout
    failed = False
    try:
        device.open()
        device.write(b'Q')
        while time.monotonic() < deadline:
            for report in reports.feed(device.read(4096)):
                if _valid_usb_report(report):
                    return report
        raise TimeoutError('Selected USB port did not acknowledge supported Clawdy identity; no BLE fallback attempted')
    except BaseException:
        failed = True
        raise
    finally:
        try:
            device.close()
        except Exception:
            if not failed:
                raise


def _valid_usb_report(report):
    return (isinstance(report, dict) and report.get('firmware') == 'traffic-esp32c3-v1'
            and report.get('transport') == 'usb' and report.get('hardware_family') == 'esp32c3'
            and isinstance(report.get('device_id'), str) and re.fullmatch(r'[0-9A-F]{12}', report['device_id']) is not None
            and type(report.get('identity_protocol')) is int and report['identity_protocol'] == 1
            and isinstance(report.get('rename_supported'), bool)
            and isinstance(report.get('ble_name'), str) and 1 <= len(report['ble_name'].encode('utf-8')) <= 29
            and not any(ord(c) < 32 or ord(c) == 127 for c in report['ble_name']))


def inspect_usb_device(port, serial_number, timeout=5.):
    """Optional, explicitly selected USB Q; subprocess bounds open/read/cleanup."""
    timeout = _validated_timeout(timeout)
    if timeout > 12:
        raise ValueError('USB identity timeout must be at most 12 seconds')
    if not all(isinstance(value, str) and value.strip() and not any(ord(c) < 32 or ord(c) == 127 for c in value)
               for value in (port, serial_number)):
        raise ValueError('Exact USB port and USB serial number are required')
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--usb-identity', port,
                             serial_number, str(timeout)], capture_output=True, text=True,
                            timeout=timeout + 2, check=False)
    if result.returncode:
        raise RuntimeError('Selected USB identity query failed: ' + result.stderr.strip()[:500])
    report = json.loads(result.stdout)
    if not _valid_usb_report(report):
        raise ValueError('Malformed USB identity reply')
    return report


def _validated_timeout(timeout):
    """Reject deadlines that would disable bounding before opening any BLE client."""
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0):
        raise ValueError('Bluetooth timeout must be a finite positive number')
    return timeout


def _valid_device_id(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-fA-F]{8,64}', value) is not None


class _ReportBuffer:
    """Bound newline-delimited reports, discarding a whole oversized frame."""
    LIMIT = 8192

    def __init__(self):
        self.pending = bytearray()
        self.discarding = False

    def feed(self, data):
        self.pending.extend(data)
        while b'\n' in self.pending:
            line, _, rest = self.pending.partition(b'\n')
            self.pending[:] = rest
            oversized, self.discarding = self.discarding, False
            if oversized or len(line) > self.LIMIT:
                continue
            try:
                report = json.loads(line.decode('utf-8'))
            except (ValueError, UnicodeError, RecursionError):
                continue
            if isinstance(report, dict):
                yield report
        if len(self.pending) > self.LIMIT:
            self.pending.clear()
            self.discarding = True


def make_device_name(laptop, nickname, device_id):
    """29-byte legacy scan-response budget, keeping both names and UID suffix."""
    if not _valid_device_id(device_id):
        raise ValueError('A verified device UID is required to generate a name')
    def clean(value):
        value = unicodedata.normalize('NFKC', value).strip()
        value = ''.join(c for c in value if not unicodedata.category(c).startswith('C'))
        return re.sub(r'\s+', '-', value) or 'Clody'
    def trim(value, budget):
        return value.encode('utf-8')[:budget].decode('utf-8', errors='ignore')
    # Reserve at least nine bytes for each human component, redistribute unused bytes.
    left, right = clean(laptop), clean(nickname)
    left = trim(left, min(9, len(left.encode('utf-8'))))
    right = trim(right, 19 - len(left.encode('utf-8')))
    return '{}-{}-{}'.format(left, right, device_id[-8:].upper())


async def discover_candidates(timeout=8.0):
    timeout = _validated_timeout(timeout)
    from bleak import BleakScanner
    # Bleak sleeps for the scan duration, then stops its scanner. Allow a bounded
    # cleanup margin so an ordinary full-duration scan is not cancelled early.
    discovered = await asyncio.wait_for(
        BleakScanner.discover(timeout=timeout, return_adv=True),
        timeout=timeout + SCAN_CLEANUP_TIMEOUT)
    candidates = {}
    for item in discovered.values():
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            continue
        device, advert = item
        services = getattr(advert, 'service_uuids', None) or []
        if not isinstance(services, (tuple, list)) or not any(
                isinstance(service, str) and service.lower() == SERVICE_UUID for service in services):
            continue
        address = getattr(device, 'address', None)
        if not isinstance(address, str) or not address.strip():
            continue
        name = getattr(advert, 'local_name', None) or getattr(device, 'name', None) or ''
        if not isinstance(name, str):
            name = ''
        candidates[address] = {'name': name, 'address': address, 'rssi': getattr(advert, 'rssi', None)}
    return sorted(candidates.values(), key=lambda item: (item['name'], item['address']))


async def _with_bounded_client(address, operation, timeout, cleanup=None):
    """Bound connect/exchange and, separately, disconnect, including failed connects.

    Bleak's context manager exit is not necessarily covered by its constructor's
    connection timeout. Keep cleanup outside the exchange deadline and preserve
    the original error if cleanup also fails. Backends must honor cancellation.
    """
    timeout = _validated_timeout(timeout)
    from bleak import BleakClient
    client = BleakClient(address, timeout=timeout)
    failed = False
    async def exchange():
        await client.connect()
        return await operation(client)
    try:
        return await asyncio.wait_for(exchange(), timeout=timeout)
    except BaseException:
        failed = True
        raise
    finally:
        cleanup_error = None
        if cleanup is not None:
            try:
                await asyncio.wait_for(cleanup(client), timeout=timeout)
            except (Exception, asyncio.CancelledError) as error:
                cleanup_error = error
        try:
            await asyncio.wait_for(client.disconnect(), timeout=timeout)
        except (Exception, asyncio.CancelledError) as error:
            if cleanup_error is None:
                cleanup_error = error
        if not failed and cleanup_error is not None:
            raise cleanup_error


async def _transaction(address, wire, predicate, timeout):
    reports = _ReportBuffer()
    loop = asyncio.get_running_loop()
    reply = loop.create_future()
    def receive(_sender, data):
        for report in reports.feed(data):
            if predicate(report) and not reply.done():
                reply.set_result(report)
    async def run(client):
        await client.start_notify(TX_UUID, receive)
        for offset in range(0, len(wire), 20):
            await client.write_gatt_char(RX_UUID, wire[offset:offset + 20], response=True)
        return await reply
    return await _with_bounded_client(address, run, timeout)


async def inspect_device(address, timeout=12.0):
    report = await _transaction(address, b'Q', lambda r: r.get('transport') == 'ble' and
                                r.get('firmware') in SUPPORTED_FIRMWARE, timeout)
    if report.get('device_id') is not None and not _valid_device_id(report['device_id']):
        raise ValueError('Board reported a malformed device UID')
    return report


async def rename_device(address, name, expected_device_id, timeout=12.0):
    if not isinstance(name, str) or not 1 <= len(name.encode('utf-8')) <= 29 or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ValueError('Name must fit 1-29 UTF-8 bytes without controls')
    if not _valid_device_id(expected_device_id):
        raise ValueError('A verified device UID is required to rename a device')
    # Caller must inspect capabilities first; sending extended frames to old
    # firmware could interpret their letters as legacy colour commands.
    report = await inspect_device(address, timeout=timeout)
    if report.get('device_id') != expected_device_id:
        raise ValueError('Selected device identity changed')
    if (type(report.get('identity_protocol')) is not int or report['identity_protocol'] != 1
            or report.get('rename_supported') is not True):
        raise ValueError('Firmware does not support persistent Bluetooth rename')
    wire = ('!' + json.dumps({'op': 'rename', 'name': name, 'device_id': expected_device_id},
                             ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
    ack = await _transaction(address, wire, lambda r: r.get('identity_ack') == 'rename' and
                             r.get('device_id') == expected_device_id, timeout)
    if ack.get('ok') is not True or ack.get('persistent') is not True or ack.get('ble_name') != name:
        raise ValueError(ack.get('error', 'Rename was not persistently acknowledged'))
    return ack


async def identify_device(address, expected_device_id=None, timeout=12.0):
    """Brief acknowledged LED identification, restoring the selected board's state.

    The caller must obtain human confirmation before configuring this unit.
    Existing firmware without UID can be identified by its explicitly selected
    BLE address; it cannot be persistently renamed through this helper.
    """
    report = await inspect_device(address, timeout=timeout)
    if expected_device_id is not None and report.get('device_id') != expected_device_id:
        raise ValueError('Selected device identity changed')
    device_id = report.get('device_id')
    restore = report.get('mode', 'O')
    if restore not in ('R', 'Y', 'G', 'B', 'O') or report.get('display_phase') == 'searching':
        restore = 'O'

    await _identify_sequence(address, device_id, restore, timeout)
    return report


async def _identify_sequence(address, device_id, restore, timeout):
    """One connection; timeout bounds exchange, restore and disconnect separately.

    Recheck Q/UID on this connection before changing LEDs. A failed/partial LED
    write still needs a restore attempt, but failed identity/notification setup
    must not trigger one. Cleanup failures must not replace the original error.
    """
    reports = _ReportBuffer()
    responses = asyncio.Queue(maxsize=64)
    def receive(_sender, data):
        for response in reports.feed(data):
            if responses.full():
                responses.get_nowait()
            responses.put_nowait(response)
    mutated = False
    command = None
    async def run(client):
        nonlocal mutated, command
        await client.start_notify(TX_UUID, receive)
        async def send_command(mode, check_identity=True):
            # Discard earlier unsolicited/animation reports before this write.
            while not responses.empty():
                responses.get_nowait()
            await client.write_gatt_char(RX_UUID, mode.encode('ascii'), response=True)
            async def acknowledged():
                while True:
                    response = await responses.get()
                    if (response.get('transport') == 'ble'
                            and response.get('firmware') in SUPPORTED_FIRMWARE
                            and (mode == 'Q' or response.get('mode') == mode)
                            and (not check_identity or device_id is None or response.get('device_id') == device_id)):
                        return response
            return await asyncio.wait_for(acknowledged(), timeout)
        command = send_command
        report = await command('Q', check_identity=False)
        if device_id is not None and report.get('device_id') != device_id:
            raise ValueError('Selected device identity changed')
        # Existing nRF connection animation lasts about one second. Keep
        # the link alive so every requested colour becomes physically visible.
        await asyncio.sleep(1.2)
        for mode in ('R', 'Y', 'G'):
            mutated = True
            await command(mode)
            await asyncio.sleep(0.6)
    async def cleanup(client):
        if mutated:
            await command(restore)
    await _with_bounded_client(address, run, timeout, cleanup)


if __name__ == '__main__':
    # This private child entry point is used only by inspect_usb_device. Its
    # parent imposes a hard process deadline including serial open and close.
    try:
        if len(sys.argv) != 5 or sys.argv[1] != '--usb-identity':
            raise ValueError('Use the guided onboard command for USB identification')
        print(json.dumps(_inspect_usb_device(sys.argv[2], sys.argv[3], float(sys.argv[4]))))
    except (ValueError, RuntimeError, OSError, TimeoutError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
