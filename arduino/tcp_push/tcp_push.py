"""Push LED commands over persistent TCP and time TCP/USB acknowledgments."""

import argparse
import msvcrt
import select
import socket
import statistics
import struct
import time

import serial
from serial.tools import list_ports


TCP_PORT = 4212


def serial_port(requested):
    if requested:
        return requested
    ports = [port.device for port in list_ports.comports()]
    if len(ports) == 1:
        return ports[0]
    raise SystemExit(
        "Specify --port COMx. Available ports: " + (", ".join(ports) or "none")
    )


def print_path_stats(label, samples, sent_count):
    print(f"{label}: acknowledged {len(samples)}/{sent_count}")
    if not samples:
        return
    values = sorted(samples)
    p95_index = max(0, (95 * len(values) + 99) // 100 - 1)
    print(
        f"  Latency (ms): min {values[0]:.2f}, "
        f"mean {statistics.mean(values):.2f}, "
        f"median {statistics.median(values):.2f}, "
        f"p95 {values[p95_index]:.2f}, max {values[-1]:.2f}"
    )


def close_client(client, clients):
    details = clients.pop(client, None)
    if details is not None:
        print(f"Disconnected {details['name']}")
    client.close()


def process_tcp_data(client, data, received_at, clients, pending, tcp_samples):
    details = clients[client]
    buffer = details["buffer"]
    buffer.extend(data)
    while buffer:
        marker = buffer[0]
        frame_size = 7 if marker == ord("H") else 6 if marker == ord("A") else 0
        if frame_size == 0:
            del buffer[0]
            continue
        if len(buffer) < frame_size:
            break
        frame = bytes(buffer[:frame_size])
        del buffer[:frame_size]
        if marker == ord("H"):
            device_id = ":".join(f"{value:02x}" for value in frame[1:])
            details["name"] = device_id
            print(f"Registered {device_id} at {details['address']}")
        else:
            sequence = struct.unpack("!I", frame[1:5])[0]
            command = chr(frame[5])
            item = pending.get(sequence)
            if item and item["command"] == command and not item["tcp_received"]:
                item["tcp_received"] = True
                latency_ms = (received_at - item["sent_at"]) / 1_000_000
                tcp_samples.append(latency_ms)
                print(f"#{sequence} TCP ACK: {latency_ms:.2f} ms")
                if item["serial_received"]:
                    del pending[sequence]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="Pico USB serial port, for example COM5")
    args = parser.parse_args()

    clients = {}  # socket -> address, name, and receive buffer
    pending = {}  # sequence -> command, send time, and acknowledgment flags
    tcp_samples = []
    serial_samples = []
    line_buffer = bytearray()
    sequence = 0
    command_count = 0

    with serial.Serial(serial_port(args.port), 115200, timeout=0) as pico:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("", TCP_PORT))
            server.listen()
            server.setblocking(False)
            print(f"Listening for Picos on TCP port {TCP_PORT}.")
            print("Press 0 or 1 to control the LED; Ctrl+C for statistics.")
            try:
                while True:
                    if msvcrt.kbhit():
                        key = msvcrt.getwch()
                        if key == "\x03":
                            break
                        if key in ("0", "1"):
                            if not clients:
                                print("No Pico connected yet.")
                                continue
                            sequence = (sequence + 1) & 0xFFFFFFFF
                            packet = struct.pack("!I", sequence) + key.encode("ascii")
                            print(f"Sending {key} (#{sequence}) to {len(clients)} Pico(s)")
                            sent_at = time.perf_counter_ns()
                            pending[sequence] = {
                                "command": key,
                                "sent_at": sent_at,
                                "tcp_received": False,
                                "serial_received": False,
                            }
                            sent_to = 0
                            for client in list(clients):
                                try:
                                    client.sendall(packet)
                                    sent_to += 1
                                except OSError:
                                    close_client(client, clients)
                            if sent_to:
                                command_count += 1
                            else:
                                del pending[sequence]

                    readable, _, _ = select.select([server, *clients], [], [], 0)
                    for ready in readable:
                        if ready is server:
                            while True:
                                try:
                                    client, (address, _) = server.accept()
                                except BlockingIOError:
                                    break
                                client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                                clients[client] = {
                                    "address": address,
                                    "name": address,
                                    "buffer": bytearray(),
                                }
                                print(f"Connected {address}")
                        else:
                            try:
                                data = ready.recv(4096)
                                received_at = time.perf_counter_ns()
                            except OSError:
                                close_client(ready, clients)
                                continue
                            if data:
                                process_tcp_data(
                                    ready, data, received_at, clients, pending, tcp_samples
                                )
                            else:
                                close_client(ready, clients)

                    incoming = pico.read(pico.in_waiting or 1)
                    if incoming:
                        received_at = time.perf_counter_ns()
                        line_buffer.extend(incoming)
                        while b"\n" in line_buffer:
                            raw_line, _, rest = line_buffer.partition(b"\n")
                            line_buffer = bytearray(rest)
                            line = raw_line.decode("ascii", errors="replace").strip()
                            parts = line.split()
                            if len(parts) == 3 and parts[0] == "ACK":
                                try:
                                    ack_sequence = int(parts[1])
                                except ValueError:
                                    continue
                                item = pending.get(ack_sequence)
                                if item and item["command"] == parts[2] and not item["serial_received"]:
                                    item["serial_received"] = True
                                    latency_ms = (received_at - item["sent_at"]) / 1_000_000
                                    serial_samples.append(latency_ms)
                                    state = "ON" if parts[2] == "1" else "OFF"
                                    print(f"#{ack_sequence} LED {state}, USB ACK: {latency_ms:.2f} ms")
                                    if item["tcp_received"]:
                                        del pending[ack_sequence]
                            elif line:
                                print(f"Pico: {line}")
                        if len(line_buffer) > 256:
                            line_buffer.clear()
                    else:
                        time.sleep(0.001)
            except KeyboardInterrupt:
                pass
            finally:
                for client in list(clients):
                    client.close()
                print("\nFinal statistics")
                print_path_stats("TCP", tcp_samples, command_count)
                print_path_stats("USB serial", serial_samples, command_count)


if __name__ == "__main__":
    main()
