"""Send LED commands by Wi-Fi broadcast; time USB-serial acknowledgments."""

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


UDP_PORT = 4210


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


def print_stats(samples, pending):
    print("\nFinal statistics")
    print(f"Acknowledged: {len(samples)}; still unacknowledged: {len(pending)}")
    if not samples:
        return
    values = sorted(samples)
    p95_index = max(0, (95 * len(values) + 99) // 100 - 1)
    print(
        f"Latency (ms): min {values[0]:.2f}, "
        f"mean {statistics.mean(values):.2f}, "
        f"median {statistics.median(values):.2f}, "
        f"p95 {values[p95_index]:.2f}, max {values[-1]:.2f}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="Pico USB serial port, for example COM5")
    parser.add_argument(
        "--broadcast",
        default=guess_broadcast(),
        help="hotspot subnet broadcast address (default: auto-detected from local IP)",
    )
    args = parser.parse_args()

    pending = {}
    samples = []
    sequence = 0
    line_buffer = bytearray()

    with serial.Serial(serial_port(args.port), 115200, timeout=0) as pico, keyboard_reader() as read_key:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            print("Press 0 or 1; Ctrl+C for statistics.")
            print(f"Broadcasting to {args.broadcast}:{UDP_PORT}")
            try:
                while True:
                    key = read_key()
                    if key is not None:
                        key = key.lower()
                        if key == "\x03":
                            break
                        if key in ("0", "1"):
                            sequence = (sequence + 1) & 0xFFFFFFFF
                            packet = struct.pack("!I", sequence) + key.encode("ascii")
                            print(f"Sending {key} (#{sequence})")
                            sent_at = time.perf_counter_ns()
                            pending[sequence] = (key, sent_at)
                            try:
                                udp.sendto(packet, (args.broadcast, UDP_PORT))
                            except OSError:
                                del pending[sequence]
                                raise

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
                                if item and item[0] == parts[2]:
                                    del pending[ack_sequence]
                                    latency_ms = (received_at - item[1]) / 1_000_000
                                    samples.append(latency_ms)
                                    print(f"#{ack_sequence} LED {'ON' if parts[2] == '1' else 'OFF'}: {latency_ms:.2f} ms")
                            elif line:
                                print(f"Pico: {line}")
                        if len(line_buffer) > 256:
                            line_buffer.clear()
                    else:
                        time.sleep(0.001)
            except KeyboardInterrupt:
                pass
            finally:
                print_stats(samples, pending)


if __name__ == "__main__":
    main()
