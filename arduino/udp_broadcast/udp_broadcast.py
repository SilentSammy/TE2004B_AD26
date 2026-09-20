"""Send LED commands by Wi-Fi broadcast; time USB-serial acknowledgments."""

import argparse
import msvcrt
import socket
import statistics
import struct
import time

import serial
from serial.tools import list_ports


UDP_PORT = 4210


def serial_port(requested):
    if requested:
        return requested
    ports = [port.device for port in list_ports.comports()]
    if len(ports) == 1:
        return ports[0]
    raise SystemExit(
        "Specify --port COMx. Available ports: " + (", ".join(ports) or "none")
    )


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
        default="192.168.137.255",
        help="hotspot subnet broadcast address (default: 192.168.137.255)",
    )
    args = parser.parse_args()

    pending = {}
    samples = []
    sequence = 0
    line_buffer = bytearray()

    with serial.Serial(serial_port(args.port), 115200, timeout=0) as pico:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            print("Press 0 or 1 to control the LED; Ctrl+C to show statistics.")
            print(f"Broadcasting to {args.broadcast}:{UDP_PORT}")
            try:
                while True:
                    if msvcrt.kbhit():
                        key = msvcrt.getwch()
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
