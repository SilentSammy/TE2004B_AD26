"""Open serial with board-appropriate DTR/RTS levels before mpremote connects."""

import sys

import serial
from serial.tools import list_ports
from mpremote import main


_serial_for_url = serial.serial_for_url


def _open_idle(*args, **kwargs):
    should_open = not kwargs.pop('do_not_open', False)
    port = _serial_for_url(*args, do_not_open=True, **kwargs)
    device = str(args[0] if args else kwargs.get('url', '')).upper()
    pico = any(p.device.upper() == device and p.vid in (0x2e8a, 0x1ffb)
               for p in list_ports.comports())
    # Pico USB CDC needs DTR asserted to carry REPL traffic. Native ESP32-C3
    # USB maps these lines to reset/boot, so leave both low on those devices.
    port.dtr = pico
    port.rts = False
    if should_open:
        port.open()
    return port


serial.serial_for_url = _open_idle

if __name__ == "__main__":
    main.main()
