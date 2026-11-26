# TE2004B_AD26

Zumo 2040 robot examples and course resources for sensor-fusion experiments.
Camera tracking and pose telemetry are maintained in the optional
[`aruco_gps`](https://github.com/SilentSammy/aruco_gps) submodule, shared with VSSS.

## Setup

```bash
git clone https://github.com/SilentSammy/TE2004B_AD26.git
cd TE2004B_AD26
bash setup.sh             # Linux; pass --yes to skip confirmation
```

On Windows run `./setup.ps1` in PowerShell, or `./setup.ps1 -Yes` to skip
confirmation. The setup scripts initialize the submodule and install the
vision dependencies in `aruco_gps/.venv`. To initialize it without installing
dependencies, run `git submodule update --init --recursive`.

## Vision service

On Linux, run `bash run.sh` to launch the shared camera, detection and viewer
stack. It prompts for a setup and optional ball detection; Ctrl+C stops it.
The launcher assumes networking is already configured. The lab-specific
`configure_lab_network.sh` is a separate, optional operation; the vision
launcher does not run it or select an adapter.

The service broadcasts legacy telemetry on UDP 5000 by default and accepts
unicast subscriptions on UDP 5001. Pass a directed broadcast address if
needed, for example `bash run.sh --broadcast 192.168.12.255`. Existing
students' telemetry listeners remain compatible. See
[`aruco_gps/README.md`](aruco_gps/README.md) for service configuration, camera
streaming and telemetry details.

One running vision service can serve TE2004 and VSSS at the same time. A client
project does not need to start a second instance or own the camera.

The `arduino/` directory contains robot telemetry and relay sketches;
`zumo2040_bk/` contains the Zumo examples. Printable course marker PDFs remain
under `resources/pdfs/`.

For the Zumo hardware server and Pico W brain/client firmware, see
[`robot_firmware/README.md`](robot_firmware/README.md). The tested binary UART
link supports approximately 100 Hz fast sensors or 50 Hz full sensors while
accepting motor commands, with a motor-command timeout on the Zumo.

Laptop remote control and hardware sensor reads use **BLE**:
`python host_velocity_client.py` for WASD/gamepad, or `python host_ir_control.py`
for the same controls plus the **I** sensor hotkey. `--check` verifies the
stopped-motor path; `host_ir_control.py --read-ir` prints one snapshot. The
default advertised robot is `zumo1`. Wi-Fi is optional for the Pico W's ArUco
position subscription and is not needed for remote control.
