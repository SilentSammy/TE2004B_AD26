"""Minimal UDP-based robot discovery."""

import json
import socket
import time


DISCOVERY_PORT = 42004
BROADCAST_ADDR = "255.255.255.255"
DISCOVERY_TIMEOUT = 2.0
DISCOVERY_REQUEST = b"ZUMO_DISCOVER_V1"


def discover(timeout=DISCOVERY_TIMEOUT):
    """Broadcast discovery request and collect responses.

    Returns a dict of {robot_id: info} or empty dict if none respond.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)

    try:
        sock.sendto(DISCOVERY_REQUEST, (BROADCAST_ADDR, DISCOVERY_PORT))
        robots = {}
        end = time.monotonic() + timeout

        while time.monotonic() < end:
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                data, addr = sock.recvfrom(512)
                info = json.loads(data.decode())
                robot_id = info.get("robot_id", "unknown")
                robots[robot_id] = info
            except socket.timeout:
                break
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

        return robots
    finally:
        sock.close()


def select_robot(robots):
    """Select a robot from discovered list, or return None.

    If exactly one is found, return it automatically.
    If multiple are found, prompt the user.
    """
    if not robots:
        return None
    if len(robots) == 1:
        return list(robots.values())[0]

    print("\nMultiple robots found:")
    items = list(robots.items())
    for i, (robot_id, info) in enumerate(items):
        ip = info.get("ip", "?")
        name = info.get("name", robot_id)
        print(f"  {i + 1}. {name} ({robot_id}) at {ip}")

    while True:
        try:
            choice = int(input("Select robot number: "))
            if 1 <= choice <= len(items):
                return items[choice - 1][1]
        except (ValueError, KeyboardInterrupt):
            pass
        print("Invalid selection.")

if __name__ == "__main__":
    robots = discover()
    selected = select_robot(robots)
    if selected is not None:
        print(f"Selected robot: {selected}")
    else:
        print("No robot selected.")