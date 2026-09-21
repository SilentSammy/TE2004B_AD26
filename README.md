# TE2004B_AD26

Camera-based pose detection for ArUco markers on a board, with optional UDP
telemetry broadcast so any device on the network can subscribe to the results
without prior configuration. `main.py` is the core of this repository; the
`arduino/` sketches are complementary examples for consuming that telemetry,
not the main focus.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running

```bash
python main.py
```

This opens two windows:
- **Camera**: the raw feed with detected markers outlined and labeled.
- **Board**: a top-down plot of marker positions on the board.

Per-second diagnostics (FPS, timing breakdown, detected marker positions) are
printed to the console. Press `q` or `Esc` in a window to quit.

## Broadcasting telemetry

By default, `main.py` only shows the local windows and does not send
anything over the network. To broadcast marker/board telemetry as JSON over
UDP, pass `--broadcast` with your network's broadcast address:

```bash
python main.py --broadcast 10.42.0.255
```

Any device listening on that UDP port (default `5000`) receives packets like:

```json
{
  "timestamp": 1695123456.789,
  "board_detected": true,
  "markers": [
    {"id": 3, "x": -0.01, "y": 0.01, "angle": 91.0}
  ]
}
```

### Common commands

```bash
# Broadcast at the default rate (10 Hz) on the default port (5000)
python main.py --broadcast 10.42.0.255

# Custom port
python main.py --broadcast 10.42.0.255 --port 5050

# Custom rate, e.g. every frame at ~30 Hz, or slower at 1 Hz
python main.py --broadcast 10.42.0.255 --rate 30
python main.py --broadcast 10.42.0.255 --rate 1
```

### Finding your broadcast address

The broadcast address depends on your network and isn't guessed automatically
on purpose, to keep `main.py` simple and predictable. To find it:

```bash
ip -4 addr show
```

Look for the active interface (e.g. `wlo1`) and its `brd` field:

```
inet 10.42.0.1/24 brd 10.42.0.255 scope global noprefixroute wlo1
```

That `brd` value (`10.42.0.255` here) is what you pass to `--broadcast`.

Common cases:
- **Same machine, no network needed** (testing telemetry reception locally):
  use the broadcast address of whatever network interface is currently active,
  found the same way above.
- **Ubuntu-hosted Wi-Fi hotspot** (e.g. for wireless devices to join): typically
  `10.42.0.255`, but always confirm with `ip -4 addr show` since it can vary.
- **Home router / phone hotspot**: usually `192.168.x.255`, again confirm with
  the command above rather than assuming.

Avoid `255.255.255.255` (the "limited broadcast" address) — it is not
reliably delivered on all networks and can silently drop most packets.

## Example: deploying on a new machine

These steps apply to any Ubuntu machine; the commands below use the lab
desktop as a worked example.

Clone and set up the environment:

```bash
git clone https://github.com/SilentSammy/TE2004B_AD26.git ~/Desktop/TE2004B_AD26
cd ~/Desktop/TE2004B_AD26
sudo apt install python3-venv   # only if `python3 -m venv` fails
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Grant camera and USB-serial access, then start a new terminal session (group
changes only apply to new logins):

```bash
sudo usermod -a -G video,dialout "$USER"
```

If `python main.py` reports `can't open camera by index`, list the available
indices and let the app's built-in fallback (it tries index `1`, then `0`)
find the right one, or check `ls -l /dev/video*` to see what exists.

### Hosting a Wi-Fi hotspot on this machine

Useful when wireless devices (e.g. a Pico W) need to join without a router.
Pick a Wi-Fi interface, an SSID, and a password (8+ characters):

```bash
nmcli device status                 # find the Wi-Fi interface name
nmcli device wifi hotspot ifname wlo1 ssid embedded band bg password 12345678
ip -4 addr show dev wlo1            # confirm the assigned IP and `brd` address
```

For example, the lab desktop's hotspot uses SSID `embedded` / password
`12345678`, and typically assigns itself `10.42.0.1/24` with broadcast
`10.42.0.255` — but always confirm with the command above, since NetworkManager
can pick a different subnet.

### Running

```bash
python main.py --broadcast 10.42.0.255
```

## Repository layout

- `main.py` — camera capture, marker detection, board pose estimation, and
  optional telemetry broadcast. The core of this repo.
- `cam_config.py`, `board_config.py`, `board_est.py`, `plotter2d.py`,
  `vision_setup.py` — supporting modules for camera calibration, board layout,
  pose estimation, and 2D plotting.
- `resources/` — printable ArUco marker images.
- `arduino/` — example sketches and Python runners showing how a
  wirelessly-connected microcontroller (Raspberry Pi Pico W) can receive the
  telemetry broadcast, plus earlier Wi-Fi latency experiments. These are
  complementary examples, not required to use `main.py`.
