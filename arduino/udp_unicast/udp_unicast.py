"""Discover Picos and time Wi-Fi and USB-serial LED acknowledgments."""

import argparse
from contextlib import contextmanager
import os
import socket
import statistics
import struct
import subprocess
import sys
import time

if os.name == "nt":
    import msvcrt
else:
    import select
    import termios
    import tty

import serial
from serial.tools import list_ports


COMMAND_PORT = 4210
REGISTRATION_PORT = 4211


@contextmanager
def keyboard_reader():
    if os.name == "nt":
        def read_key():
            return msvcrt.getwch() if msvcrt.kbhit() else None

        yield read_key
        return

    if not sys.stdin.isatty():
        raise SystemExit("Run this script in a terminal to read 0/1 without Enter.")
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    try:
        def read_key():
            if select.select([fd], [], [], 0)[0]:
                return os.read(fd, 1).decode("ascii", errors="ignore")
            return None

        yield read_key
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def serial_port(requested):
    if requested:
        return requested
    ports = [port.device for port in list_ports.comports()]
    if len(ports) == 1:
        return ports[0]
    raise SystemExit(
        "Specify --port COMx. Available ports: " + (", ".join(ports) or "none")
    )


def guess_broadcast():
    # Read assigned addresses directly; works even with no default route,
    # e.g. when this machine is hosting the hotspot itself.
    try:
        output = subprocess.check_output(["ip", "-o", "-4", "addr", "show"], text=True)
        for line in output.splitlines():
            fields = line.split()
            if fields[1] != "lo" and "brd" in fields and "global" in fields:
                return fields[fields.index("brd") + 1]
    except (OSError, subprocess.CalledProcessError, IndexError, ValueError):
        pass

    # Fall back for platforms without `ip` (e.g. Windows): probe a route and
    # assume a /24 subnet, true for every hotspot tested so far. Pass
    # --broadcast explicitly if this guess is wrong.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))  # No packet sent; just picks a local route.
            local_ip = probe.getsockname()[0]
    except OSError:
        return "192.168.137.255"
    return local_ip.rsplit(".", 1)[0] + ".255"


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


def print_duration_stats(label, samples):
    if not samples:
        return
    values = sorted(samples)
    p95_index = max(0, (95 * len(values) + 99) // 100 - 1)
    print(
        f"{label} (us): median {statistics.median(values):.0f}, "
        f"p95 {values[p95_index]}, max {values[-1]}"
    )


def print_stats(wifi_samples, serial_samples, led_samples, parse_samples, wifi_gaps, sent_count):
    print("\nFinal statistics")
    print_path_stats("Wi-Fi", wifi_samples, sent_count)
    print_path_stats("USB serial", serial_samples, sent_count)
    print_duration_stats("Pico LED write", led_samples)
    print_duration_stats("Pico UDP parse", parse_samples)
    if wifi_gaps:
        slow = [(latency, gap) for latency, gap in zip(wifi_samples, wifi_gaps) if latency > 20]
        delayed_host = sum(gap > 20 for _, gap in slow)
        print(
            f"Wi-Fi ACKs over 20 ms: {len(slow)}; of those, {delayed_host} "
            "had a host receive-loop gap over 20 ms"
        )


def parse_serial_ack(line):
    parts = line.split()
    if len(parts) != 5 or parts[0] != "ACK":
        return None
    try:
        sequence = int(parts[1])
        led_us = int(parts[3].removeprefix("LED_US="))
        parse_us = int(parts[4].removeprefix("PARSE_US="))
    except ValueError:
        return None
    if parts[2] not in ("0", "1") or not parts[3].startswith("LED_US=") or not parts[4].startswith("PARSE_US="):
        return None
    return sequence, parts[2], led_us, parse_us


def discover(udp, broadcast):
    udp.sendto(b"DISCOVER", (broadcast, COMMAND_PORT))
    print("Looking for Picos...")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="Pico USB serial port, for example COM5")
    parser.add_argument(
        "--broadcast",
        default=guess_broadcast(),
        help="hotspot subnet broadcast address (default: auto-detected from local IP)",
    )
    args = parser.parse_args()

    devices = {}  # MAC address -> current IP address
    pending = {}  # sequence -> command, send time, and acknowledgment flags
    wifi_samples = []
    serial_samples = []
    led_samples = []
    parse_samples = []
    wifi_gaps = []
    line_buffer = bytearray()
    sequence = 0

    with serial.Serial(serial_port(args.port), 115200, timeout=0) as pico, keyboard_reader() as read_key:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            udp.bind(("", REGISTRATION_PORT))
            udp.setblocking(False)
            print("Press 0 or 1; d to rediscover; Ctrl+C for statistics.")
            discover(udp, args.broadcast)
            next_discovery = time.monotonic() + 2
            last_receive_check = time.perf_counter_ns()
            try:
                while True:
                    key = read_key()
                    if key is not None:
                        key = key.lower()
                        if key == "\x03":
                            break
                        if key == "d":
                            discover(udp, args.broadcast)
                        elif key in ("0", "1"):
                            if not devices:
                                print("No Pico registered yet. Press d to rediscover.")
                                continue
                            sequence = (sequence + 1) & 0xFFFFFFFF
                            packet = struct.pack("!I", sequence) + key.encode("ascii")
                            print(f"Sending {key} (#{sequence}) to {len(devices)} Pico(s)")
                            sent_at = time.perf_counter_ns()
                            pending[sequence] = {
                                "command": key,
                                "sent_at": sent_at,
                                "wifi_received": False,
                                "serial_received": False,
                                "max_host_gap_ms": 0.0,
                            }
                            try:
                                for address in devices.values():
                                    udp.sendto(packet, (address, COMMAND_PORT))
                            except OSError:
                                del pending[sequence]
                                raise

                    receive_check = time.perf_counter_ns()
                    for item in pending.values():
                        gap_ms = (receive_check - max(last_receive_check, item["sent_at"])) / 1_000_000
                        item["max_host_gap_ms"] = max(item["max_host_gap_ms"], gap_ms)
                    last_receive_check = receive_check

                    while True:
                        try:
                            data, (address, _) = udp.recvfrom(128)
                            received_at = time.perf_counter_ns()
                        except BlockingIOError:
                            break
                        if len(data) == 8 and data.startswith(b"ACK"):
                            ack_sequence = struct.unpack("!I", data[3:7])[0]
                            item = pending.get(ack_sequence)
                            if item and item["command"] == chr(data[7]) and not item["wifi_received"]:
                                item["wifi_received"] = True
                                latency_ms = (received_at - item["sent_at"]) / 1_000_000
                                wifi_samples.append(latency_ms)
                                wifi_gaps.append(item["max_host_gap_ms"])
                                print(
                                    f"#{ack_sequence} Wi-Fi ACK: {latency_ms:.2f} ms "
                                    f"(max host poll gap {item['max_host_gap_ms']:.2f} ms)"
                                )
                                if item["serial_received"]:
                                    del pending[ack_sequence]
                        elif data.startswith(b"HELLO "):
                            device_id = data[6:].decode("ascii", errors="replace")
                            if device_id and devices.get(device_id) != address:
                                devices[device_id] = address
                                print(f"Registered {device_id} at {address}")

                    if not devices and time.monotonic() >= next_discovery:
                        discover(udp, args.broadcast)
                        next_discovery = time.monotonic() + 2

                    incoming = pico.read(pico.in_waiting or 1)
                    if incoming:
                        received_at = time.perf_counter_ns()
                        line_buffer.extend(incoming)
                        while b"\n" in line_buffer:
                            raw_line, _, rest = line_buffer.partition(b"\n")
                            line_buffer = bytearray(rest)
                            line = raw_line.decode("ascii", errors="replace").strip()
                            ack = parse_serial_ack(line)
                            if ack:
                                ack_sequence, command, led_us, parse_us = ack
                                item = pending.get(ack_sequence)
                                if item and item["command"] == command and not item["serial_received"]:
                                    item["serial_received"] = True
                                    latency_ms = (received_at - item["sent_at"]) / 1_000_000
                                    serial_samples.append(latency_ms)
                                    led_samples.append(led_us)
                                    parse_samples.append(parse_us)
                                    state = "ON" if command == "1" else "OFF"
                                    print(
                                        f"#{ack_sequence} LED {state}, USB ACK: {latency_ms:.2f} ms "
                                        f"(LED write {led_us} us, UDP parse {parse_us} us)"
                                    )
                                    if item["wifi_received"]:
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
                print_stats(
                    wifi_samples, serial_samples, led_samples, parse_samples, wifi_gaps, sequence
                )


if __name__ == "__main__":
    main()
