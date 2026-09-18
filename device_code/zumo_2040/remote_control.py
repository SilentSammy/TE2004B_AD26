"""Zumo 2040: receive raw left/right PWM over UART and drive the motors."""

import time
from machine import Pin, UART
from zumo_2040_robot import robot

UART_BAUD = 115200
UART_TIMEOUT_MS = 350
PWM_LIMIT = 6000
DISPLAY_INTERVAL_MS = 250

uart = UART(0, UART_BAUD, tx=Pin(28), rx=Pin(29))
motors = robot.Motors()
display = robot.Display()
motors.off()


def main():
    buffer = b""
    last_valid_ms = time.ticks_ms()
    last_command = None
    stopped = True

    network_ssid = "WiFi: waiting"
    network_ip = "IP: waiting"
    network_rssi = ""
    current_left = 0
    current_right = 0
    current_sequence = 0
    display_dirty = True
    last_display_ms = time.ticks_add(time.ticks_ms(), -DISPLAY_INTERVAL_MS)

    print("ZUMO_UART_READY")

    try:
        while True:
            if uart.any():
                chunk = uart.read()
                if chunk:
                    buffer += chunk
                    if len(buffer) > 256:
                        buffer = buffer[-128:]

                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    try:
                        parts = line.decode().split(",", 3)
                        kind = parts[0]

                        if kind == "N" and len(parts) == 4:
                            ip, rssi, ssid = parts[1:]
                            network_ssid = "WiFi: " + ssid
                            network_ip = ip
                            network_rssi = "RSSI: " + rssi + " dBm" if rssi else ""
                            display_dirty = True
                            continue

                        if kind != "P" or len(parts) != 4:
                            continue

                        sequence = int(parts[1])
                        left_pwm = int(parts[2])
                        right_pwm = int(parts[3])
                        if abs(left_pwm) > PWM_LIMIT or abs(right_pwm) > PWM_LIMIT:
                            continue
                        motors.set_speeds(left_pwm, right_pwm)
                        command = (left_pwm, right_pwm)
                        if command != last_command:
                            print("UART_PWM", left_pwm, right_pwm)
                            last_command = command
                        current_left = left_pwm
                        current_right = right_pwm
                        current_sequence = sequence
                        display_dirty = True
                        last_valid_ms = time.ticks_ms()
                        stopped = left_pwm == 0 and right_pwm == 0
                    except (ValueError, UnicodeError):
                        pass

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
                display.text("SEQ {}".format(current_sequence)[:16], 0, 49)
                display.show()
                last_display_ms = now
                display_dirty = False

            time.sleep_ms(2)
    finally:
        motors.off()


main()
