#!/usr/bin/env python3
"""Read-only host tool capability checks for clone backends."""

from __future__ import annotations

import re
import shutil
import subprocess


TOOL_SPECS = {
    "esptool": {
        "versionArgs": ("version",),
        "versionPattern": r"(?i)\besptool\s+v?([0-9][0-9A-Za-z.+_-]*)",
    },
    "espefuse": {
        "versionArgs": None,
        "versionPattern": None,
    },
    "avrdude": {
        "versionArgs": ("--version",),
        "versionPattern": r"(?i)\bavrdude\s+version\s+([0-9][0-9A-Za-z.+_-]*)",
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

    version_args = spec["versionArgs"]
    version_pattern = spec["versionPattern"]

    if version_args is None:
        return {
            "available": True,
            "path": str(path),
            "version": "",
            "versionStatus": "not-queried",
            "reason": "",
        }

    command = [
        str(path),
        *version_args,
    ]

    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {
            "available": True,
            "path": str(path),
            "version": "",
            "versionStatus": "query-failed",
            "reason": f"{name}-version-query-failed",
        }

    if result.returncode != 0:
        return {
            "available": True,
            "path": str(path),
            "version": "",
            "versionStatus": "query-failed",
            "reason": f"{name}-version-query-failed",
        }

    text = (
        f"{result.stdout or ''}\n"
        f"{result.stderr or ''}"
    )

    match = re.search(str(version_pattern), text)

    if not match:
        return {
            "available": True,
            "path": str(path),
            "version": "",
            "versionStatus": "query-failed",
            "reason": f"{name}-version-query-failed",
        }

    return {
        "available": True,
        "path": str(path),
        "version": match.group(1),
        "versionStatus": "reported",
        "reason": "",
    }


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
