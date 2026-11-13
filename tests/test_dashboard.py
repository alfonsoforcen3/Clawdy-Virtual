"""Device-status API and privacy tests using an isolated loopback HTTP fixture."""
import json
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from scripts.dashboard import Dashboard, device_report, firmware_status


def report(**values):
    return dict({'firmware': 'traffic-nicenano-v1', 'mode': 'Y', 'transport': 'ble',
                 'display_phase': 'tracking', 'green_pin': 'P0.25', 'amber_pin': 'P0.26',
                 'red_pin': 'P0.27', 'P0.25': False, 'P0.26': True, 'P0.27': False,
                 'green_pwm_duty': 32768, 'green_pwm_frequency': 5000,
                 'session_count_kind': 'working', 'session_count': 2, 'working_provider_mask': 3}, **values)


class DashboardTests(unittest.TestCase):
    def test_status_is_sanitized_and_clears_when_disconnected_or_stale(self):
        clock, wall, online = [0.0], [1000.0], [True]
        raw = report(device_id='PRIVATE_UID', ble_name='PRIVATE_NAME', port='PRIVATE_PATH',
                     private_prompt='PRIVATE_PROMPT', unexpected={'private': 'PRIVATE_DATA'})
        dash = Dashboard(lambda: raw, lambda: online[0], clock=lambda: clock[0], wall_clock=lambda: wall[0])
        self.assertTrue(dash.status()['stale'])
        dash.received(raw)
        data = dash.status()
        self.assertFalse(data['stale'])
        self.assertEqual((data['mode'], data['transport'], data['working_count']), ('Y', 'ble', 2))
        self.assertEqual(data['providers'], ['claude', 'codex'])
        self.assertEqual(data['hardware_report']['P0.26'], True)
        self.assertNotIn('PRIVATE', json.dumps(data))
        self.assertEqual(set(data), {'connected', 'stale', 'age_seconds', 'updated_at', 'firmware',
                                    'mode', 'transport', 'display_phase', 'working_count', 'providers', 'hardware_report'})
        clock[0] = 12; wall[0] = -5000  # Wall-clock reversal cannot refresh an old GPIO report.
        self.assertEqual(dash.status()['age_seconds'], 12)
        self.assertEqual(dash.status()['updated_at'], 1000)
        clock[0] = 91
        stale = dash.status()
        self.assertTrue(stale['stale'])
        self.assertIsNone(stale['mode']); self.assertIsNone(stale['hardware_report'])
        self.assertIsNone(stale['working_count']); self.assertEqual(stale['providers'], [])
        dash.received(raw); online[0] = False
        self.assertIsNone(dash.status()['hardware_report'])
        online[0] = True
        self.assertTrue(dash.status()['stale'])  # Connection alone cannot replay an old report.
        dash.received(report(mode='G', session_count=0, working_provider_mask=3))
        self.assertEqual(dash.status()['mode'], 'G')
        self.assertEqual(dash.status()['providers'], [])
        dash.received(None)
        self.assertIsNone(dash.status()['age_seconds'])

    def test_malformed_reports_clear_freshness_and_typed_allowlist_ignores_unknown_data(self):
        dash = Dashboard(lambda: None, lambda: True)
        for bad in (None, [], {}, {'firmware': 'unknown'}):
            dash.received(report())
            dash.received(bad)
            self.assertTrue(dash.status()['stale'])
        invalid = report(mode='PRIVATE_MODE', transport='PRIVATE_PORT', display_phase='PRIVATE_PHASE',
                         green_pin='PRIVATE_PIN', green_pwm_duty=True, green_pwm_frequency=999999,
                         session_count=True, working_provider_mask=True)
        dash.received(invalid)
        data = dash.status()
        self.assertIsNone(data['mode']); self.assertIsNone(data['transport'])
        self.assertIsNone(data['working_count']); self.assertEqual(data['providers'], [])
        self.assertNotIn('PRIVATE', json.dumps(data))
        self.assertNotIn('green_pin', data['hardware_report'])
        self.assertNotIn('green_pwm_duty', data['hardware_report'])

    def test_usb_reports_use_same_status_contract_and_copy_output_values(self):
        raw = report(firmware='traffic-esp32c3-v1', transport='usb', green_pin='GPIO21',
                     amber_pin='GPIO22', red_pin='GPIO23', GPIO21=False, GPIO22=True, GPIO23=False,
                     green_pwm_duty=2048, green_pwm_resolution_bits=12)
        dash = Dashboard(lambda: raw, lambda: True)
        dash.received(raw)
        data = dash.status()
        self.assertEqual(data['transport'], 'usb')
        self.assertEqual(data['hardware_report']['GPIO22'], True)
        self.assertEqual(data['hardware_report']['green_pwm_resolution_bits'], 12)
        raw['GPIO22'] = False
        self.assertTrue(dash.status()['hardware_report']['GPIO22'])
        data['hardware_report']['GPIO22'] = False
        self.assertTrue(dash.status()['hardware_report']['GPIO22'])

    def test_private_bridge_allowlist_retains_identity_but_omits_unrecognized_legacy_fields(self):
        raw = report(device_id='fixture-id', ble_name='fixture-name', hardware_family='nrf52840',
                     identity_protocol=1, rename_supported=True, obsolete_sensor={'legacy': 1},
                     private_prompt='PRIVATE')
        data = firmware_status(raw)
        self.assertEqual((data['device_id'], data['ble_name']), ('fixture-id', 'fixture-name'))
        self.assertEqual(data['identity_protocol'], 1)
        self.assertTrue(data['rename_supported'])
        self.assertEqual(data['P0.26'], True)
        self.assertEqual(data['session_count'], 2)
        self.assertNotIn('obsolete_sensor', data)
        self.assertNotIn('PRIVATE', json.dumps(data))
        self.assertNotIn('device_id', device_report(data))

    def test_http_status_rejects_foreign_host_old_endpoint_and_private_routes(self):
        dash = Dashboard(lambda: None, lambda: False)
        server = dash.start(0)
        base = 'http://127.0.0.1:' + str(server.server_port)
        host = '127.0.0.1:' + str(server.server_port)
        try:
            with urlopen(Request(base + '/api/status', headers={'Host': host}), timeout=2) as response:
                data = json.load(response)
                self.assertTrue(data['stale'])
                self.assertIsNone(response.headers.get('Access-Control-Allow-Origin'))
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
            for path, origin, code in [('/api/status', 'evil.example', 403), ('/api/battery', host, 404),
                                       ('/../bridge.py', host, 404), ('/api/status/private', host, 404)]:
                with self.assertRaises(HTTPError) as failure:
                    urlopen(Request(base + path, headers={'Host': origin}), timeout=2)
                self.assertEqual(failure.exception.code, code)
        finally:
            server.shutdown(); server.server_close()
