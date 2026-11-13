#!/usr/bin/env python3
"""
bridge.py — True Plug & Go Multi-Session Serial Bridge Daemon for Arduino Traffic Light.

Features:
- Background Hardware Watchdog: Continuously monitors USB connection.
  When you plug in the Arduino, it automatically connects and immediately illuminates
  the correct LED within 2 seconds. No manual restart needed!
- True Plug & Go: Handles unplugs, replugs, and moving across USB ports seamlessly.
- Thread-Safe Communication: Decouples USB serial management from TCP hook requests.
- Multi-Session Priority Resolution:
  1. Blinking Red ('B'): If ANY session needs user input/permission
  2. Solid Red ('R'):    If ANY session encountered an error
  3. Solid Yellow ('Y'): If ANY session is currently working/thinking
  4. Solid Green ('G'):  When ALL active sessions are finished/ready
  5. Off ('O'):          When all sessions have ended
- Abandoned sessions expire after 24 hours; long running turns stay yellow.
"""

import os
import sys
import json
import time
import socket
import threading
from pathlib import Path
import serial
import serial.tools.list_ports
if __package__:
    from .dashboard import Dashboard, firmware_status
else:
    from dashboard import Dashboard, firmware_status

TCP_HOST = "127.0.0.1"
TCP_PORT = 8765
BAUD_RATE = 115200
try:
    with open(os.path.expanduser('~/.local/share/trafficlights/connection.json'), encoding='utf-8') as config_file:
        connection_config = json.load(config_file)
except FileNotFoundError:
    connection_config = {}
TRANSPORT = os.environ.get('TRAFFIC_TRANSPORT', connection_config.get('transport', 'serial')).lower()
STATE_FILE = os.path.expanduser(os.environ.get('TRAFFIC_STATE_FILE', '~/.local/share/trafficlights/sessions.json'))
bluetooth_link = None

# Registry & Hardware state
active_sessions = {}
current_hardware_state = 'G'
hardware_synced = False
ser_conn = None
ser_lock = threading.Lock()
firmware_report = None
pending_transition = None

def settle_transition():
    global pending_transition
    if pending_transition and time.monotonic() >= pending_transition[1]:
        state = pending_transition[0]
        pending_transition = None
        write_to_hardware(state)

def request_transition(state):
    global pending_transition
    if state == current_hardware_state:
        pending_transition = None
        return
    delay = {'G': 1.5, 'B': 0.8}.get(state, 0)
    if delay:
        if not pending_transition or pending_transition[0] != state:
            pending_transition = (state, time.monotonic() + delay)
    else:
        pending_transition = None
        write_to_hardware(state)

def find_serial_port():
    override = os.environ.get("TRAFFIC_PORT")
    if override:
        return override
    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        if p.vid == 0x239A and p.pid == 0x80B4:
            return p.device
    # 1. Prefer Arduino / CH340 / USB-Serial devices
    for p in ports:
        desc = (p.description or "").lower()
        hwid = (p.hwid or "").lower()
        if "1a86:7523" in hwid or "ch340" in desc or "arduino" in desc or "usb" in desc:
            return p.device
    # 2. Look for COM ports on Windows or USB ports on Mac/Linux
    for p in ports:
        if p.device.upper().startswith("COM") or "usb" in p.device.lower():
            return p.device
    return None

def hardware_watchdog(on_report=None):
    """
    Background worker that watches for the Arduino USB connection:
    - Auto-detects whenever you plug the Arduino into any port.
    - Waits for bootloader (1.8s) and immediately writes current state.
    - Detects disconnects and cleans up automatically.
    """
    global ser_conn, hardware_synced, firmware_report
    last_sync_time = time.time()
    incoming_buffer = b''
    while True:
        with ser_lock:
            # 1. If currently connected, check if port is still alive and send heartbeat
            if ser_conn is not None:
                port_alive = False
                try:
                    if os.name == 'nt':
                        port_alive = any(p.device.upper() == ser_conn.port.upper() for p in serial.tools.list_ports.comports())
                    else:
                        port_alive = os.path.exists(ser_conn.port)
                except Exception:
                    port_alive = False

                if not port_alive:
                    print(f"Warning: Arduino was unplugged from {ser_conn.port}.", flush=True)
                    try:
                        ser_conn.close()
                    except Exception:
                        pass
                    ser_conn = None
                    hardware_synced = False
                    firmware_report = None
                    if on_report:
                        on_report(None)
                else:
                    # Heartbeat: read any reboot message & periodically re-assert state
                    try:
                        # A read also initiates USB CDC transfers on macOS;
                        # polling in_waiting alone can leave data on the device.
                        incoming = ser_conn.read(4096)
                        if incoming:
                            incoming_buffer += incoming
                            while b'\n' in incoming_buffer:
                                line, incoming_buffer = incoming_buffer.split(b'\n', 1)
                                try:
                                    report = json.loads(line)
                                    if report.get('firmware') in ('traffic-nicenano-v1', 'traffic-esp32c3-v1'):
                                        report = firmware_status(report)
                                        firmware_report = report
                                        if on_report:
                                            on_report(report)
                                except (ValueError, AttributeError):
                                    pass
                            if b"TRAFFIC_LIGHT_READY" in incoming:
                                print(f"Arduino reboot detected! Re-syncing state [{current_hardware_state}]...", flush=True)
                                ser_conn.write(current_hardware_state.encode("utf-8"))
                                ser_conn.flush()
                        now = time.time()
                        if now - last_sync_time >= 3.0:
                            ser_conn.write(current_hardware_state.encode("utf-8"))
                            ser_conn.flush()
                            last_sync_time = now
                    except Exception as e:
                        print(f"Warning: Connection dropped ({e}). Watchdog will reconnect.", flush=True)
                        try:
                            ser_conn.close()
                        except Exception:
                            pass
                        ser_conn = None
                        hardware_synced = False
                        firmware_report = None
                        if on_report:
                            on_report(None)

            # 2. If not connected, scan and connect
            if ser_conn is None:
                port = find_serial_port()
                if port:
                    print(f"Detected Arduino on {port}! Connecting...", flush=True)
                    try:
                        ser = serial.Serial(port, BAUD_RATE, timeout=0.05)
                        # Bootloader delay
                        time.sleep(1.8)
                        if ser.in_waiting:
                            ser.read(ser.in_waiting)
                        # Immediately sync current state
                        ser.write(current_hardware_state.encode("utf-8"))
                        ser.flush()
                        ser_conn = ser
                        incoming_buffer = b''
                        hardware_synced = True
                        last_sync_time = time.time()
                        print(f"Plug & Go Ready: Connected to {port} and synced state [{current_hardware_state}]!", flush=True)
                    except Exception as e:
                        ser_conn = None
                        hardware_synced = False

        time.sleep(1.0)

def write_to_hardware(state_char):
    """Sends a state character to the Arduino (thread-safe)."""
    global current_hardware_state, hardware_synced, ser_conn
    current_hardware_state = state_char
    if TRANSPORT == 'ble':
        hardware_synced = bool(bluetooth_link and bluetooth_link.send(state_char.encode()))
        return hardware_synced

    with ser_lock:
        if ser_conn is not None and ser_conn.is_open:
            try:
                ser_conn.write(state_char.encode("utf-8"))
                ser_conn.flush()
                hardware_synced = True
                return True
            except Exception as e:
                print(f"Warning: Serial write failed ({e}). Watchdog will reconnect.", flush=True)
                try:
                    ser_conn.close()
                except Exception:
                    pass
                ser_conn = None
                hardware_synced = False
        return False

def compute_aggregate_state():
    """Calculates highest-priority state across all tracked sessions."""
    if not active_sessions:
        return 'G'

    states = [s["state"] for s in active_sessions.values()]

    if 'R' in states:
        return 'R'
    if 'Y' in states:
        return 'Y'
    if 'B' in states:
        return 'B'
    if 'G' in states:
        return 'G'

    return 'O'

def save_sessions():
    """Persist host state so a login helper restart restores ongoing chats."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    temporary = STATE_FILE + '.tmp'
    try:
        with open(temporary, 'w', encoding='utf-8') as file:
            json.dump(active_sessions, file)
        for attempt in range(5):
            try:
                os.replace(temporary, STATE_FILE)
                break
            except OSError:
                if attempt == 4:
                    raise
                time.sleep(0.05)
    except OSError as error:
        print(f"Could not persist bridge sessions: {error}", file=sys.stderr)

def restore_sessions():
    global current_hardware_state
    try:
        with open(STATE_FILE, encoding='utf-8') as file:
            saved = json.load(file)
        for sid, session in saved.items():
            if session.get('state') in ('G', 'Y', 'B', 'R') and time.time() - session['updated'] < 86400:
                # Older versions used bare Codex IDs. Migrate once without losing ongoing turns.
                key = sid if ":" in sid else "codex:" + sid
                active_sessions[key] = session
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    current_hardware_state = compute_aggregate_state()

def clean_stale_sessions():
    """Expire abandoned sessions and allow explicit questions to time out after an hour."""
    now = time.time()
    to_delete = []
    for sid, s in active_sessions.items():
        elapsed = now - s["updated"]
        if s.get('awaiting_user'):
            if elapsed > 3600:
                s["state"] = 'G'
                s.pop('awaiting_user', None)
                s["updated"] = now
        elif s.get("state") == 'B' and elapsed > 180:
            s["state"] = 'G'
            s["updated"] = now
        elif elapsed > 86400:
            to_delete.append(sid)

    for sid in to_delete:
        del active_sessions[sid]

def is_hardware_connected():
    if TRANSPORT == 'ble':
        return bool(bluetooth_link and bluetooth_link.connected)
    with ser_lock:
        return ser_conn is not None and ser_conn.is_open

def working_session_count():
    """Count only turns currently working, excluding ready/input/error records."""
    return sum(session["state"] == "Y" for session in tuple(active_sessions.values()))

def working_provider_mask():
    """Application identity from hook namespaces, never guessed model identity."""
    mask = 0
    for sid, session in tuple(active_sessions.items()):
        if session['state'] == 'Y':
            provider = sid.split(':', 1)[0]
            mask |= {'claude': 1, 'codex': 2, 'gemini': 4}.get(provider, 8)
    return mask

def get_active_port():
    if TRANSPORT == 'ble':
        return ('ble://' + bluetooth_link.peer) if is_hardware_connected() else None
    with ser_lock:
        return ser_conn.port if (ser_conn is not None and ser_conn.is_open) else None

def run_bridge():
    global current_hardware_state, ser_conn, hardware_synced, bluetooth_link, pending_transition
    print("=" * 60)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((TCP_HOST, TCP_PORT))
    except OSError:
        server.close()
        raise RuntimeError('Bridge port 8765 is occupied; stop the existing companion or inspect the listener.')
    server.listen(10)
    server.settimeout(0.5)

    restore_sessions()
    print("Clawdy local status service")
    print("=" * 60)

    assets = os.path.join(os.path.dirname(__file__), "web")
    if not os.path.isdir(assets):
        assets = os.path.join(os.path.dirname(__file__), "..", "web")
    dashboard = Dashboard(lambda: firmware_report, is_hardware_connected, assets)
    if TRANSPORT != 'local':
        try:
            dashboard.start()
        except OSError as error:
            print("Dashboard unavailable: " + str(error), flush=True)

    # Start the hardware watchdog thread
    if TRANSPORT == 'ble':
        from ble_transport import BluetoothLink
        def received(report):
            global firmware_report, hardware_synced
            report = firmware_status(report)
            firmware_report = report
            dashboard.received(report)
            hardware_synced = report is not None
        bluetooth_link = BluetoothLink(os.environ.get('TRAFFIC_BLE_NAME') or connection_config['ble_name'],
                                       lambda: current_hardware_state, received,
                                       get_session_count=working_session_count,
                                       get_provider_mask=working_provider_mask,
                                       device_id=connection_config.get('device_id'))
        bluetooth_link.start()
    elif TRANSPORT == 'serial':
        watchdog_thread = threading.Thread(target=hardware_watchdog, args=(dashboard.received,), daemon=True)
        watchdog_thread.start()

    print(f"Bridge TCP server listening on {TCP_HOST}:{TCP_PORT}...\n", flush=True)

    pid_file = Path(STATE_FILE).parent / 'bridge.pid'
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()), encoding='ascii')
    last_stale_check = time.time()
    try:
        while True:
            try:
                settle_transition()
            except Exception as e:
                print(f"Warning: settle_transition error: {e}", file=sys.stderr, flush=True)

            try:
                client, _ = server.accept()
                client.settimeout(2)
            except socket.timeout:
                try:
                    if time.time() - last_stale_check > 5:
                        last_stale_check = time.time()
                        clean_stale_sessions()
                        new_agg = compute_aggregate_state()
                        if new_agg != current_hardware_state:
                            save_sessions()
                            request_transition(new_agg)
                except Exception as e:
                    print(f"Warning: Stale check error: {e}", file=sys.stderr, flush=True)
                continue
            try:
                raw_data = client.recv(1024).decode("utf-8", errors="ignore").strip()
                if not raw_data:
                    client.close()
                    continue

                session_id = "default"
                cmd = "G"
                hook_event = ""
                awaiting_user = False

                if raw_data.startswith("{") and raw_data.endswith("}"):
                    try:
                        payload = json.loads(raw_data)

                        if payload.get("action") == "shutdown":
                            client.sendall(b'{"status":"stopping"}\n')
                            return

                        # Status query
                        if payload.get("action") == "status":
                            clean_stale_sessions()
                            current_agg = compute_aggregate_state()
                            resp_data = {
                                "status": "ok",
                                "aggregate": current_agg if active_sessions else "O",
                                "hardware_connected": is_hardware_connected(),
                                "port": get_active_port(),
                                "transport": TRANSPORT,
                                "connection_error": bluetooth_link.last_error if bluetooth_link else None,
                                "firmware_report": firmware_report,
                                "active_sessions": {
                                    sid: s["state"] for sid, s in active_sessions.items()
                                }
                            }
                            client.sendall(json.dumps(resp_data).encode("utf-8") + b"\n")
                            client.close()
                            continue

                        # Reset action
                        if payload.get('action') == 'hardware_test':
                            if TRANSPORT == 'local':
                                client.sendall(b'{"status":"no_hardware"}\n')
                                continue
                            test_state = payload.get('state')
                            if test_state not in ('G', 'Y', 'R', 'B', 'O'):
                                raise ValueError('Invalid hardware test state')
                            pending_transition = None
                            write_to_hardware(test_state)
                            client.sendall(b'{"status":"test_started"}\n')
                            continue
                        if payload.get('action') == 'resume':
                            write_to_hardware(compute_aggregate_state())
                            client.sendall(b'{"status":"tracking_restored"}\n')
                            continue

                        if payload.get("action") in ("reset", "clear"):
                            active_sessions.clear()
                            save_sessions()
                            write_to_hardware('G')
                            client.sendall(b'{"status": "reset_ok"}\n')
                            client.close()
                            continue

                        session_id = payload.get("session_id", "default")
                        cmd = payload.get("state", "G").upper()
                        hook_event = str(payload.get("hook_event") or "").upper()
                        awaiting_user = payload.get("awaiting_user") is True
                    except Exception:
                        cmd = raw_data.upper()
                else:
                    cmd = raw_data.upper()

                if cmd in ('RESET', 'CLEAR'):
                    active_sessions.clear()
                    new_state = 'G'
                elif cmd in ('R', 'B', 'Y', 'G', 'O', 'T'):
                    clean_stale_sessions()
                    existing = active_sessions.get(session_id, {})
                    resolves_input = hook_event in ('USERPROMPTSUBMIT', 'INTERRUPT', 'SESSIONSTART')
                    if cmd == 'O':
                        if session_id in active_sessions:
                            del active_sessions[session_id]
                    elif existing.get('awaiting_user') and cmd in ('Y', 'G') and not resolves_input:
                        # Keep blinking red while the explicit question is awaiting a reply.
                        pass
                    else:
                        session_state = {"state": cmd, "updated": time.time()}
                        if cmd == 'B' and awaiting_user:
                            session_state['awaiting_user'] = True
                        active_sessions[session_id] = session_state
                    new_state = compute_aggregate_state() if cmd != 'T' else 'T'
                else:
                    new_state = current_hardware_state

                # Update physical hardware if state changed, test requested, or not synced
                save_sessions()
                request_transition(new_state)
                if new_state != current_hardware_state or cmd == 'T' or not hardware_synced:
                    summary = f"[{new_state}] (Active Sessions: {len(active_sessions)})"
                    print(f"Hardware -> {summary} | Triggered by '{session_id[:12]}' -> {cmd}", flush=True)

                client.sendall(json.dumps({
                    "status": "ok",
                    "aggregate": current_hardware_state,
                    "hardware_connected": is_hardware_connected(),
                    "active_sessions": len(active_sessions)
                }).encode("utf-8") + b"\n")

            except Exception as e:
                print(f"Warning: Bridge request error: {e}", file=sys.stderr, flush=True)
            finally:
                client.close()

    except KeyboardInterrupt:
        print("\nStopping bridge...", flush=True)
    finally:
        if pid_file.exists() and pid_file.read_text(encoding='ascii') == str(os.getpid()):
            pid_file.unlink()
        try:
            with ser_lock:
                if ser_conn and ser_conn.is_open:
                    ser_conn.write(b'O')
                    ser_conn.close()
            server.close()
        except Exception:
            pass

if __name__ == "__main__":
    run_bridge()
