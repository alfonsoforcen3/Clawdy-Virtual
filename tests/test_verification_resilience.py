"""Hardware-free verification checks; every request is replaced before use."""
import contextlib
import copy
import io
import unittest
from unittest.mock import patch

from scripts import verify_hardware as verifier


def status(mode, device_id='selected', peer='ble://selected'):
    return {'hardware_connected': True, 'transport': 'ble', 'port': peer,
            'firmware_report': {'mode': mode, 'transport': 'ble', 'device_id': device_id,
                                'display_phase': 'tracking', 'green_pin': 'P0.25',
                                'amber_pin': 'P0.26', 'red_pin': 'P0.27',
                                'P0.25': mode == 'G', 'P0.26': mode == 'Y',
                                'P0.27': mode in ('R', 'B')}}


class VerificationResilienceTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        # Fail fast rather than ever allowing a test to contact a running bridge.
        self.request = self.stack.enter_context(patch.object(verifier, 'request', side_effect=AssertionError('Unmocked request')))
        self.stack.enter_context(patch.object(verifier.socket, 'create_connection', side_effect=AssertionError('Sockets forbidden')))
        self.stack.enter_context(patch.object(verifier.time, 'sleep'))
        self.output = self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.errors = self.stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.mode = None
        self.actions = []

    def responder(self, transform=None, resume_error=None):
        def respond(payload):
            self.actions.append(payload['action'])
            if payload['action'] == 'hardware_test':
                self.mode = payload['state']
                return {}
            if payload['action'] == 'resume':
                if resume_error:
                    raise resume_error
                return {}
            result = status(self.mode)
            return transform(result) if transform else result
        self.request.side_effect = respond

    def test_selected_identity_and_nondefault_green_complete_every_mode(self):
        self.responder()
        verifier.verify('ble', expected_device_id='selected')
        self.assertEqual(self.actions.count('status'), 5)
        self.assertEqual(self.actions[-1], 'resume')
        self.assertIn('Tracking restored', self.output.getvalue())

    def test_identity_must_match_on_later_led_acknowledgements(self):
        for mode in 'YGBO':
            with self.subTest(mode=mode):
                def change(result):
                    if self.mode == mode:
                        result['firmware_report']['device_id'] = 'other'
                    return result
                self.responder(change)
                with self.assertRaisesRegex(AssertionError, 'identity changed'):
                    verifier.verify('ble', expected_device_id='selected')
                self.assertEqual(self.actions[-1], 'resume')

    def test_identity_checked_even_before_requested_mode_arrives(self):
        def stale(result):
            result['firmware_report'].update(mode='G', device_id='other')
            return result
        self.responder(stale)
        with self.assertRaisesRegex(AssertionError, 'identity changed'):
            verifier.verify('ble', expected_device_id='selected')

    def test_peer_cannot_change_between_leds(self):
        def changed(result):
            if self.mode == 'Y':
                result['port'] = 'ble://other'
            return result
        self.responder(changed)
        with self.assertRaisesRegex(AssertionError, 'peer changed'):
            verifier.verify('ble', expected_device_id='selected')

    def test_ble_requires_host_peer_and_both_transports(self):
        variants = [('port', None), ('port', 'ble://'), ('port', 'serial'), ('transport', 'serial')]
        for key, value in variants:
            with self.subTest(key=key, value=value):
                self.responder(lambda result: dict(result, **{key: value}))
                with self.assertRaisesRegex(AssertionError, 'Bluetooth peer'):
                    verifier.verify('ble')
        def wrong_report(result):
            result['firmware_report']['transport'] = 'usb'
            return result
        self.responder(wrong_report)
        with self.assertRaisesRegex(AssertionError, 'wrong transport'):
            verifier.verify('ble')

    def test_malformed_status_has_actionable_failure_and_restores(self):
        for malformed in (None, [], {}, {'hardware_connected': 'true'},
                          {'hardware_connected': True, 'firmware_report': []},
                          {'hardware_connected': True, 'firmware_report': None}):
            with self.subTest(value=malformed):
                self.responder(lambda result: copy.deepcopy(malformed))
                with self.assertRaisesRegex(AssertionError, 'Malformed|no firmware'):
                    verifier.verify('ble')
                self.assertEqual(self.actions[-1], 'resume')

    def test_gpio_shape_and_wrong_values_fail_without_keyerror(self):
        variants = [('green_pin', []), ('P0.25', None), ('P0.26', 0), ('P0.27', False)]
        for key, value in variants:
            with self.subTest(key=key):
                def changed(result):
                    result['firmware_report'][key] = value
                    return result
                self.responder(changed)
                with self.assertRaisesRegex(AssertionError, 'GPIO'):
                    verifier.verify('ble')

    def test_blink_acknowledgement_keeps_other_leds_off(self):
        def changed(result):
            if self.mode == 'B':
                result['firmware_report']['P0.26'] = True
            return result
        self.responder(changed)
        with self.assertRaisesRegex(AssertionError, 'GPIO outputs'):
            verifier.verify('ble')

    def test_primary_failure_survives_resume_failure(self):
        self.responder(lambda result: None, resume_error=OSError('resume offline'))
        with self.assertRaisesRegex(AssertionError, 'Malformed bridge status'):
            verifier.verify('ble')
        self.assertIn('restoration also failed', self.errors.getvalue())
        self.assertNotIn('Tracking restored', self.output.getvalue())

    def test_resume_failure_after_success_is_reported(self):
        self.responder(resume_error=OSError('resume offline'))
        with self.assertRaisesRegex(OSError, 'resume offline'):
            verifier.verify('ble')
        self.assertNotIn('Tracking restored', self.output.getvalue())

    def test_original_transport_positional_call_supports_legacy_usb(self):
        def usb(result):
            result['transport'] = 'serial'
            result['port'] = '/dev/legacy'
            result['firmware_report']['transport'] = 'usb'
            del result['firmware_report']['device_id']
            return result
        self.responder(usb)
        verifier.verify('usb')
        self.assertIn('Tracking restored', self.output.getvalue())

    def test_disconnected_bridge_expires_without_shape_crash(self):
        self.responder(lambda result: {'hardware_connected': False, 'firmware_report': None})
        # Advance the logical deadline without real waiting or backend access.
        counter = iter(range(0, 100, 6))
        with patch.object(verifier.time, 'monotonic', side_effect=lambda: next(counter)):
            with self.assertRaisesRegex(AssertionError, 'did not acknowledge'):
                verifier.verify('ble', expected_device_id='selected')
        self.assertEqual(self.actions[-1], 'resume')


if __name__ == '__main__':
    unittest.main()
