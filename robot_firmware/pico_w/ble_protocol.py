"""Shared BLE GATT identifiers and compact status codec (CPython/MicroPython)."""
import struct
try:
    import hw_protocol as wire
except ImportError:
    from robot_firmware.zumo_hardware import hw_protocol as wire

SERVICE_UUID = '6e400001-b5a3-f393-e0a9-e50e24dcca9e'
RX_UUID = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'
TX_UUID = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'
PROTOCOL = 'zumo-hw-ble-v1'
STATUS = 0x20
POSE_FORMAT = '<BHHfffII'
REASONS = (None, 'no_telemetry', 'stale_telemetry', 'board_not_detected',
           'stale_camera_frame', 'marker_not_visible', 'closed', 'unavailable')


def status_payload(info, snapshot, stops, crc_errors, position=None):
    position = position or {}
    pose = position.get('pose')
    flags = int(bool(position.get('enabled'))) | (2 if pose else 0)
    reason = position.get('reason')
    reason_id = REASONS.index(reason) if reason in REASONS else 7
    age = position.get('feed_age_ms')
    compact_pose = struct.pack(POSE_FORMAT, flags, min(65535, position.get('marker_id', 1)), reason_id,
                               pose['x'] if pose else 0, pose['y'] if pose else 0,
                               pose['angle'] if pose else 0,
                               0xffffffff if age is None else min(0xfffffffe, max(0, age)),
                               position.get('packets', 0) & 0xffffffff)
    return info + snapshot + struct.pack('<HH', stops & 0xffff, crc_errors & 0xffff) + compact_pose


def decode_status(payload):
    expected = 12 + wire.SNAPSHOT_SIZE + 4 + struct.calcsize(POSE_FORMAT)
    if len(payload) != expected:
        raise ValueError('invalid BLE status size')
    baud, watchdog, mask, size = struct.unpack('<IIHH', payload[:12])
    snapshot = wire.decode_snapshot(payload[12:12 + wire.SNAPSHOT_SIZE])
    offset = 12 + wire.SNAPSHOT_SIZE
    stops, crc = struct.unpack('<HH', payload[offset:offset + 4])
    flags, marker, reason, x, y, angle, age, packets = struct.unpack(POSE_FORMAT, payload[offset + 4:])
    position = dict(enabled=bool(flags & 1), marker_id=marker,
                    reason=REASONS[reason] if reason < len(REASONS) else 'unavailable',
                    feed_age_ms=None if age == 0xffffffff else age, packets=packets,
                    pose=dict(id=marker, x=x, y=y, angle=angle) if flags & 2 else None)
    return dict(protocol=PROTOCOL, hardware=dict(baud=baud, motor_timeout_ms=watchdog,
                sensor_mask=mask, snapshot_bytes=size), hardware_pwm=list(snapshot['motor_pwm']),
                pwm=list(snapshot['motor_pwm']), encoders=list(snapshot['encoders']),
                battery_mv=snapshot['battery_mv'], disconnect_or_timeout_stops=stops,
                server_crc_errors=crc, position=position)
