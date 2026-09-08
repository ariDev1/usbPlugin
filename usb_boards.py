#!/usr/bin/env python3
"""Report connected USB development boards and serial adapters as JSON."""

from __future__ import annotations

import argparse
import grp
import json
import os
from pathlib import Path
import re
import subprocess


SYS_TTY = Path("/sys/class/tty")
SYS_USB = Path("/sys/bus/usb/devices")
DEV_SERIAL_BY_ID = Path("/dev/serial/by-id")
LOCK_DIRS = (Path("/run/lock"), Path("/var/lock"))

# A non-empty USB serial string is evidence, but it is not always unique.
# The classic CP2102 factory default is "0001", so it must not be used as a
# portable profile identity without stronger evidence.
KNOWN_NON_UNIQUE_USB_SERIALS = {
    ("10c4", "ea60", "0001"),
}

# A bridge identifies the USB-to-serial chip, not the board behind it.
BRIDGES = {
    ("0403", "6001"): "FTDI FT232",
    ("0403", "6010"): "FTDI FT2232",
    ("0403", "6011"): "FTDI FT4232",
    ("0403", "6014"): "FTDI FT232H",
    ("0403", "6015"): "FTDI FT-X",
    ("067b", "2303"): "Prolific PL2303",
    ("10c4", "ea60"): "CP210x",
    ("10c4", "ea70"): "CP2105",
    ("10c4", "ea71"): "CP2108",
    ("1a86", "5523"): "CH341",
    ("1a86", "7523"): "CH340/CH341",
    ("1a86", "55d3"): "CH343",
    ("1a86", "55d4"): "CH9102/CH343",
    ("1a86", "55d5"): "CH9102",
}

# Entries here are safe to show without a TTY because the VID/PID identifies a
# development-board function rather than an arbitrary USB peripheral.
BOARD_IDS = {
    ("0483", "5740"): ("STM32 Virtual COM Port", "serial"),
    ("0483", "df11"): ("STM32 DFU Bootloader", "dfu"),
    ("0d28", "0204"): ("Arm DAPLink / micro:bit", "debug"),
    ("16c0", "0478"): ("Teensy HalfKay Bootloader", "bootloader"),
    ("16c0", "0483"): ("Teensy", "serial"),
    ("2341", "003d"): ("Arduino Due Programming Port", "serial"),
    ("2341", "003e"): ("Arduino Due Native Port", "serial"),
    ("2341", "0042"): ("Arduino Mega 2560", "serial"),
    ("2341", "0043"): ("Arduino Uno", "serial"),
    ("2341", "0058"): ("Arduino Nano Every", "serial"),
    ("2341", "0070"): ("Arduino Nano ESP32", "serial"),
    ("2e8a", "0003"): ("Raspberry Pi RP2 Bootloader", "bootloader"),
    ("2e8a", "0005"): ("Raspberry Pi Pico", "serial"),
    ("2e8a", "000a"): ("Raspberry Pi Pico SDK", "serial"),
    ("303a", "1001"): ("Espressif USB JTAG/Serial", "debug"),
}

BOARD_VENDORS = {
    "0d28": "Arm mbed development board",
    "16c0": "PJRC Teensy",
    "2341": "Arduino",
    "239a": "Adafruit development board",
    "2886": "Seeed Studio development board",
    "2a03": "Arduino",
    "2e8a": "Raspberry Pi RP-series board",
    "303a": "Espressif development board",
}


def read_text(path: Path) -> str:
    try:
        return path.read_text(errors="replace").strip()
    except (OSError, UnicodeError):
        return ""


def usb_parent(path: Path) -> Path | None:
    current = path.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "idVendor").is_file() and (candidate / "idProduct").is_file():
            return candidate
    return None


def udev_properties(port: str) -> dict[str, str]:
    try:
        result = subprocess.run(
            ["udevadm", "info", "--query=property", f"--name={port}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}

    properties: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            properties[key] = value
    return properties


def clean_name(value: str) -> str:
    return re.sub(r"[_\s]+", " ", value).strip()


def infer_mode(usb_product: str, has_serial: bool) -> str:
    description = usb_product.lower()
    if "dfu" in description:
        return "dfu"
    if any(word in description for word in ("bootloader", "boot", "uf2")):
        return "bootloader"
    if any(word in description for word in ("jtag", "cmsis-dap", "daplink", "debug")):
        return "debug"
    return "serial" if has_serial else "usb"


def identify_board_evidence(
    vendor: str,
    product: str,
    manufacturer: str,
    usb_product: str,
) -> tuple[str, str, str]:
    """Return board label, confidence, and the evidence used for identification."""

    description = f"{manufacturer} {usb_product}".lower()
    exact = BOARD_IDS.get((vendor, product))
    if exact:
        return exact[0], "exact", "vid-pid"

    names = (
        ("nano esp32", "Arduino Nano ESP32"),
        ("nano 33 iot", "Arduino Nano 33 IoT"),
        ("nano 33 ble", "Arduino Nano 33 BLE"),
        ("raspberry pi pico", "Raspberry Pi Pico"),
        ("micro:bit", "BBC micro:bit"),
        ("teensy", "PJRC Teensy"),
    )
    for marker, name in names:
        if marker in description:
            return name, "probable", "descriptor"

    if "arduino nano" in description:
        return "Arduino Nano", "probable", "descriptor"
    if vendor in BOARD_VENDORS:
        board = clean_name(usb_product)
        if board:
            return board, "probable", "descriptor"
        return BOARD_VENDORS[vendor], "probable", "vendor"

    bridge = BRIDGES.get((vendor, product), "")
    if bridge:
        return f"Serial development board ({bridge})", "bridge-only", "bridge"
    return clean_name(usb_product) or "USB serial device", "unknown", "unknown"


def identify_board(
    vendor: str,
    product: str,
    manufacturer: str,
    usb_product: str,
) -> tuple[str, str]:
    board, confidence, _evidence = identify_board_evidence(
        vendor, product, manufacturer, usb_product
    )
    return board, confidence


def is_board_candidate(vendor: str, product: str, manufacturer: str, usb_product: str) -> bool:
    description = f"{manufacturer} {usb_product}".lower()
    return (
        (vendor, product) in BOARD_IDS
        or vendor in BOARD_VENDORS
        or any(word in description for word in ("arduino", "esp32", "espressif", "micro:bit", "teensy"))
    )


def stable_paths(directory: Path = DEV_SERIAL_BY_ID) -> dict[str, str]:
    paths: dict[str, str] = {}
    if not directory.is_dir():
        return paths
    for link in directory.iterdir():
        try:
            paths[str(link.resolve())] = str(link)
        except OSError:
            continue
    return paths


def driver_name(path: Path) -> str:
    resolved = path.resolve()
    for candidate in (resolved, *resolved.parents):
        driver = candidate / "driver"
        if driver.is_symlink():
            try:
                return driver.resolve().name
            except OSError:
                pass
    return ""


def device_access(port: str) -> dict[str, object]:
    try:
        stat = os.stat(port)
        permissions = oct(stat.st_mode & 0o777)
        try:
            group = grp.getgrgid(stat.st_gid).gr_name
        except KeyError:
            group = str(stat.st_gid)
    except OSError:
        permissions = ""
        group = ""

    return {
        "readable": os.access(port, os.R_OK),
        "writable": os.access(port, os.W_OK),
        "permissions": permissions,
        "group": group,
    }


def lock_info(port: str, lock_dirs=LOCK_DIRS) -> dict[str, object]:
    """Report a conventional UUCP serial lock without treating it as proof."""
    name = Path(port).name
    for directory in lock_dirs:
        path = Path(directory) / f"LCK..{name}"
        if not path.exists():
            continue
        try:
            pid = int(path.read_text(errors="replace").split()[0])
        except (OSError, ValueError, IndexError):
            pid = 0
        return {"locked": True, "lockPath": str(path), "lockPid": pid}
    return {"locked": False, "lockPath": "", "lockPid": 0}


def usb_details(usb: Path, properties: dict[str, str] | None = None) -> dict[str, str]:
    properties = properties or {}
    return {
        "vendor": read_text(usb / "idVendor").lower(),
        "product": read_text(usb / "idProduct").lower(),
        "manufacturer": clean_name(
            read_text(usb / "manufacturer") or properties.get("ID_VENDOR_FROM_DATABASE", "")
        ),
        "usb_product": clean_name(
            read_text(usb / "product") or properties.get("ID_MODEL_FROM_DATABASE", "")
        ),
        "serial": read_text(usb / "serial") or properties.get("ID_SERIAL_SHORT", ""),
    }


def serial_identity_quality(vendor: str, product: str, serial: str) -> str:
    """Classify whether a reported USB serial is safe for portable profile matching."""

    if not serial:
        return "missing"
    if (vendor, product, serial) in KNOWN_NON_UNIQUE_USB_SERIALS:
        return "known-default"
    return "reported"


def device_identity(
    vendor: str,
    product: str,
    serial: str,
    topology: str,
) -> tuple[str, str, bool]:
    """Return a profile identity without treating a connection path as device proof."""

    if serial_identity_quality(vendor, product, serial) == "reported":
        return f"usb-serial:{vendor}:{product}:{serial}", "usb-serial", False
    return f"usb-topology:{vendor}:{product}:{topology}", "usb-topology", True


def base_device(usb: Path, details: dict[str, str], has_serial: bool) -> dict[str, object]:
    vendor = details["vendor"]
    product = details["product"]
    board, confidence, identification_evidence = identify_board_evidence(
        vendor, product, details["manufacturer"], details["usb_product"]
    )
    known_mode = BOARD_IDS.get((vendor, product), ("", ""))[1]
    mode = known_mode or infer_mode(details["usb_product"], has_serial)
    serial = details["serial"]
    identity_key, identity_evidence, identity_port_bound = device_identity(
        vendor, product, serial, usb.name
    )
    return {
        "id": serial or f"{vendor}:{product}:{usb.name}",
        "identityKey": identity_key,
        "identityEvidence": identity_evidence,
        "identityPortBound": identity_port_bound,
        "board": board,
        "confidence": confidence,
        "identificationEvidence": identification_evidence,
        "connected": True,
        "serialAvailable": has_serial,
        "mode": mode,
        "port": "",
        "ports": [],
        "stablePath": "",
        "vendorId": vendor,
        "productId": product,
        "manufacturer": details["manufacturer"],
        "usbProduct": details["usb_product"],
        "serial": serial,
        "bridge": BRIDGES.get((vendor, product), "Native USB" if vendor in BOARD_VENDORS else ""),
        "driver": driver_name(usb),
        "sysPath": str(usb),
        "locked": False,
        "lockPath": "",
        "lockPid": 0,
        "readable": False,
        "writable": False,
        "permissions": "",
        "group": "",
    }


def scan(
    sys_tty: Path = SYS_TTY,
    sys_usb: Path = SYS_USB,
    dev_root: Path = Path("/dev"),
    serial_by_id: Path = DEV_SERIAL_BY_ID,
    properties_reader=udev_properties,
) -> list[dict[str, object]]:
    devices: dict[str, dict[str, object]] = {}
    by_id = stable_paths(serial_by_id)

    if sys_tty.is_dir():
        for tty in sorted(sys_tty.iterdir(), key=lambda item: item.name):
            port_path = dev_root / tty.name
            port = str(port_path)
            if not port_path.exists():
                continue
            usb = usb_parent(tty)
            if usb is None:
                continue

            properties = properties_reader(port)
            details = usb_details(usb, properties)
            key = str(usb.resolve())
            device = devices.setdefault(key, base_device(usb, details, True))
            ports = device["ports"]
            assert isinstance(ports, list)
            ports.append(port)
            if not device["port"]:
                device.update(
                    {
                        "port": port,
                        "stablePath": by_id.get(str(port_path.resolve()), ""),
                        "driver": driver_name(tty),
                        **lock_info(port),
                        **device_access(port),
                    }
                )

    if sys_usb.is_dir():
        for entry in sorted(sys_usb.iterdir(), key=lambda item: item.name):
            usb = entry.resolve()
            if not (usb / "idVendor").is_file() or not (usb / "idProduct").is_file():
                continue
            key = str(usb)
            if key in devices:
                continue
            details = usb_details(usb)
            if not is_board_candidate(
                details["vendor"], details["product"], details["manufacturer"], details["usb_product"]
            ):
                continue
            devices[key] = base_device(usb, details, False)

    return sorted(
        devices.values(),
        key=lambda device: (not bool(device["serialAvailable"]), str(device["board"]).lower()),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pretty", action="store_true", help="indent the JSON output")
    args = parser.parse_args()
    print(json.dumps(scan(), indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
