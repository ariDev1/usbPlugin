#!/usr/bin/env python3
"""Read-only host tool capability checks for clone backends."""

from __future__ import annotations

import re
import shutil
import subprocess


# Every parser in clone_probe is written against one esptool/espefuse output
# dialect. esptool 4 reports "Crystal is 40MHz" where 5 reports
# "Crystal frequency: 40MHz", so a different major version turns every ESP32
# probe into "missing-crystal" and the board looks unsupported rather than the
# tool looking wrong. Pinning the major version makes preflight say so before
# any hardware is touched. avrdude is unpinned because the only output parsed
# is the -U signature, whose format has been stable across many releases.
TOOL_SPECS = {
    "esptool": {
        "versionArgs": ("version",),
        "versionPattern": r"(?i)\besptool\s+v?([0-9][0-9A-Za-z.+_-]*)",
        "supportedMajor": 5,
    },
    "espefuse": {
        # espefuse has no version subcommand; the banner carries the version.
        "versionArgs": ("--help",),
        "versionPattern": r"(?i)\bespefuse\s+v([0-9][0-9A-Za-z.+_-]*)",
        "supportedMajor": 5,
    },
    "avrdude": {
        "versionArgs": ("--version",),
        "versionPattern": r"(?i)\bavrdude\s+version\s+([0-9][0-9A-Za-z.+_-]*)",
        "supportedMajor": None,
    },
}


FAMILY_REQUIREMENTS = {
    "esp32-classic-spi-flash": (
        "esptool",
        "espefuse",
    ),
    "avr-stk500v1-serial": (
        "avrdude",
    ),
}


def _missing_tool(name: str) -> dict[str, object]:
    return {
        "available": False,
        "path": "",
        "version": "",
        "versionStatus": "unavailable",
        "reason": f"missing-{name}",
    }


def _version_supported(version: str, supported_major: int) -> bool:
    """Report whether a reported version is in the dialect this code parses.

    Compares the leading integer only. A tool that prints something
    unparseable here has already failed the version pattern, so the only
    remaining doubt is a leading component that is not a plain number.
    """

    match = re.match(r"[0-9]+", str(version or ""))
    if not match:
        return False
    return int(match.group(0)) == supported_major


def _reported(
    name: str,
    path: str,
    status: str,
    reason: str,
    version: str = "",
) -> dict[str, object]:
    return {
        "available": True,
        "path": path,
        "version": version,
        "versionStatus": status,
        "reason": reason,
    }


def _inspect_tool(
    name: str,
    spec: dict[str, object],
    *,
    resolver,
    runner,
) -> dict[str, object]:
    path = resolver(name)

    if not path:
        return _missing_tool(name)

    command = [
        str(path),
        *spec["versionArgs"],
    ]

    try:
        result = runner(
            command,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _reported(name, str(path), "query-failed", f"{name}-version-query-failed")

    if result.returncode != 0:
        return _reported(name, str(path), "query-failed", f"{name}-version-query-failed")

    text = (
        f"{result.stdout or ''}\n"
        f"{result.stderr or ''}"
    )

    match = re.search(str(spec["versionPattern"]), text)

    if not match:
        return _reported(name, str(path), "query-failed", f"{name}-version-query-failed")

    version = match.group(1)

    supported_major = spec["supportedMajor"]
    if supported_major is not None and not _version_supported(version, supported_major):
        return _reported(
            name,
            str(path),
            "unsupported",
            f"{name}-version-unsupported",
            version,
        )

    return _reported(name, str(path), "reported", "", version)


def _family_status(
    requirements: tuple[str, ...],
    tools: dict[str, dict[str, object]],
) -> dict[str, object]:
    for name in requirements:
        tool = tools[name]

        if tool["available"] is not True:
            return {
                "ready": False,
                "reason": str(tool["reason"]),
            }

        if tool["reason"]:
            return {
                "ready": False,
                "reason": str(tool["reason"]),
            }

    return {
        "ready": True,
        "reason": "",
    }


def run_preflight(
    *,
    resolver=shutil.which,
    runner=subprocess.run,
) -> dict[str, object]:
    tools = {
        name: _inspect_tool(
            name,
            spec,
            resolver=resolver,
            runner=runner,
        )
        for name, spec in TOOL_SPECS.items()
    }

    families = {
        family: _family_status(
            requirements,
            tools,
        )
        for family, requirements
        in FAMILY_REQUIREMENTS.items()
    }

    return {
        "operation": "preflight",
        "status": "pass",
        "tools": tools,
        "families": families,
    }


__all__ = [
    "FAMILY_REQUIREMENTS",
    "TOOL_SPECS",
    "run_preflight",
]
