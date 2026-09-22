"""Zumo 2040: manage its own UDP subscriptions and drive the motors.

Works with arduino/generic_udp_relay/generic_udp_relay.ino: this file writes
bare port numbers (e.g. "5000\\n") to its own UART periodically to subscribe
to and keep alive whichever UDP ports it cares about. The Pico W relays
whatever arrives on those ports back over the same UART, tagged with the
source port, e.g. "5000 {...}".

Port numbers and their meaning are defined entirely here, not in the sketch:
- TELEMETRY_PORT: {"markers": [...], "board_detected": bool, ...} for display.
- COMMAND_PORT: {"l": <int>, "r": <int>} to drive the motors.
- Port 0 is reserved by the sketch for its own {"ip", "rssi", "ssid"} info.
"""

import time
import json
from machine import Pin, UART
from zumo_2040_robot import robot

UART_BAUD = 115200
UART_TIMEOUT_MS = 350
PWM_LIMIT = 6000
DISPLAY_INTERVAL_MS = 250

TELEMETRY_PORT = 5000
COMMAND_PORT = 5002  # Must not collide with the sketch's fixed DISCOVERY_PORT (5001).
# Only subscribe to what this script actually needs right now. Add
# TELEMETRY_PORT back here if you also want board/marker info on the display.
SUBSCRIBED_PORTS = (COMMAND_PORT,)
RENEW_INTERVAL_MS = 4000  # Well under the sketch's 10s lease, for margin.

uart = UART(0, UART_BAUD, tx=Pin(28), rx=Pin(29))
motors = robot.Motors()
display = robot.Display()
motors.off()


def parse_line(line):
    port_str, _, payload = line.partition(" ")
    return int(port_str), json.loads(payload)


def main():
    buffer = b""
    last_valid_ms = time.ticks_ms()
    last_renew_ms = time.ticks_add(time.ticks_ms(), -RENEW_INTERVAL_MS)
    last_command = None
    stopped = True

    current_left = 0
    current_right = 0
    commands_received = 0
    telemetry_markers = 0
    board_detected = False
    network_ip = "IP: waiting"
    network_ssid = "WiFi: waiting"
    network_rssi = ""
    display_dirty = True
    last_display_ms = time.ticks_add(time.ticks_ms(), -DISPLAY_INTERVAL_MS)

    print("ZUMO_UART_READY")

    try:
        while True:
            now = time.ticks_ms()
            if time.ticks_diff(now, last_renew_ms) >= RENEW_INTERVAL_MS:
                for port in SUBSCRIBED_PORTS:
                    uart.write("{}\n".format(port))
                last_renew_ms = now

            if uart.any():
                chunk = uart.read()
                if chunk:
                    buffer += chunk
                    if len(buffer) > 1024:
                        buffer = buffer[-512:]

                while b"\n" in buffer:
                    raw_line, buffer = buffer.split(b"\n", 1)
                    try:
                        port, data = parse_line(raw_line.decode().strip())
                    except (ValueError, UnicodeError):
                        continue

                    if port == COMMAND_PORT:
                        left_pwm = int(data["l"])
                        right_pwm = int(data["r"])
                        if abs(left_pwm) > PWM_LIMIT or abs(right_pwm) > PWM_LIMIT:
                            continue
                        motors.set_speeds(left_pwm, right_pwm)
                        command = (left_pwm, right_pwm)
                        if command != last_command:
                            print("UART_PWM", left_pwm, right_pwm)
                            last_command = command
                        current_left = left_pwm
                        current_right = right_pwm
                        commands_received += 1
                        display_dirty = True
                        last_valid_ms = time.ticks_ms()
                        stopped = left_pwm == 0 and right_pwm == 0
                    elif port == TELEMETRY_PORT:
                        board_detected = bool(data.get("board_detected"))
                        telemetry_markers = len(data["markers"])
                        display_dirty = True
                    elif port == 0:
                        network_ip = str(data.get("ip", ""))
                        network_ssid = "WiFi: " + str(data.get("ssid", ""))
                        rssi = data.get("rssi")
                        network_rssi = "RSSI: {} dBm".format(rssi) if rssi is not None else ""
                        display_dirty = True

            now = time.ticks_ms()
            if not stopped and time.ticks_diff(now, last_valid_ms) > UART_TIMEOUT_MS:
                motors.off()
                current_left = 0
                current_right = 0
                display_dirty = True
                stopped = True
                print("UART_WATCHDOG_STOP")

            if display_dirty and time.ticks_diff(now, last_display_ms) >= DISPLAY_INTERVAL_MS:
                display.fill(0)
                display.text(network_ssid[:16], 0, 0)
                display.text(network_ip[:16], 0, 11)
                display.text(network_rssi[:16], 0, 22)
                display.text(
                    "L:{:+5d} R:{:+5d}".format(current_left, current_right), 0, 36
                )
                display.text("CMDS {}".format(commands_received)[:16], 0, 49)
                display.show()
                last_display_ms = now
                display_dirty = False

            time.sleep_ms(2)
    finally:
        motors.off()


main()
