# Ubuntu handoff: Pico W latency test

This page is for running the next test on the Ubuntu partition. The goal is to measure the same UDP command and LED/USB/Wi-Fi acknowledgment paths while the **Ubuntu computer is the hotspot** and the **Pico W is a Wi-Fi client**.

## Before rebooting from Windows

The current branch is `code_cleanup`; the remote is `https://github.com/SilentSammy/TE2004B_AD26.git`. All `arduino/` work and these handoff files are currently local until you commit and push them.

The Wi-Fi client sketches now use `YOUR_WIFI_SSID` and `YOUR_WIFI_PASSWORD` placeholders, so you can commit them without publishing the old hotspot password. In PowerShell from the repository root:

```powershell
git status --short
git add arduino UBUNTU_SETUP.md UBUNTU_AGENT_HANDOFF.md
git commit -m "Add Pico latency tests and Ubuntu handoff"
git push -u origin code_cleanup
```

If you change any files after that commit, commit and push those changes too before switching OS.

## Clone and prepare Ubuntu

Do this **before** turning on the Ubuntu hotspot, while Ubuntu still has internet access. In a terminal:

```bash
git clone https://github.com/SilentSammy/TE2004B_AD26.git
cd TE2004B_AD26
git switch code_cleanup
git pull --ff-only origin code_cleanup
python3 -m venv .venv
source .venv/bin/activate
python -m pip install pyserial
```

If `python3 -m venv` is unavailable, install `python3-venv` with Ubuntu's package manager and retry. The test only requires `pyserial`; the root `requirements.txt` contains dependencies for other parts of the project.

## Create the Ubuntu hotspot

Ubuntu Desktop: open the system menu, expand Wi-Fi, open **All Networks**, then use the menu to **Turn On Wi-Fi Hotspot**. Note its SSID and password. A single Wi-Fi adapter disconnects from its current Wi-Fi network when it starts a hotspot. See [Ubuntu's hotspot instructions](https://help.ubuntu.com/stable/ubuntu-help/net-wireless-adhoc.html.en).

The Pico W needs a **2.4 GHz** network. If the GUI hotspot uses another band or does not work, NetworkManager can explicitly request 2.4 GHz (`band bg`). Find the Wi-Fi interface with `nmcli device status`, then substitute its name, SSID, and a password of your choice:

```bash
nmcli device status
nmcli device wifi hotspot ifname WIFI_INTERFACE ssid PicoLatencyUbuntu band bg password YOUR_HOTSPOT_PASSWORD
```

The hotspot command and `band bg` option are documented by [NetworkManager](https://networkmanager.dev/docs/api/latest/nmcli.html). The password must be at least eight characters. You do not need internet access on the hotspot for this local UDP test.

## Upload and run the comparable test

1. In `arduino/udp_unicast/udp_unicast.ino`, set `WIFI_SSID` and `WIFI_PASSWORD` to the Ubuntu hotspot credentials and upload it to the Pico W. Keep the Pico connected by USB for the second timing path. The sketch should print `READY <Pico IP>` when connected. It already calls `WiFi.noLowPowerMode()`.
2. Find the hotspot interface and its **broadcast** address. For example, `inet 10.42.0.1/24 brd 10.42.0.255` means the broadcast address is `10.42.0.255`:

   ```bash
   nmcli device status
   ip -4 addr show dev WIFI_INTERFACE
   ls /dev/ttyACM*
   ```

3. Replace the example broadcast and serial port below with the actual values. The script's built-in broadcast default is for the old Windows hotspot, so **pass `--broadcast` explicitly**:

   ```bash
   source .venv/bin/activate
   python arduino/udp_unicast/udp_unicast.py --port /dev/ttyACM0 --broadcast 10.42.0.255
   ```

4. Wait for `Registered ...`, then press `0` and `1` without Enter. Aim for roughly 200 commands at a pace similar to the earlier runs. Press `Ctrl+C` for final statistics. Keep the laptop and Pico at about the same separation as before.

If discovery fails, try the Pico's printed IP as a one-device diagnostic: `--broadcast <Pico IP>`. This sends discovery directly to it. If serial access is denied, check that your Ubuntu user has permission for the Pico's `/dev/ttyACM*` device (commonly through the `dialout` group). If the Python process is running inside an IDE or a non-terminal console, use a real terminal for the no-Enter keyboard input.

## What to send to the next agent

Send the final statistics plus a few fast and slow command examples. Include whether the Pico registered via the subnet broadcast or only via its direct IP, the hotspot interface and band, and whether the laptop has another active network connection. The next agent's context is in [UBUNTU_AGENT_HANDOFF.md](UBUNTU_AGENT_HANDOFF.md).
