# Agent handoff: Pico W wireless latency investigation

## Objective and constraints

The user sends `0` (LED off) and `1` (LED on) from a laptop to Raspberry Pi Pico W devices, with no Enter key. The user wants visual feedback and measured command-to-ack latency, including per-command output and final statistics on `Ctrl+C`. The long-term design is for **many wireless devices to join or subscribe to a laptop-controlled service without configuring device IPs in advance**. A reasonably consistent response below 20 ms would be acceptable.

The next experiment is an Ubuntu-hosted Wi-Fi hotspot with the Pico in station/client mode. It is intended to test whether the excellent Pico-access-point result can be approached in a topology suitable for multiple Picos. The user does not currently have a dedicated router.

## Repository and code

- Remote: `https://github.com/SilentSammy/TE2004B_AD26.git`; branch: `code_cleanup`. The user plans to commit and push the current work before rebooting into Ubuntu.
- `arduino/udp_unicast/udp_unicast.ino` and `.py`: primary comparable station-mode UDP test. Edit Wi-Fi credentials in the sketch and pass the Ubuntu hotspot's subnet broadcast address to the Python runner.
- `arduino/pico_ap/pico_ap.ino` and `.py`: diagnostic where Pico creates `PicoLatency` (`192.168.4.1`) and laptop joins it. This had the best latency but reverses the intended topology.
- `arduino/udp_broadcast/` and `arduino/tcp_push/`: earlier experiments. `blink/` and `serial/` are basic LED tests.
- `udp_unicast.py` and `pico_ap.py` were updated to read single keys on Windows and POSIX terminals; this Ubuntu path has not yet been exercised on actual Ubuntu hardware. Only these two runners have been ported.

The station-mode UDP protocol: host sends `DISCOVER` to Pico UDP port 4210; Pico replies `HELLO <MAC>` to host UDP port 4211; host records MAC-to-IP mappings and sends a five-byte packet (big-endian `uint32` sequence, then ASCII `0`/`1`) by unicast to registered Picos. Pico writes the built-in LED, prints `ACK <sequence> <command> LED_US=<us> PARSE_US=<us>` over USB serial, then sends the same command and sequence back as a UDP ACK. The host times both paths. `WiFi.noLowPowerMode()` is enabled in the station-mode sketch.

The Pico initially announces to `WiFi.gatewayIP()`, which works when the laptop itself is the hotspot gateway; the host also periodically broadcasts `DISCOVER` until registration. The host runner's default `--broadcast` is **192.168.137.255**, inherited from Windows hotspot. On Ubuntu, supply the actual hotspot subnet broadcast explicitly. Passing the Pico IP to `--broadcast` is a diagnostic unicast discovery and is not the desired final discovery method.

## Measurements so far

| Network/topology | Commands ACKed | Wi-Fi mean | Wi-Fi median | Wi-Fi p95 | Wi-Fi max | Wi-Fi >20 ms | USB mean | USB median | USB p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Windows laptop hotspot, Pico client | 188/188 | 45.01 ms | 21.19 ms | 131.20 ms | 199.76 ms | 95/188 | 44.14 ms | 19.63 ms | 130.34 ms |
| Phone hotspot, Pico and laptop clients | 210/210 | 35.09 ms | 11.09 ms | 149.57 ms | 198.74 ms | 66/210 | 26.89 ms | 6.62 ms | 121.75 ms |
| Pico access point, laptop client | 206/206 | **6.30 ms** | **3.63 ms** | **20.39 ms** | **83.71 ms** | **11/206** | **5.01 ms** | **3.30 ms** | **15.88 ms** |

Other UDP and persistent TCP runs on the Windows hotspot were similarly slow: about 40–45 ms mean and 125–133 ms p95. On the Pico-AP run, LED write time was median 1166 us / p95 1180 us / max 4442 us; UDP parse call was median 2 us / p95 217 us / max 712 us. Only one of 11 Wi-Fi ACKs over 20 ms coincided with a host receive-loop gap over 20 ms. On the phone run, only four of 66 did. These numbers make LED write and Python receive-loop pauses unlikely to account for most long delays. `PARSE_US` measures the duration of a `udp.parsePacket()` call, **not** how long a packet waited before the Pico application saw it.

Wi-Fi and USB ACK timings are end-to-end host measurements, not one-way radio measurements. The sketch prints USB ACK before sending Wi-Fi ACK. Long USB and Wi-Fi times together suggest delay before LED action, but do not uniquely identify the Wi-Fi access point, driver, station-mode stack, or radio conditions. The Pico-AP test changed both the access point and the Pico's Wi-Fi role. It was much faster but still had occasional 80 ms spikes and did not meet a strict always-below-20-ms goal.

## Next agent's immediate task

Help the user run the Ubuntu hotspot test described in [UBUNTU_SETUP.md](UBUNTU_SETUP.md), resolving practical Linux issues if needed. Verify 2.4 GHz, USB serial port and permissions, actual subnet broadcast address, registration, and that 0/1 work without Enter. Compare roughly 200 commands against the table above, especially Wi-Fi/USB p95, maximum, and fraction above 20 ms. If no Pico registers, distinguish a wrong broadcast address from client isolation or firewall by testing discovery to the Pico IP; do not treat a failed discovery run as a latency result.

Avoid assuming that an Ubuntu hotspot will match the Pico-AP performance. If it remains slow, consider station-mode behavior or host/AP implementation and then evaluate another protocol or hardware arrangement. If it is fast, work toward the laptop-controlled, multi-device arrangement without configuring per-device IPs.

## Local verification performed before handoff

The Pico AP sketch ran successfully on the user's hardware (206/206 ACKs). The updated Python POSIX terminal path is new and cannot be run on this Windows checkout. There is no `arduino-cli` available in the Windows environment, so sketches were not locally compiled here. Keep the result interpretation tied to the actual hardware runs above.
