"""Loopback-only device status and explicit session reset."""
import json
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

FIRMWARE = ('traffic-nicenano-v1', 'traffic-esp32c3-v1')
MODES = ('G', 'Y', 'R', 'B', 'O')
PHASES = ('searching', 'connected_show', 'tracking')
PROVIDER_BITS = ((1, 'claude'), (2, 'codex'), (4, 'gemini'), (8, 'other'))


def device_report(report):
    """Fixed allowlist, including only the selected colour pins' boolean outputs."""
    if not isinstance(report, dict) or report.get('firmware') not in FIRMWARE:
        return None
    clean = {'firmware': report['firmware'],
             'mode': report.get('mode') if report.get('mode') in MODES else None,
             'transport': report.get('transport') if report.get('transport') in ('ble', 'usb') else None,
             'display_phase': report.get('display_phase') if report.get('display_phase') in PHASES else None}
    for field in ('green_pin', 'amber_pin', 'red_pin'):
        pin = report.get(field)
        if isinstance(pin, str) and re.fullmatch(r'(?:P[01]\.\d{2}|GPIO\d{1,2})', pin):
            clean[field] = pin
            if type(report.get(pin)) is bool:
                clean[pin] = report[pin]
    for field, maximum in (('green_pwm_duty', 65535), ('green_pwm_frequency', 40000), ('green_pwm_resolution_bits', 16)):
        value = report.get(field)
        if type(value) is int and 0 <= value <= maximum:
            clean[field] = value
    return clean


def firmware_status(report):
    """Private bridge report allowlist; retain identity/verification metadata only."""
    clean = device_report(report)
    if clean is None:
        return None
    for field, maximum in (('device_id', 128), ('ble_name', 29), ('ble_error', 256), ('oled_error', 256)):
        value = report.get(field)
        if value is None or (isinstance(value, str) and len(value.encode('utf-8')) <= maximum):
            clean[field] = value
    if report.get('hardware_family') in ('nrf52840', 'esp32c3'):
        clean['hardware_family'] = report['hardware_family']
    if type(report.get('identity_protocol')) is int and report['identity_protocol'] == 1:
        clean['identity_protocol'] = 1
    if type(report.get('rename_supported')) is bool:
        clean['rename_supported'] = report['rename_supported']
    count = report.get('session_count')
    if count is None or (type(count) is int and 0 <= count <= 9999):
        clean['session_count'] = count
    if report.get('session_count_kind') == 'working':
        clean['session_count_kind'] = 'working'
    mask = report.get('working_provider_mask')
    if type(mask) is int and 0 <= mask <= 15:
        clean['working_provider_mask'] = mask
    return clean


class Dashboard:
    def __init__(self, get_report, connected, root=None, *, clock=time.monotonic, wall_clock=time.time):
        # Keep the established constructor; accepted reports enter via received().
        self.get_report = get_report
        self.connected = connected
        self.root = Path(root or Path(__file__).resolve().parent.parent / 'web')
        self.clock, self.wall_clock = clock, wall_clock
        self._lock = threading.Lock()
        self._report = None
        self._last_seen = None
        self._updated_at = None
        self._working_count = None
        self._providers = []

    def received(self, report):
        clean = device_report(report)
        count = report.get('session_count') if clean and report.get('session_count_kind') == 'working' else None
        if type(count) is not int or not 0 <= count <= 9999:
            count = None
        mask = report.get('working_provider_mask') if clean else None
        providers = [name for bit, name in PROVIDER_BITS if mask & bit] if (
            type(mask) is int and 0 <= mask <= 15 and count is not None and count > 0) else []
        with self._lock:
            self._report = clean
            self._last_seen = self.clock() if clean else None
            self._updated_at = round(self.wall_clock(), 3) if clean else None
            self._working_count, self._providers = count, providers

    def status(self):
        online = bool(self.connected())
        with self._lock:
            if not online:
                self._report = None
            age = max(0, self.clock() - self._last_seen) if self._last_seen is not None else None
            stale = not online or self._report is None or age is None or age > 90
            report = dict(self._report) if not stale and self._report else None
            return {'connected': online, 'stale': stale,
                    'age_seconds': round(age) if age is not None else None,
                    'updated_at': self._updated_at,
                    'firmware': report['firmware'] if report else None,
                    'mode': report['mode'] if report else None,
                    'transport': report['transport'] if report else None,
                    'display_phase': report['display_phase'] if report else None,
                    'working_count': self._working_count if report else None,
                    'providers': list(self._providers) if report else [],
                    'hardware_report': report}

    def start(self, port=8766):
        dashboard = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                host = self.headers.get('Host')
                if (host not in (f'127.0.0.1:{server.server_port}', f'localhost:{server.server_port}')
                        or self.headers.get('Origin') != f'http://{host}'):
                    self.send_error(403)
                    return
                if urlsplit(self.path).path != '/api/reset':
                    self.send_error(404)
                    return
                try:
                    with socket.create_connection(('127.0.0.1', 8765), timeout=2) as client:
                        client.sendall(b'{"action":"reset"}\n')
                        if json.loads(client.recv(1024)).get('status') != 'reset_ok':
                            raise ValueError('Bridge rejected reset')
                except (OSError, ValueError, AttributeError):
                    self.send_error(503, 'Bridge did not confirm reset')
                    return
                self.send_response(204)
                self.end_headers()

            def do_GET(self):
                # Reject DNS rebinding. No CORS; public sites cannot read local status.
                if self.headers.get('Host') not in ('127.0.0.1:'+str(server.server_port), 'localhost:'+str(server.server_port)):
                    self.send_error(403); return
                path = urlsplit(self.path).path
                if path == '/api/status':
                    payload = json.dumps(dashboard.status()).encode()
                    mime = 'application/json'
                elif path in ('/', '/index.html', '/style.css', '/app.js'):
                    file = dashboard.root / ('index.html' if path == '/' else path[1:])
                    try:
                        payload = file.read_bytes()
                    except OSError:
                        self.send_error(503, 'Dashboard assets unavailable'); return
                    mime = {'html':'text/html', 'css':'text/css', 'js':'text/javascript'}[file.suffix[1:]]
                else:
                    self.send_error(404); return
                self.send_response(200)
                self.send_header('Content-Type', mime+'; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers(); self.wfile.write(payload)
        server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server
