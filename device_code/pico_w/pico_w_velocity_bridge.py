"""Pico W: receive raw wheel PWM over UDP and forward it to the Zumo UART."""

import socket
import struct
import time
from machine import Pin, UART

from wifi_config import PASSWORD, SSID

UDP_PORT = 42001
PACKET_FORMAT = ">2sHhh"
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)
MAGIC = b"PW"
PWM_LIMIT = 6000
NETWORK_TIMEOUT_MS = 300
NETWORK_INFO_INTERVAL_MS = 5000
UART_BAUD = 115200

uart = UART(0, UART_BAUD, tx=Pin(0), rx=Pin(1))


def send_uart(sequence, left_pwm, right_pwm):
    uart.write("P,{},{},{}\n".format(sequence, left_pwm, right_pwm).encode())


def send_network_info(wlan):
    try:
        rssi = wlan.status("rssi")
    except Exception:
        rssi = ""
    uart.write("N,{},{},{}\n".format(wlan.ifconfig()[0], rssi, SSID).encode())


def connect_wifi():
    import network

    wlan = network.WLAN(network.STA_IF)
    while not wlan.isconnected():
        wlan.active(False)
        time.sleep_ms(500)
        wlan.active(True)
        try:
            wlan.config(pm=0xA11140)  # Disable power saving for control latency.
        except Exception:
            pass
        wlan.connect(SSID, PASSWORD)
        deadline = time.ticks_add(time.ticks_ms(), 15000)
        while not wlan.isconnected() and time.ticks_diff(deadline, time.ticks_ms()) > 0:
            time.sleep_ms(100)
        if not wlan.isconnected():
            print("Wi-Fi retry; status:", wlan.status())
            wlan.disconnect()
    print("PICO_W_IP", wlan.ifconfig()[0])
    return wlan


def main():
    wlan = connect_wifi()
    send_network_info(wlan)
    last_network_info_ms = time.ticks_ms()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", UDP_PORT))
    sock.setblocking(False)

    last_valid_ms = time.ticks_ms()
    last_command = None
    stopped = True
    stop_sequence = 0
    print("UDP_READY", UDP_PORT)

    try:
        while True:
            try:
                data, _address = sock.recvfrom(64)
            except OSError:
                data = None

            if data is not None and len(data) == PACKET_SIZE:
                magic, sequence, left_pwm, right_pwm = struct.unpack(PACKET_FORMAT, data)
                if magic == MAGIC and abs(left_pwm) <= PWM_LIMIT and abs(right_pwm) <= PWM_LIMIT:
                    send_uart(sequence, left_pwm, right_pwm)
                    command = (left_pwm, right_pwm)
                    if command != last_command:
                        print("UDP_PWM", left_pwm, right_pwm)
                        last_command = command
                    last_valid_ms = time.ticks_ms()
                    stop_sequence = sequence
                    stopped = left_pwm == 0 and right_pwm == 0

            now = time.ticks_ms()
            if not stopped and time.ticks_diff(now, last_valid_ms) > NETWORK_TIMEOUT_MS:
                stop_sequence = (stop_sequence + 1) & 0xFFFF
                send_uart(stop_sequence, 0, 0)
                stopped = True
                print("NETWORK_WATCHDOG_STOP")

            if not wlan.isconnected():
                if not stopped:
                    send_uart((stop_sequence + 1) & 0xFFFF, 0, 0)
                    stopped = True
                wlan = connect_wifi()
                send_network_info(wlan)
                last_network_info_ms = time.ticks_ms()
            elif time.ticks_diff(now, last_network_info_ms) >= NETWORK_INFO_INTERVAL_MS:
                send_network_info(wlan)
                last_network_info_ms = now

            time.sleep_ms(2)
    finally:
        send_uart((stop_sequence + 1) & 0xFFFF, 0, 0)
        sock.close()
        wlan.active(False)


main()
