"""Build a local Mac helper with an explicit Bluetooth usage description."""
from setuptools import setup

setup(name='Traffic Light Bridge', app=['bluetooth_app.py'], options={'py2app': {
    'argv_emulation': False,
    'plist': {
        'CFBundleName': 'Traffic Light Bridge',
        'CFBundleDisplayName': 'Traffic Light Bridge',
        'CFBundleIdentifier': 'local.trafficlights.bluetooth',
        'LSUIElement': True,
        'NSBluetoothAlwaysUsageDescription': 'Send chat activity to your Bluetooth traffic light.',
        'NSBluetoothPeripheralUsageDescription': 'Connect to your traffic light LEDs.'
    }
}})
