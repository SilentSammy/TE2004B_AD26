"""Pico W HTTP server that acknowledges each request over USB stdout."""

import socket
import time

from wifi_config import PASSWORD, SSID

HTTP_PORT = 8080
MAX_REQUEST_BYTES = 1024


def connect_wifi():
    import network

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    try:
        wlan.config(pm=0xA11140)
    except Exception:
        pass

    if not wlan.isconnected():
        wlan.connect(SSID, PASSWORD)
        deadline = time.ticks_add(time.ticks_ms(), 15000)
        while not wlan.isconnected() and time.ticks_diff(deadline, time.ticks_ms()) > 0:
            time.sleep_ms(50)

    if not wlan.isconnected():
        raise RuntimeError("Wi-Fi connection failed: {}".format(wlan.status()))
    return wlan


def read_request(connection):
    request = b""
    while b"\r\n\r\n" not in request and len(request) < MAX_REQUEST_BYTES:
        chunk = connection.recv(256)
        if not chunk:
            break
        request += chunk
    return request


def request_id(request):
    try:
        target = request.split(b"\r\n", 1)[0].split(b" ")[1]
    except (IndexError, ValueError):
        return None

    marker = b"id="
    marker_index = target.find(marker)
    if marker_index < 0:
        return None
    value = target[marker_index + len(marker) :].split(b"&", 1)[0]
    if not value or any(character not in b"0123456789abcdefABCDEF" for character in value):
        return None
    return value.decode()


def send_response(connection, status, body):
    payload = body.encode()
    response = (
        "HTTP/1.1 {}\r\n"
        "Content-Type: text/plain\r\n"
        "Content-Length: {}\r\n"
        "Connection: close\r\n\r\n"
    ).format(status, len(payload)).encode() + payload
    connection.sendall(response)


def main():
    wlan = connect_wifi()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", HTTP_PORT))
    server.listen(1)

    print("READY", wlan.ifconfig()[0], HTTP_PORT)

    try:
        while True:
            connection, _address = server.accept()
            try:
                identifier = request_id(read_request(connection))
                if identifier is None:
                    send_response(connection, "400 Bad Request", "missing or invalid id\n")
                    continue

                print("ACK", identifier)
                send_response(connection, "204 No Content", "")
            except OSError:
                pass
            finally:
                connection.close()
    finally:
        server.close()


main()