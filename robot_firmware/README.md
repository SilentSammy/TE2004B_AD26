# Zumo hardware server + Pico W brain

The Zumo's built-in RP2040 runs `zumo_hardware/hardware_server.py`. It owns
the hardware and motor timeout. The external Pico W runs your application,
using `pico_w/zumo_client.py` to access hardware over UART. Wi-Fi, navigation
and sensor fusion belong on the Pico W; this link does not relay Wi-Fi packets.
Both devices remain independently programmable over USB.

## Wiring and firmware

The tested wiring is Zumo UART0 GP28 TX → Pico W GP1 RX, Zumo GP29 RX ←
Pico W GP0 TX, and common ground. UART is 3.3 V, 921600 baud, 8N1.
Do not connect 5 V to a UART pin. The existing wiring was verified in both
directions. COM3 is the Zumo and COM8 is the Pico W in the tested setup.

The Zumo's Pololu MicroPython build and `zumo_2040_robot` package are retained.
No UF2 replacement is needed. Install from this repository root:

```text
python -m mpremote connect COM3 fs cp robot_firmware/zumo_hardware/hw_protocol.py :hw_protocol.py + fs cp robot_firmware/zumo_hardware/hardware_server.py :hardware_server.py + fs cp robot_firmware/zumo_hardware/main.py :main.py + reset
python -m mpremote connect COM8 fs cp robot_firmware/zumo_hardware/hw_protocol.py :hw_protocol.py + fs cp robot_firmware/pico_w/zumo_client.py :zumo_client.py + fs cp robot_firmware/pico_w/main.py :main.py + reset
```

`hw_protocol.py` must be the same version on both devices. Close serial monitors
before running mpremote. Connecting to COM3 with mpremote interrupts the hardware
server, which stops the motors; reset that device when finished programming.
Hold button A while booting the Zumo to bypass the server and reach the REPL.
The Pico W's starter `main.py` connects, sends a stop, and exits to the REPL.
It does not start a moving application or replace your choice of Wi-Fi code.

## Application API

Run this on the Pico W (or put your application in its `main.py`):

```python
from zumo_client import Zumo
import hw_protocol as p

car = Zumo()                         # UART0, GP0/GP1, 921600 baud
print(car.info())
sample = car.read_sensors(p.ALL)     # synchronous full sensor snapshot
print(sample['encoders'], sample['gyro_dps'])
car.set_motor_speeds(0, 0)           # signed Pololu PWM units -6000..6000
car.reset_encoders()
car.led(True)                       # yellow LED
car.display('Hello\nfrom Pico W')    # up to six lines, 16 characters each
car.buzzer('L16O5c')                 # background Pololu notes; '' stops sound
car.close()                         # stop motors, stop streaming, release UART
```

Snapshots contain encoder counts, acceleration in g, gyro in degrees/s,
magnetometer in gauss, raw IMU values, five raw line readings, six proximity
counts, battery millivolts, button bitmask (A/B/C = bits 0/1/2), commanded motor
PWM, requested/valid sensor mask, acquisition duration, acquisition-start tick,
sample sequence, and watchdog stop counter. `motor_pwm` reports the commanded
PWM; encoders provide actual movement feedback.

Sensor masks: `CORE=1` (encoders + IMU), `LINE=2`, `PROXIMITY=4`, `BATTERY=8`,
`BUTTONS=16`. `FAST=27` excludes proximity; `ALL=31` includes everything.
Unrequested groups are zero and absent from `valid_mask`. The IMU is configured
at ±2 g / ±2000 degrees/s / ±4 gauss; accelerometer and gyro run at 208 Hz,
magnetometer at 80 Hz. Reading a sensor faster does not create new physical
measurements. Raw line values use the original Pololu driver; calibration can
be performed by the Pico W application. Proximity counts use all six default
brightness levels and remain slower than the other sensors.

For a 100 Hz application use `car.stream(100, p.FAST)` and call `car.poll()`
frequently. The latest decoded snapshot is `car.latest`; local receipt time is
`car.latest_received_us`. `car.stream(50, p.ALL)` delivers the full sensor set.
Use `car.stream(0)` to stop. Keep one client as owner of the UART; execute your
own logic on the snapshots and renew the motor command each control cycle.
`pico_w/example.py` demonstrates this while holding PWM at zero.

Synchronous `read_sensors()` waits for a new snapshot and builds a friendly
dictionary, which costs more time. `read_raw(mask)` returns the 31-field tuple
without floating-point conversion. Streaming is the tested high-rate path.
Snapshots are sequential sensor reads, not simultaneous samples. Timestamp
ticks belong to the Zumo, wrap according to MicroPython's tick clock, and are
not synchronized to the Pico W's clock.

## Motor behavior

Motors start at zero. Nonzero commands expire after 250 ms without another
valid motor command. Sensor reads, pings and streaming do not renew that lease.
Button A stops the motors and rejects nonzero PWM while held. Invalid commands
stop the motors; CRC-invalid packets are discarded and cannot renew the lease.
Server exit/exception also turns the motors off. Applications should stop on
stale sensor/network data as well as use `try/finally` or `with Zumo()`.
This is a MicroPython software timeout; a completely hung interpreter is not
covered by a hardware watchdog in this version.

## Measured hardware results

On the connected Zumo/Pico W at their default 125 MHz clocks, with a zero-speed
motor command every tick and concurrent sensor streaming:

| Profile | Motor updates | Sensor packets / ~4 seconds | Missing frames | CRC errors |
| --- | ---: | ---: | ---: | ---: |
| FAST, target 100 Hz | 99.8 Hz | 401 | 0 | 0 |
| ALL, target 50 Hz | 49.9 Hz | 200 | 0 | 0 |

MicroPython GC introduces occasional jitter: maximum measured control-loop
gaps were about 17.5 ms and 28.7 ms respectively. These are average-rate
measurements, not hard real-time guarantees. The rates were measured without
Wi-Fi/application load; remeasure with your full application running.
The full proximity scan costs roughly 11 ms by itself. The synchronous
dictionary API measured about 98.6 Hz FAST and 47.1 Hz ALL when driven as fast
as possible; choose streaming for predictable average update rates.

The raised-track motor test verified left/right actuation, reverse operation,
encoder changes and automatic timeout stopping. Yellow LED, background buzzer
and text display were also tested. Battery sampling precedes line emission
because GP26 is shared; the corrected readings matched the stock driver at
about 6.6 V on this robot.

Repeat non-moving tests:

```text
python -m mpremote connect COM8 run robot_firmware/pico_w/control_rate_test.py
python -m mpremote connect COM8 run robot_firmware/pico_w/protocol_test.py
python -m mpremote connect COM8 run robot_firmware/pico_w/benchmark.py
```

Only run `pico_w/motor_test.py` with the tracks raised. Its longest powered
phase deliberately waits for the 250 ms timeout.

## Protocol and recovery

Frames use `A5 5A`, version byte, opcode byte, little-endian uint16 sequence,
uint16 payload length, payload, and little-endian CRC32 of version through
payload. Maximum payload is 192 bytes. A snapshot is 64 payload bytes / 76
wire bytes, about 0.825 ms at 921600 baud. RX buffers are bounded; partial
frames expire after a 20 ms idle gap. Response opcodes are request opcode OR
0x80; stream data is 0x90; errors are 0xFF. See `hw_protocol.py` for constants.
Invalid CRC, garbage and truncated-frame recovery were tested on the real UART.

Snapshot payload format is `<IIii9h5H6BHHhhHHH`: acquisition tick/duration,
two encoders, raw acc/gyro/mag, line values, proximity pairs (left/front/right,
left-emitter/right-emitter), battery, buttons, two PWM values, mask, watchdog
count and sample sequence. `car.status()` reports parser errors and watchdog
stops. No automatic retransmission of motor commands is performed.

The original Zumo `main.py` and `remote_control.py` were copied to the ignored
local folder `.firmware_backups/zumo-before-hardware-server/`. To restore the
original startup:

```text
python -m mpremote connect COM3 fs cp .firmware_backups/zumo-before-hardware-server/main.py :main.py + reset
```

The old `remote_control.py` and Pololu examples remain on the Zumo unchanged.
The Pico W filesystem was empty before this installation.

## Wi-Fi control from the laptop

`host_velocity_client.py` now uses a Pico W endpoint that calls this hardware
API directly. The old Arduino UDP relay and Zumo `remote_control.py` are not
part of this command path. Install the optional teleoperation startup on the
Pico W (the Zumo hardware server firmware stays the same):

```text
python -m mpremote connect COM8 fs cp robot_firmware/pico_w/velocity_server.py :velocity_server.py + fs cp robot_firmware/pico_w/velocity_main.py :main.py + reset
```

It joins `embedded` by default. To use another network, create `wifi_config.json`
on the Pico W with `ssid` and `password` keys. The server prints its IP and ports
over USB. Discovery uses UDP 5001; wheel commands/status/acknowledgments use UDP
5002. Join the same reachable LAN on the laptop, then run:

```text
python host_velocity_client.py --check
python host_velocity_client.py
python host_velocity_client.py 192.168.12.45 --check
python host_velocity_client.py --broadcast 192.168.12.255 --max-pwm 1500
```

`--check` only sends status and stop commands. Normal mode uses W/S and A/D,
or the gamepad sticks, with C/right trigger for boost. It verifies the Pico W
protocol and physical Zumo UART connection before enabling controls. It sends
unchanged moving commands every 100 ms, stops on Ctrl+C/error, and exits if
acknowledgments stop for 500 ms. The Pico W and Zumo each enforce a 250 ms
command timeout. Discovery uses the actual local subnet masks rather than
assuming the default internet interface is the robot network; `--broadcast`
can override it.

Commands contain integer `l`/`r` PWM, a random host session ID and an increasing
sequence number. Stale nonzero commands are rejected, and only one active
client owns nonzero control. Any client may send a stop. A host session ID is
for ordering, not authentication; use this service on the trusted robot LAN.
The endpoint does not change the Zumo firmware or forward UDP packets blindly.

The previous Pico W startup is backed up locally at
`.firmware_backups/pico-before-velocity-server/main.py`; restore it with
`mpremote ... fs cp` if returning to a standalone Pico W application.
It is also retained on the Pico W as `main_uart_example.py`.

For keyboard driving with sensor inspection, run `python host_ir_control.py`.
W/S and A/D (or gamepad sticks) drive normally; press **I** to print one IR
snapshot. `--ir-key KEY` changes the hotkey. Downward line readings are shown
left-to-right as raw values, and proximity readings show left/front/right
receiver counts for each emitter (counts, not distances in centimeters).
The snapshot request uses a separate read-only UDP connection in a worker,
so it does not pause the keyboard loop or renew/stop a motor-control lease.
`python host_ir_control.py --read-ir` prints one snapshot and exits without
sending motor commands. Both modes require the updated `velocity_server.py`
on the Pico W. Sensor read failures are printed without ending manual control;
the existing independent motor/command timeouts still apply.

`tools/mpremote_no_reset.py` provides board-aware USB line handling: DTR is
asserted for Pico/Pololu USB CDC and left low for native ESP32 USB. Replace
`python -m mpremote` with `python tools/mpremote_no_reset.py` when using it.
Add `resume` to avoid mpremote's automatic soft reset; entering the REPL still
interrupts a running application, so reset afterward to restart the endpoint.

## Optional marker pose on the Pico W

`pose_client.py` is an independent, non-blocking unicast subscriber. Applications
may use it with or without the velocity endpoint or Zumo hardware client.
Marker ID defaults to **1**. Enable/use it only when the application needs GPS
feedback; receiving a packet does not imply the robot's marker is visible.

```python
from pose_client import PoseSubscriber

position = PoseSubscriber('192.168.12.1', marker_id=1)
# Inside your existing application/control loop:
position.poll()
pose = position.pose
if pose is not None:
    x_m, y_m, heading_deg = pose['x'], pose['y'], pose['angle']
else:
    reason = position.reason  # e.g. marker_not_visible or stale_telemetry
# Call position.close() when shutting down (or use a with block).
```

The module sends `POSE_SUBSCRIBE` once per second to the server's subscription
port (5001 by default) from its ephemeral receiving socket. It never binds the
broadcast port or changes Wi-Fi settings. Connect Wi-Fi before constructing it.
It sends `POSE_UNSUBSCRIBE` on close. `poll()` handles at most four packets per
call, so it can coexist with the motor command loop. The application must call
it regularly; there is no background thread.

`position.pose` returns `None` if the board/marker is absent, the feed is stale,
or the camera frame is too old. Default validity is 500 ms, counting both the
frame age reported by the server and elapsed local time since reception. Remote
network transit time is not measured because the clocks are unsynchronized.
Coordinates/angle use the existing vision feed convention (meters/degrees);
no coordinate transform is applied. The module filters by server IP and
subscription port and ignores older frame sequences within a stream.
`position.status()` distinguishes packet reception from marker visibility.
Some MicroPython socket builds cannot expose the ephemeral local port; status
reports `local_port: null` on those builds, and reception still works normally.

The optional velocity-service integration is **disabled by default**. Install
`pose_client.py`, copy `pose_config.example.json` to the Pico W as
`pose_config.json`, and change `enabled` to `true` when needed:

```text
python tools/mpremote_no_reset.py connect COM8 fs cp robot_firmware/pico_w/pose_client.py :pose_client.py + fs cp robot_firmware/pico_w/pose_config.example.json :pose_config.json + reset
```

The shipped example installs it disabled; an enabled configuration looks like:

```json
{"enabled": true, "server": "192.168.12.1", "marker_id": 1, "port": 5000, "stale_ms": 500}
```

Use the vision server's advertised hotspot/LAN IP. `subscription_port` may
also be set if it differs from `port + 1`. Restart the Pico W after changing
the config. Invalid optional configuration is reported and disables the
subscriber without preventing teleoperation. Missing/stale pose never stops
manual driving automatically; autonomous applications must decide their own
pose-loss policy. The existing command/motor timeouts remain independent.

The host client's `get_status()` includes a `position` object, and `--check`
prints pose state when enabled. A read-only diagnostic can be run with
`python tools/mpremote_no_reset.py connect COM8 resume run robot_firmware/pico_w/pose_check.py`.
It assumes the Pico W is already connected to Wi-Fi and tests server
`192.168.12.1`, marker 1. Reset afterward to restart the velocity endpoint.
