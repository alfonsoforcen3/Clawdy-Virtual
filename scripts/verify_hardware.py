#!/usr/bin/env python3
"""Check real board acknowledgements; briefly overrides LEDs, then restores tracking."""
import argparse
import json
import socket
import sys
import time

def request(payload):
    with socket.create_connection(('127.0.0.1', 8765), 3) as connection:
        connection.sendall(json.dumps(payload).encode())
        return json.loads(connection.recv(8192))

def _checked_report(result, transport, expected_device_id, peer):
    """Validate bridge evidence before interpreting any firmware GPIO fields."""
    if not isinstance(result, dict) or not isinstance(result.get('hardware_connected'), bool):
        raise AssertionError('Malformed bridge status: expected an object with hardware_connected boolean.')
    report = result.get('firmware_report')
    if report is not None and not isinstance(report, dict):
        raise AssertionError('Malformed firmware report: expected an object or null.')
    if not result['hardware_connected']:
        return {}, peer
    if not report:
        raise AssertionError('Connected bridge has no firmware acknowledgement.')
    if transport and report.get('transport') != transport:
        raise AssertionError('Board acknowledgement used the wrong transport.')
    if transport == 'ble':
        port = result.get('port')
        if (result.get('transport') != 'ble' or not isinstance(port, str)
                or not port.startswith('ble://') or not port[6:]):
            raise AssertionError('Connected bridge did not report a Bluetooth peer.')
        if peer is not None and port != peer:
            raise AssertionError('Bluetooth peer changed during LED verification; stop and select the intended Clawdy.')
        peer = port
    if expected_device_id is not None and report.get('device_id') != expected_device_id:
        raise AssertionError('Board identity changed or is missing during LED verification; stop and select the intended Clawdy.')
    return report, peer


def _check_gpio(report, mode):
    values = []
    for label in ('green_pin', 'amber_pin', 'red_pin'):
        pin = report.get(label)
        if not isinstance(pin, str) or not isinstance(report.get(pin), bool):
            raise AssertionError('Malformed firmware GPIO acknowledgement: ' + label)
        values.append(report[pin])
    if mode == 'B':
        # Red may be in either part of its blink cycle, but other colors must be off.
        expected = [False, False, values[2]]
    else:
        expected = [mode == 'G', mode == 'Y', mode == 'R']
    if values != expected:
        raise AssertionError('Board GPIO outputs do not match requested mode ' + mode + '.')


def verify(transport, expected_device_id=None):
    """Verify LED acknowledgements, optionally pinning the selected immutable UID."""
    primary_error = None
    peer = None
    try:
        for mode in 'RYGBO':
            request({'action': 'hardware_test', 'state': mode})
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                result = request({'action': 'status'})
                report, peer = _checked_report(result, transport, expected_device_id, peer)
                if (result['hardware_connected'] and report.get('mode') == mode
                        and report.get('display_phase') in (None, 'tracking')):
                    _check_gpio(report, mode)
                    print('Confirmed', mode, report, flush=True)
                    time.sleep(1)
                    break
                time.sleep(.15)
            else:
                raise AssertionError('Board did not acknowledge ' + mode + ': ' + str(result))
    except BaseException as error:
        primary_error = error
        raise
    finally:
        try:
            request({'action': 'resume'})
        except Exception:
            if primary_error is None:
                raise
            print('Warning: tracking restoration also failed; the original verification failure is preserved. '
                  'Check the bridge and restore tracking before using Clawdy.', file=sys.stderr)
    print('Tracking restored. A human must also confirm the LEDs physically lit.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transport', choices=['ble', 'usb'], default='ble')
    parser.add_argument('--device-id', help='Expected immutable board identity; checked throughout LED verification')
    args = parser.parse_args()
    verify(args.transport, expected_device_id=args.device_id)
