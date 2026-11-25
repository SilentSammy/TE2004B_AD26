"""Read-only eight-second feed check on an already Wi-Fi-connected Pico W."""
import json
import time
import network
from pose_client import PoseSubscriber

if not network.WLAN(network.STA_IF).isconnected():
    raise RuntimeError('Connect the Pico W to the vision LAN first')
with PoseSubscriber('192.168.12.1', marker_id=1) as position:
    start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start) < 8000:
        position.poll()
        time.sleep_ms(10)
    print('POSITION_STATUS', json.dumps(position.status()))
