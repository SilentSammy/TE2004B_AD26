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
width and height in centimeters, and detects the telemetry broadcast address.
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
| `setup_90cm` | `resources/board_90cm.png` and `.pdf` (when generated) |
| `setup_160cm` | `resources/board_160cm.png` and `.pdf` |

`DEFAULT_SETUP` in `vision_setup.py` selects the default setup object.
Individual board marker images use the same basename, such as
`resources/board_160cm_markers/`.

This opens two windows:
- **Camera**: the raw feed with detected markers outlined and labeled.
- **Board**: a top-down plot of marker positions on the board.

Per-second diagnostics (FPS, timing breakdown, detected marker positions) are
printed to the console. Press `q` or `Esc` in a window to quit.

Each `VisionSetup` has a `marker_config_path` pointing to its appearance and
height JSON. Every setup explicitly declares this required field; all currently
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

For example, the lab desktop's hotspot uses SSID `embedded` / password
`12345678`. Its subnet is **not** guaranteed to be NetworkManager's usual
`10.42.0.0/24` default — this one has been observed assigning `192.168.12.0/24`
instead, likely from a pre-existing connection profile. Always confirm with
the command above rather than assuming either subnet.

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
