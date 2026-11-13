"""Entry point for the macOS Bluetooth login helper."""
import json
import os
from pathlib import Path
import sys

runtime = Path.home() / '.local' / 'share' / 'trafficlights'
config = json.loads((runtime / 'connection.json').read_text())
os.environ['TRAFFIC_TRANSPORT'] = config['transport']
os.environ['TRAFFIC_BLE_NAME'] = config['ble_name']
sys.path.insert(0, str(runtime))
import bridge
bridge.run_bridge()
