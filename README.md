# USB Boards for Omarchy

An Omarchy bar plugin for USB development boards, bootloaders, and serial
adapters. It uses Linux sysfs and the Python standard library, with no Python
packages or background service required.

## Features

- detects serial devices plus DFU, UF2/bootloader, CMSIS-DAP, and JTAG modes
- identifies common Arduino, Espressif, RP-series, STM32, Teensy, micro:bit,
  Adafruit, and Seeed devices
- recognizes CH34x/CH91xx, CP210x, FTDI, and PL2303 serial bridges
- groups multiple serial interfaces belonging to one physical USB device
- shows VID/PID, connection mode, driver, serial number, stable path, locks,
  and permissions
- remembers device names and monitor profiles while devices are disconnected
- includes a reconnecting serial monitor, selectable format and line ending,
  and optional timestamped RX/TX logs

USB-to-serial bridges cannot reveal the board behind them. A CH340 attached to
an ESP32 is therefore labelled `BOARD UNKNOWN (CH340/CH341)`, rather than being
guessed incorrectly. Native USB boards can usually be identified more exactly.

## Install

From a published Git repository:

```bash
omarchy plugin add https://github.com/ariDev1/usbPlugin --enable
omarchy bar put dev.usb-boards --section right
```

For local development, `install.sh` links this checkout into the Omarchy plugin
directory and adds it to the bar:

```bash
./install.sh
```

## Usage

Select a connected device from the bar. The panel can copy its stable path,
assign a friendly name, or open the serial monitor. Press `Ctrl+]` to close the
monitor.

Set global defaults with:

```bash
omarchy bar set dev.usb-boards baudRate 9600
omarchy bar set dev.usb-boards lineEnding crlf
omarchy bar set dev.usb-boards sessionLogging true
```

Line endings are `none`, `lf`, `cr`, or `crlf`. Supported serial formats are
`8N1`, `8N2`, `7E1`, and `7O1`. Per-device controls override these defaults.
Logs are stored under
`${XDG_STATE_HOME:-~/.local/state}/omarchy/usb-boards/sessions/`.

If a port is inaccessible, **Grant access** opens a terminal, explains the
persistent group-membership change, and asks for confirmation before running
`sudo usermod`. Log out and back in once after granting access.

## Supported Hardware

| Family | Detection |
| --- | --- |
| Arduino | Native USB IDs and product names |
| Espressif ESP32-S2/S3/C3 and newer | Native USB JTAG/serial IDs |
| Raspberry Pi Pico and RP-series | Serial and RP2/UF2 bootloader |
| STM32 | Virtual COM and DFU bootloader |
| PJRC Teensy | Serial and HalfKay bootloader |
| BBC micro:bit / Arm mbed | DAPLink and CMSIS-DAP |
| Adafruit / Seeed | Vendor ID and product name |
| Generic development boards | CH34x/CH91xx, CP210x, FTDI, or PL2303 bridge |

Adding an exact board requires a VID/PID entry in `BOARD_IDS` in
`usb_boards.py`. Add a regression case to `IdentifyBoardTests` with it.

## Troubleshooting

Run the scanner directly to separate USB discovery from panel rendering:

```bash
python3 usb_boards.py --pretty
```

If nothing appears there, Linux has not exposed a supported USB device. Try a
known data-capable cable and another USB port. A charging-only cable can power a
board without making it discoverable.

Force Omarchy to rediscover plugin files with:

```bash
omarchy-shell shell rescanPlugins
```

## Development

```bash
python3 -m unittest -v
omarchy plugin validate .
```

Before a release, update `manifest.json`, capture current bar and expanded-panel
screenshots, run both commands above, and test serial and bootloader-only boards.

## License

MIT. See [LICENSE](LICENSE).
