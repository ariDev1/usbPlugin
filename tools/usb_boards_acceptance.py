#!/usr/bin/env python3
"""Deterministic acceptance checks for the USB Boards Omarchy plugin."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable, Mapping, Sequence


PLUGIN_ID = "dev.usb-boards"
EXPECTED_BRANCH = "development"
RUNTIME_FILES = (
    "manifest.json",
    "Panel.qml",
    "ProfileStore.js",
    "usb_boards.py",
    "serial_monitor.py",
    "usb_clone.py",
    "clone_policy.py",
    "clone_probe.py",
)
IDENTITY_FIELDS = (
    "identityKey",
    "identityEvidence",
    "identityPortBound",
    "identityQuality",
    "vendorId",
    "productId",
    "serial",
    "board",
    "confidence",
    "identificationEvidence",
    "identificationScope",
)


class AcceptanceError(RuntimeError):
    """Raised when a deterministic acceptance condition fails."""


def parse_device_json(raw: str, source: str) -> list[dict[str, object]]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise AcceptanceError(f"{source}: invalid JSON") from error
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise AcceptanceError(f"{source}: expected a JSON array of objects")
    return value


def _connected_by_identity(
    devices: Sequence[dict[str, object]], source: str
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for device in devices:
        if device.get("connected") is not True:
            continue
        key = str(device.get("identityKey") or "")
        if not key:
            raise AcceptanceError(f"{source}: connected device has no identityKey")
        if key in result:
            raise AcceptanceError(f"{source}: duplicate connected identityKey {key}")
        result[key] = device
    return result


def compare_connected_devices(
    scanner_devices: Sequence[dict[str, object]],
    runtime_devices: Sequence[dict[str, object]],
) -> None:
    scanner = _connected_by_identity(scanner_devices, "scanner")
    runtime = _connected_by_identity(runtime_devices, "runtime")

    scanner_keys = set(scanner)
    runtime_keys = set(runtime)
    if scanner_keys != runtime_keys:
        missing = sorted(scanner_keys - runtime_keys)
        unexpected = sorted(runtime_keys - scanner_keys)
        details = []
        if missing:
            details.append("missing runtime identities: " + ", ".join(missing))
        if unexpected:
            details.append("unexpected runtime identities: " + ", ".join(unexpected))
        raise AcceptanceError("; ".join(details))

    for key in sorted(scanner):
        for field in IDENTITY_FIELDS:
            if scanner[key].get(field) != runtime[key].get(field):
                raise AcceptanceError(
                    f"identity {key}: field {field} changed from "
                    f"{scanner[key].get(field)!r} to {runtime[key].get(field)!r}"
                )


def _run_checked(
    runner: Callable[..., subprocess.CompletedProcess[str]],
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    result = runner(
        list(args),
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        detail = str(result.stderr or result.stdout or "").strip()
        suffix = f": {detail}" if detail else ""
        raise AcceptanceError(
            f"command failed ({result.returncode}): {' '.join(args)}{suffix}"
        )
    return result


def ensure_development_branch(
    project_dir: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    result = _run_checked(
        runner,
        ["git", "-C", str(project_dir), "rev-parse", "--abbrev-ref", "HEAD"],
    )
    branch = str(result.stdout or "").strip()
    if branch != EXPECTED_BRANCH:
        raise AcceptanceError(
            f"expected branch {EXPECTED_BRANCH}, found {branch or 'unknown'}"
        )


def ensure_active_plugin_checkout(
    project_dir: Path,
    environment: Mapping[str, str] | None = None,
) -> None:
    env = os.environ if environment is None else environment
    config_home = env.get("XDG_CONFIG_HOME") or str(
        Path(env.get("HOME", "~")).expanduser() / ".config"
    )
    plugin_dir = Path(config_home) / "omarchy" / "plugins" / PLUGIN_ID

    if plugin_dir.is_symlink():
        raise AcceptanceError(
            f"active plugin must be a real directory copy: {plugin_dir}"
        )
    if not plugin_dir.is_dir():
        raise AcceptanceError(
            f"active plugin path does not exist: {plugin_dir}"
        )

    for name in RUNTIME_FILES:
        checkout_file = project_dir / name
        active_file = plugin_dir / name

        if not checkout_file.is_file():
            raise AcceptanceError(
                f"checkout runtime file missing: {name}"
            )
        if active_file.is_symlink() or not active_file.is_file():
            raise AcceptanceError(
                f"active plugin runtime file missing: {name}"
            )

        try:
            checkout_bytes = checkout_file.read_bytes()
            active_bytes = active_file.read_bytes()
        except OSError as error:
            raise AcceptanceError(
                f"could not read runtime file for comparison: {name}"
            ) from error

        if active_bytes != checkout_bytes:
            raise AcceptanceError(
                f"active plugin file differs from checkout: {name}"
            )


def _read_runtime_state(
    runner: Callable[..., subprocess.CompletedProcess[str]],
    attempts: int = 40,
    delay_seconds: float = 0.5,
) -> list[dict[str, object]]:
    last_error = ""
    for attempt in range(attempts):
        result = runner(
            ["omarchy-shell", PLUGIN_ID, "state"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        if result.returncode == 0:
            try:
                return parse_device_json(result.stdout, "runtime")
            except AcceptanceError as error:
                last_error = str(error)
        else:
            last_error = str(result.stderr or result.stdout or "").strip()
        if attempt + 1 < attempts:
            time.sleep(delay_seconds)
    raise AcceptanceError(
        f"runtime state did not become ready: {last_error or 'no response'}"
    )


def run_acceptance(
    project_dir: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    environment: Mapping[str, str] | None = None,
) -> None:
    project_dir = project_dir.resolve()
    ensure_development_branch(project_dir, runner)
    ensure_active_plugin_checkout(project_dir, environment)

    _run_checked(runner, ["omarchy", "plugin", "validate", "."], cwd=project_dir)

    scanner_result = _run_checked(
        runner,
        [sys.executable, str(project_dir / "usb_boards.py")],
        cwd=project_dir,
    )
    scanner_devices = parse_device_json(scanner_result.stdout, "scanner")

    _run_checked(runner, ["omarchy", "restart", "shell"], timeout=90.0)
    _run_checked(runner, ["omarchy-shell", "shell", "ping"], timeout=5.0)

    runtime_devices = _read_runtime_state(runner)
    compare_connected_devices(scanner_devices, runtime_devices)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="USB Boards repository checkout",
    )
    args = parser.parse_args(argv)

    try:
        run_acceptance(args.project_dir)
    except AcceptanceError as error:
        print(f"USB Boards acceptance: FAIL: {error}", file=sys.stderr)
        return 1

    print("USB Boards acceptance: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
