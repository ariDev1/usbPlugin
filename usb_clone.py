#!/usr/bin/env python3
"""Read-only raw flash transaction backend for USB Boards."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from clone_policy import evaluate_source
from clone_probe import run_esp32_probe


FLASH_SIZE = 4 * 1024 * 1024
FLASH_SIZE_HEX = "0x400000"
READ_BAUD = "460800"


@dataclass(frozen=True)
class ConnectionToken:
    sys_path: str
    devnum: str


def resolve_connected_device(
    identity_key: str,
    devices: list[dict[str, object]],
) -> dict[str, object]:
    matches = [
        device
        for device in devices
        if device.get("connected") is True
        and str(device.get("identityKey") or "") == identity_key
    ]
    if not matches:
        raise RuntimeError("identity-not-connected")
    if len(matches) != 1:
        raise RuntimeError("duplicate-identity")
    return matches[0]


def device_path(device: dict[str, object]) -> str:
    stable = str(device.get("stablePath") or "")
    port = str(device.get("port") or "")
    path = stable or port
    if not path:
        raise RuntimeError("missing-connection-path")
    return path


def read_connection_token(device: dict[str, object]) -> ConnectionToken:
    sys_path = str(device.get("sysPath") or "")
    if not sys_path:
        raise RuntimeError("missing-sys-path")
    try:
        devnum = (Path(sys_path) / "devnum").read_text(errors="strict").strip()
    except (OSError, UnicodeError) as error:
        raise RuntimeError("missing-devnum") from error
    if not devnum:
        raise RuntimeError("missing-devnum")
    return ConnectionToken(sys_path=sys_path, devnum=devnum)


def _default_scanner() -> list[dict[str, object]]:
    from usb_boards import scan

    return scan()


def _failure(reason: str) -> dict[str, object]:
    return {
        "operation": "read-source",
        "status": "failed",
        "reason": reason,
    }


def _secure_clone_root(environ: dict[str, str]) -> Path:
    runtime = str(environ.get("XDG_RUNTIME_DIR") or "")
    if not runtime:
        raise RuntimeError("runtime-dir-unavailable")
    base = Path(runtime) / "omarchy" / "usb-boards" / "clone"
    try:
        base.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(base, 0o700)
    except OSError as error:
        raise RuntimeError("runtime-dir-unavailable") from error
    return base


def _new_transaction_dir(base: Path) -> Path:
    try:
        path = Path(tempfile.mkdtemp(prefix="read-", dir=base))
        os.chmod(path, 0o700)
        return path
    except OSError as error:
        raise RuntimeError("runtime-dir-unavailable") from error


def _prepare_private_image(path: Path) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    os.close(fd)
    os.chmod(path, 0o600)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run_source_read(runner, path: str, image_path: Path) -> None:
    try:
        result = runner(
            [
                "esptool",
                "-p",
                path,
                "-b",
                READ_BAUD,
                "read-flash",
                "0",
                FLASH_SIZE_HEX,
                str(image_path),
            ],
            capture_output=True,
            text=True,
            timeout=600.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("source-read-failed") from error
    if result.returncode != 0:
        raise RuntimeError("source-read-failed")


def read_source(
    identity_key: str,
    *,
    scanner=None,
    runner=subprocess.run,
    environ=None,
) -> dict[str, object]:
    scanner = scanner or _default_scanner
    environ = os.environ if environ is None else environ
    transaction_dir: Path | None = None
    result: dict[str, object]
    try:
        source = resolve_connected_device(identity_key, scanner())
        initial_token = read_connection_token(source)
        path = device_path(source)

        probe = run_esp32_probe(path, runner=runner)
        decision = evaluate_source(source, probe)
        if not decision.allowed:
            result = _failure(decision.reason)
        else:
            base = _secure_clone_root(environ)
            transaction_dir = _new_transaction_dir(base)
            image_path = transaction_dir / "source.bin"
            _prepare_private_image(image_path)

            _run_source_read(runner, path, image_path)
            try:
                size = image_path.stat().st_size
            except OSError as error:
                raise RuntimeError("source-read-failed") from error
            if size != FLASH_SIZE:
                raise RuntimeError("source-size-mismatch")
            os.chmod(image_path, 0o600)
            digest = _sha256(image_path)

            try:
                current = resolve_connected_device(identity_key, scanner())
            except RuntimeError as error:
                if str(error) == "identity-not-connected":
                    raise RuntimeError("source-disconnected") from error
                raise
            final_token = read_connection_token(current)
            if final_token != initial_token:
                raise RuntimeError("connection-changed")

            result = {
                "operation": "read-source",
                "status": "pass",
                "identityKey": identity_key,
                "cloneFamily": decision.clone_family,
                "imageSize": size,
                "sha256": digest,
            }
    except RuntimeError as error:
        result = _failure(str(error))

    if transaction_dir is not None:
        try:
            shutil.rmtree(transaction_dir)
        except OSError:
            return _failure("cleanup-failed")
    return result


def _probe_identity(identity_key: str, *, scanner, runner) -> dict[str, object]:
    try:
        device = resolve_connected_device(identity_key, scanner())
        path = device_path(device)
    except RuntimeError as error:
        return {
            "operation": "probe",
            "status": "failed",
            "reason": str(error),
        }
    probe = run_esp32_probe(path, runner=runner)
    if probe.get("ok") is not True:
        return {
            "operation": "probe",
            "status": "failed",
            "reason": str(probe.get("error") or "probe-failed"),
        }
    return {
        "operation": "probe",
        "status": "pass",
        "identityKey": identity_key,
        "probe": probe,
    }


def main(
    argv=None,
    *,
    scanner=None,
    runner=subprocess.run,
    environ=None,
    printer=print,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    for name in ("probe", "read-source"):
        command = subparsers.add_parser(name)
        command.add_argument("--identity-key", required=True)
    args = parser.parse_args(argv)
    scanner = scanner or _default_scanner

    if args.operation == "probe":
        result = _probe_identity(args.identity_key, scanner=scanner, runner=runner)
    else:
        result = read_source(
            args.identity_key,
            scanner=scanner,
            runner=runner,
            environ=environ,
        )
    printer(json.dumps(result, sort_keys=True))
    return 0 if result.get("status") == "pass" else 1


__all__ = [
    "ConnectionToken",
    "main",
    "device_path",
    "read_connection_token",
    "read_source",
    "resolve_connected_device",
]


if __name__ == "__main__":
    raise SystemExit(main())
