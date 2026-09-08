#!/usr/bin/env python3
"""Read-only active hardware evidence for supported clone families."""

from __future__ import annotations

import json
import re
import subprocess


class ProbeError(RuntimeError):
    """Raised when active clone evidence cannot be proven."""


def _required_match(pattern: str, text: str, label: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise ProbeError(f"missing-{label}")
    return match.group(1).strip()


def parse_chip_id(text: str) -> dict[str, object]:
    model = _required_match(r"^Chip type:\s+(.+?)\s+\(revision ", text, "chip-model")
    revision = _required_match(r"\(revision\s+([^)]+)\)", text, "chip-revision")
    mac = _required_match(r"^MAC:\s+([0-9a-fA-F:]{17})\s*$", text, "chip-mac").lower()
    crystal = int(_required_match(r"^Crystal frequency:\s+(\d+)MHz\s*$", text, "crystal"))
    return {
        "socFamily": "ESP32",
        "chipModel": model,
        "chipRevision": revision,
        "chipMac": mac,
        "crystalMHz": crystal,
    }


def parse_flash_id(text: str) -> dict[str, object]:
    manufacturer = _required_match(
        r"^Manufacturer:\s+([0-9a-fA-F]+)\s*$", text, "flash-manufacturer"
    ).lower()
    device = _required_match(
        r"^Device:\s+([0-9a-fA-F]+)\s*$", text, "flash-device"
    ).lower()
    size_mb = int(_required_match(r"^Detected flash size:\s+(\d+)MB\s*$", text, "flash-size"))
    voltage = _required_match(r"^Flash voltage.*:\s+([0-9.]+V)\s*$", text, "flash-voltage")
    return {
        "flashManufacturer": manufacturer,
        "flashDevice": device,
        "flashSize": size_mb * 1024 * 1024,
        "flashVoltage": voltage,
    }


def _efuse_value(data: dict[str, object], name: str) -> object:
    field = data.get(name)
    if not isinstance(field, dict) or field.get("readable") is not True or "value" not in field:
        raise ProbeError(f"missing-efuse-{name.lower()}")
    return field["value"]


def parse_efuse_json(text: str) -> dict[str, object]:
    start = text.find("{")
    if start < 0:
        raise ProbeError("invalid-efuse-json")
    try:
        data = json.loads(text[start:])
    except json.JSONDecodeError as error:
        raise ProbeError("invalid-efuse-json") from error
    if not isinstance(data, dict):
        raise ProbeError("invalid-efuse-json")
    crypt_count = int(_efuse_value(data, "FLASH_CRYPT_CNT"))
    return {
        "flashEncryption": crypt_count.bit_count() % 2 == 1,
        "secureBootV1": bool(_efuse_value(data, "ABS_DONE_0")),
        "secureBootV2": bool(_efuse_value(data, "ABS_DONE_1")),
        "uartDownloadEnabled": not bool(_efuse_value(data, "UART_DOWNLOAD_DIS")),
        "rdDis": int(_efuse_value(data, "RD_DIS")),
        "wrDis": int(_efuse_value(data, "WR_DIS")),
    }


def _run_checked(runner, args: list[str], timeout: float = 20.0) -> str:
    try:
        result = runner(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ProbeError("probe-command-failed") from error
    if result.returncode != 0:
        raise ProbeError("probe-command-failed")
    return str(result.stdout or "")


def _failure(reason: str) -> dict[str, object]:
    return {
        "ok": False,
        "cloneFamily": "",
        "rawReadSupported": False,
        "rawWriteCandidate": False,
        "error": reason,
    }


def run_esp32_probe(port: str, runner=subprocess.run) -> dict[str, object]:
    try:
        chip_text = _run_checked(runner, ["esptool", "-p", port, "chip-id"])
        flash_text = _run_checked(runner, ["esptool", "-p", port, "flash-id"])
        efuse_text = _run_checked(
            runner,
            ["espefuse", "-p", port, "summary", "--format", "json"],
        )
        return {
            "ok": True,
            "cloneFamily": "esp32-classic-spi-flash",
            **parse_chip_id(chip_text),
            **parse_flash_id(flash_text),
            **parse_efuse_json(efuse_text),
            "rawReadSupported": True,
            "rawWriteCandidate": False,
            "toolVersion": "esptool-cli",
            "error": "",
        }
    except ProbeError as error:
        return _failure(str(error))


__all__ = [
    "ProbeError",
    "parse_chip_id",
    "parse_flash_id",
    "parse_efuse_json",
    "run_esp32_probe",
]
