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

Choose a vision setup with `--setup` (default: `setup_160cm`):

```bash
python main.py --setup setup_90cm
python main.py --setup setup_160cm --broadcast 192.168.12.255
```

On Linux, `bash run.sh` activates `.venv`, prompts for a setup with its print
width and height in centimeters, and uses the telemetry broadcast address verified by `configure_lab_network.sh`.
The hotspot check runs first, before activating the virtual environment or
showing the setup prompt. If it fails, the launcher stops.
Press Enter to use `DEFAULT_SETUP` from `vision_setup.py`. Supply `--setup`
to skip the prompt:

```bash
bash run.sh
bash run.sh --setup setup_90cm --rate 20
```

Available setups and their board resources:

| Setup | Board resources |
| --- | --- |
| `setup_letter` | `resources/board_letter.png` and `.pdf` |
| `setup_90cm` | `resources/board_90cm.png` and `.pdf` |
| `setup_160cm` | `resources/board_160cm.png` and `.pdf` |

`DEFAULT_SETUP` in `vision_setup.py` selects the default setup object.
Individual board marker images use the same basename, such as
`resources/board_160cm_markers/`.

This opens two windows:
- **Camera**: the raw feed with detected markers outlined and labeled.
- **Board**: a top-down plot of marker positions on the board.

Per-second diagnostics (FPS, detected marker positions) are
printed to the console. Press `q` or `Esc` in a window to quit.

Each `VisionSetup` has a `marker_config_path` pointing to its appearance and
height JSON. This optional field defaults to `None`, which uses default marker
appearance and height without reading a file. All current setups explicitly
point to `marker_config.json` beside `main.py`. To assign a different file, change
`marker_config_path` in its `VisionSetup(...)` definition. Keys in the JSON are
ArUco IDs written as strings:

```json
{
  "1": {"text": "A", "color": [180, 230, 180], "height_m": 0.09},
  "2": {"text": "Dream\nTeam", "height_m": 0.15},
  "3": {"image": "resources/custom_marker.png", "scale": 2.0}
}
```

- `text`: printable ASCII, with `\n` for centered multiline labels.
- `color`: fill color in **RGB** order (red, green, blue), three integers
  from 0 to 255. For example, `[255, 0, 0]` is red. Python overrides and the
  default palette also use RGB; the plotter converts to OpenCV's internal
  BGR order when drawing.
- `height_m`: marker height above the board in meters, including zero for a
  marker lying on the board. Omitted values use the selected setup's height.
- `image`: image path, relative to the JSON file's folder or absolute. A valid
  image takes priority over text, fill color, and underline. PNG transparency,
  including partial transparency, reveals the board underneath.
- `scale`: positive image size multiplier, default `1.0`. The longest axis is
  the marker size times this value; aspect ratio and rotation are preserved.
  A 640x480 image on a 9 cm marker occupies 9x6.75 cm at scale `1.0`, or
  18x13.5 cm at `2.0`, centered on the marker.

Only `main.py` reads this JSON. The plotter receives appearance overrides and
renders them; the estimator receives each marker's selected height. Appearance
changes affect the board plot, while height corrections also affect telemetry.
The camera frame and telemetry still identify markers by their numeric IDs.

Settings and images load once at startup; restart to apply edits. Use `{}` for
all defaults, or override the selected setup's file for one run:

```bash
python main.py --marker-config path/to/marker_config.json
```

Missing, unreadable, incorrectly encoded, or malformed JSON falls back to the
defaults with a console message. Invalid entries or fields are skipped while
valid settings are retained. Missing or corrupt images fall back to text and
color. The standalone `plotter2d.py` demo uses its Python overrides.

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

The lab desktop uses a different arrangement: `create_ap.service` manages
SSID `embedded` on the built-in Wi-Fi adapter `wlp1s0`, using virtual interface
`ap0` at `192.168.12.1/24`. A separate USB Wi-Fi adapter connects to `Tec`.
Its hotspot settings are in `/etc/create_ap.conf`; NetworkManager's saved
`embedded` profile is a client connection, not this hotspot.

To check and restore the lab network, run:

```bash
bash configure_lab_network.sh
```

`run.sh` calls this script automatically before starting vision. Running it
manually first is optional; either route verifies the same network.

The script performs one check/repair pass. When run manually in a terminal,
it pauses with `Press Enter to close...` on success or failure. Use
`--no-pause` for human-readable output without that pause.

Other scripts should use `--json`, which never pauses and returns a single
JSON object on stdout. Progress and command output go to stderr. Exit status
is `0` for success and nonzero for failure. For example, a caller can use:

```bash
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if network_info=$(bash "$SCRIPT_DIR/configure_lab_network.sh" --json); then
  broadcast=$(python3 -c 'import json, sys; print(json.loads(sys.argv[1])["broadcast"])' "$network_info")
  hotspot_ip=$(python3 -c 'import json, sys; print(json.loads(sys.argv[1])["hotspot_ip"])' "$network_info")
else
  printf 'Network setup failed: %s\n' "$network_info" >&2
  exit 1
fi
```

The result contains `success`, `error`, `hotspot_interface`, `hotspot_ip`,
`hotspot_cidr`, `broadcast`, and `hotspot_ssid`.
Unavailable values are `null`. Failures also return JSON with `success: false`
and an error message. Without a terminal on stdin, privileged repairs use
noninteractive sudo and fail promptly if authentication is required.

This standalone script reads the hotspot adapter, SSID and gateway from the
existing `create_ap` configuration. It ensures `create_ap.service` is enabled
and running, and waits for the hotspot on the configured Wi-Fi radio to
advertise the expected SSID and gateway. An unhealthy hotspot gets one restart.
It reports the AP interface and telemetry broadcast address and returns a
nonzero exit status if hotspot setup fails.

Choose the desktop's internet connection normally in Ubuntu's network GUI.
The script does not select or reconnect `Tec`, or require an internet connection;
local vision and telemetry only require the hotspot. Internet sharing to hotspot
clients still follows the uplink settings in `/etc/create_ap.conf`.

A healthy hotspot is left running without restart. Repairs may request your
Ubuntu sudo password. Configure `/etc/create_ap.conf` on the desktop first.

### Running

```bash
python main.py --broadcast 192.168.12.255
```

### Updating the lab desktop

After the desired changes have been committed and pushed to `main`, run:

```bash
cd ~/Desktop/TE2004B_AD26
bash update_lab_repo.sh
```

The script fetches `origin/main`, discards local tracked changes, and removes
untracked files so the checkout matches the published branch. Git-ignored
files and directories, including `.venv`, are preserved.

If the lab checkout predates the update script, bootstrap it once with:

```bash
cd ~/Desktop/TE2004B_AD26
git fetch origin main
git checkout -f -B main origin/main
git clean -fd
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
