#!/usr/bin/env python3
"""Validated AVR serial clone evidence for USB Boards."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import subprocess


FULL_FLASH_SIZE = 32768
BOOTLOADER_SIZE = 512
BOOTLOADER_START = 0x7E00
APPLICATION_SIZE = BOOTLOADER_START

VALIDATED_BOOTLOADER_SHA256 = (
    "e36d971b54b3336178813bf16cddf265"
    "8866367874587f7fc6c560fb629fbc74"
)

VALIDATED_REPORTED_SIGNATURE = "1e950f"
AVR_BAUD = 115200


@dataclass(frozen=True)
class AvrImageEvidence:
    full_size: int
    full_sha256: str
    application_sha256: str
    bootloader_sha256: str


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_full_image(path: Path) -> AvrImageEvidence:
    try:
        image = path.read_bytes()
    except OSError as error:
        raise RuntimeError("avr-image-read-failed") from error

    if len(image) != FULL_FLASH_SIZE:
        raise RuntimeError("avr-geometry-mismatch")

    application = image[:APPLICATION_SIZE]
    bootloader = image[BOOTLOADER_START:]

    bootloader_sha256 = _sha256(bootloader)

    if bootloader_sha256 != VALIDATED_BOOTLOADER_SHA256:
        raise RuntimeError("avr-bootloader-mismatch")

    return AvrImageEvidence(
        full_size=len(image),
        full_sha256=_sha256(image),
        application_sha256=_sha256(application),
        bootloader_sha256=bootloader_sha256,
    )


def _probe_failure(reason: str) -> dict[str, object]:
    return {
        "ok": False,
        "cloneFamily": "",
        "protocol": "",
        "baud": AVR_BAUD,
        "bootloaderReportedSignature": "",
        "rawReadSupported": False,
        "rawWriteCandidate": False,
        "error": reason,
    }


def _parse_reported_signature(text: str) -> str:
    match = re.search(
        r"Device signature\s*=\s*"
        r"([0-9a-fA-F]{2})\s+"
        r"([0-9a-fA-F]{2})\s+"
        r"([0-9a-fA-F]{2})",
        text,
    )

    if match:
        return "".join(match.groups()).lower()

    match = re.search(
        r"0x([0-9a-fA-F]{2})\s*,\s*"
        r"0x([0-9a-fA-F]{2})\s*,\s*"
        r"0x([0-9a-fA-F]{2})",
        text,
    )

    if match:
        return "".join(match.groups()).lower()

    raise RuntimeError("avr-signature-missing")



@dataclass(frozen=True)
class AvrCloneVerificationEvidence:
    application_sha256: str
    bootloader_sha256: str


def verify_clone_evidence(
    source: AvrImageEvidence,
    target: AvrImageEvidence,
) -> AvrCloneVerificationEvidence:
    if (
        source.bootloader_sha256
        != VALIDATED_BOOTLOADER_SHA256
        or target.bootloader_sha256
        != VALIDATED_BOOTLOADER_SHA256
    ):
        raise RuntimeError("avr-bootloader-mismatch")

    if source.application_sha256 != target.application_sha256:
        raise RuntimeError(
            "avr-application-verification-mismatch"
        )

    return AvrCloneVerificationEvidence(
        application_sha256=source.application_sha256,
        bootloader_sha256=target.bootloader_sha256,
    )

def run_avr_probe(
    port: str,
    *,
    runner=subprocess.run,
) -> dict[str, object]:
    command = [
        "avrdude",
        "-v",
        "-n",
        "-p",
        "m328p",
        "-c",
        "arduino",
        "-P",
        port,
        "-b",
        str(AVR_BAUD),
        "-U",
        "signature:r:-:h",
    ]

    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            timeout=20.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _probe_failure("avr-probe-command-failed")

    if result.returncode != 0:
        return _probe_failure("avr-probe-command-failed")

    text = f"{result.stdout or ''}\n{result.stderr or ''}"

    try:
        signature = _parse_reported_signature(text)
    except RuntimeError as error:
        return _probe_failure(str(error))

    if signature != VALIDATED_REPORTED_SIGNATURE:
        return _probe_failure("avr-signature-mismatch")

    return {
        "ok": True,
        "cloneFamily": "avr-stk500v1-serial",
        "protocol": "stk500v1",
        "baud": AVR_BAUD,
        "bootloaderReportedSignature": signature,
        "rawReadSupported": True,
        "rawWriteCandidate": True,
        "error": "",
    }


def read_avr_flash(
    port: str,
    output_path: Path,
    *,
    runner=subprocess.run,
) -> AvrImageEvidence:
    try:
        output_path.unlink(missing_ok=True)
    except OSError as error:
        raise RuntimeError("avr-flash-read-failed") from error

    command = [
        "avrdude",
        "-v",
        "-n",
        "-A",
        "-p",
        "m328p",
        "-c",
        "arduino",
        "-P",
        port,
        "-b",
        str(AVR_BAUD),
        "-U",
        f"flash:r:{output_path}:r",
    ]

    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            timeout=120.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("avr-flash-read-failed") from error

    if result.returncode != 0:
        raise RuntimeError("avr-flash-read-failed")

    return validate_full_image(output_path)


def write_application(
    port: str,
    source_path: Path,
    application_path: Path,
    *,
    runner=subprocess.run,
) -> AvrImageEvidence:
    evidence = validate_full_image(source_path)

    try:
        image = source_path.read_bytes()
        application = image[:APPLICATION_SIZE]

        application_path.unlink(missing_ok=True)
        application_path.write_bytes(application)
    except OSError as error:
        raise RuntimeError("avr-application-write-failed") from error

    if len(application) != APPLICATION_SIZE:
        raise RuntimeError("avr-geometry-mismatch")

    command = [
        "avrdude",
        "-v",
        "-D",
        "-A",
        "-p",
        "m328p",
        "-c",
        "arduino",
        "-P",
        port,
        "-b",
        str(AVR_BAUD),
        "-U",
        f"flash:w:{application_path}:r",
    ]

    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            timeout=120.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("avr-application-write-failed") from error

    if result.returncode != 0:
        raise RuntimeError("avr-application-write-failed")

    return evidence


__all__ = [
    "APPLICATION_SIZE",
    "AVR_BAUD",
    "AvrImageEvidence",
    "BOOTLOADER_SIZE",
    "BOOTLOADER_START",
    "FULL_FLASH_SIZE",
    "VALIDATED_BOOTLOADER_SHA256",
    "VALIDATED_REPORTED_SIGNATURE",
    "read_avr_flash",
    "run_avr_probe",
    "validate_full_image",
    "write_application",
]
