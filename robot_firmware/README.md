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
