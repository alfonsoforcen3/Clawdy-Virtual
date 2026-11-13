import json
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts import device_identity as identity


class UsbIdentityTests(unittest.TestCase):
    def report(self, **updates):
        return dict(firmware='traffic-esp32c3-v1', hardware_family='esp32c3', transport='usb',
                    device_id='AABBCCDDEEFF', ble_name='Clawdy-AABBCCDDEEFF',
                    identity_protocol=1, rename_supported=True, **updates)

    def candidate(self, **updates):
        value = dict(port='MOCK-PORT', serial_number='MOCK-SERIAL', identity_query_supported=True)
        value.update(updates)
        return value

    def test_inventory_reads_metadata_without_opening_and_never_claims_a_board_model(self):
        port = SimpleNamespace(device='MOCK', vid=0x303A, pid=0x1001,
                               serial_number='SERIAL', description='USB Serial/JTAG')
        serial = SimpleNamespace(Serial=Mock(side_effect=AssertionError('No port opening')))
        ports = SimpleNamespace(comports=Mock(return_value=[port]))
        with patch.dict(sys.modules, {'serial': serial, 'serial.tools': SimpleNamespace(list_ports=ports)}):
            result = identity.usb_inventory()
        self.assertTrue(result['available']); self.assertTrue(result['ports'][0]['identity_query_supported'])
        self.assertFalse(result['ports'][0]['firmware_verified'])
        self.assertFalse(result['ports'][0]['board_model_verified']); serial.Serial.assert_not_called()

    def test_child_rechecks_exact_port_serial_and_allowlist_before_opening(self):
        serial = SimpleNamespace(Serial=Mock(side_effect=AssertionError('No port opening')))
        for entry in (self.candidate(port='OTHER'), self.candidate(serial_number='OTHER'),
                      self.candidate(identity_query_supported=False)):
            with patch.object(identity, 'usb_inventory', return_value={'ports': [entry]}), \
                    patch.dict(sys.modules, {'serial': serial}):
                with self.assertRaisesRegex(ValueError, 'no port opened'):
                    identity._inspect_usb_device('MOCK-PORT', 'MOCK-SERIAL', 1)
        serial.Serial.assert_not_called()

    def test_child_only_sends_q_with_reset_lines_disabled_and_closes(self):
        device = Mock()
        device.read.return_value = (json.dumps(self.report())+'\n').encode()
        serial = SimpleNamespace(Serial=Mock(return_value=device))
        with patch.object(identity, 'usb_inventory', return_value={'ports': [self.candidate()]}), \
                patch.dict(sys.modules, {'serial': serial}):
            report = identity._inspect_usb_device('MOCK-PORT', 'MOCK-SERIAL', 1)
        self.assertEqual(report['device_id'], 'AABBCCDDEEFF')
        serial.Serial.assert_called_once_with(port=None, baudrate=115200, timeout=.1, write_timeout=1.)
        self.assertIs(device.dtr, False); self.assertIs(device.rts, False); self.assertEqual(device.port, 'MOCK-PORT')
        device.open.assert_called_once(); device.write.assert_called_once_with(b'Q'); device.close.assert_called_once()

    def test_child_rejects_legacy_diagnostic_and_wrong_transport_reports_until_deadline(self):
        device = Mock()
        device.read.return_value = b'{"firmware":"clawdy-esp32c3-led-test-v1"}\n'
        with patch.object(identity, 'usb_inventory', return_value={'ports': [self.candidate()]}), \
                patch.dict(sys.modules, {'serial': SimpleNamespace(Serial=Mock(return_value=device))}), \
                patch.object(identity.time, 'monotonic', side_effect=[0, 0, 2]):
            with self.assertRaisesRegex(TimeoutError, 'no BLE fallback'):
                identity._inspect_usb_device('MOCK-PORT', 'MOCK-SERIAL', 1)
        device.close.assert_called_once()

    def test_parent_bounds_the_process_including_open_and_cleanup(self):
        result = subprocess.CompletedProcess([], 0, json.dumps(self.report()), '')
        with patch.object(identity.subprocess, 'run', return_value=result) as run:
            self.assertEqual(identity.inspect_usb_device('MOCK-PORT', 'MOCK-SERIAL'), self.report())
        self.assertEqual(run.call_args.kwargs['timeout'], 7.)
        self.assertEqual(run.call_args.args[0][-4:], ['--usb-identity', 'MOCK-PORT', 'MOCK-SERIAL', '5.0'])
        with patch.object(identity.subprocess, 'run', side_effect=subprocess.TimeoutExpired('mock', 7)):
            with self.assertRaises(subprocess.TimeoutExpired):
                identity.inspect_usb_device('MOCK-PORT', 'MOCK-SERIAL')

    def test_parent_validates_firmware_identity_and_never_accepts_a_bare_uid(self):
        for updates in ({'transport': 'serial'}, {'transport': 'ble'}, {'identity_protocol': True},
                        {'device_id': 'aabbccddeeff'}, {'hardware_family': 'nrf52840'},
                        {'ble_name': 'bad\nname'}, {'rename_supported': 'yes'}):
            report = self.report(); report.update(updates)
            with patch.object(identity.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(report), '')):
                with self.assertRaisesRegex(ValueError, 'Malformed USB'):
                    identity.inspect_usb_device('MOCK', 'SERIAL')

    def test_invalid_parameters_never_launch_a_process(self):
        with patch.object(identity.subprocess, 'run') as run:
            for port, serial, timeout in (('', 'S', 1), ('P', '', 1), ('P\n', 'S', 1),
                                          ('P', 'S', float('inf')), ('P', 'S', 13), ('P', 'S', True)):
                with self.assertRaises(ValueError):
                    identity.inspect_usb_device(port, serial, timeout)
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
