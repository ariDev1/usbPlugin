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

from clone_policy import evaluate_source, evaluate_write_pair
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


def _new_transaction_dir(base: Path, prefix: str = "read-") -> Path:
    try:
        path = Path(tempfile.mkdtemp(prefix=prefix, dir=base))
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


def _clone_failure(reason: str) -> dict[str, object]:
    return {
        "operation": "clone",
        "status": "failed",
        "reason": reason,
    }


def _run_target_write(runner, path: str, image_path: Path) -> None:
    try:
        result = runner(
            [
                "esptool",
                "-p",
                path,
                "-b",
                READ_BAUD,
                "--after",
                "no-reset",
                "write-flash",
                "0x0",
                str(image_path),
            ],
            capture_output=True,
            text=True,
            timeout=600.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("target-write-failed") from error

    if result.returncode != 0:
        raise RuntimeError("target-write-failed")


def _run_target_readback(runner, path: str, image_path: Path) -> None:
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
        raise RuntimeError("target-readback-failed") from error

    if result.returncode != 0:
        raise RuntimeError("target-readback-failed")


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


def clone_flash(
    source_identity_key: str,
    target_identity_key: str,
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
        devices = scanner()
        source = resolve_connected_device(source_identity_key, devices)
        target = resolve_connected_device(target_identity_key, devices)

        source_token = read_connection_token(source)
        target_token = read_connection_token(target)

        source_path = device_path(source)
        target_path = device_path(target)

        source_probe = run_esp32_probe(source_path, runner=runner)
        target_probe = run_esp32_probe(target_path, runner=runner)

        decision = evaluate_write_pair(
            source,
            target,
            source_probe,
            target_probe,
        )

        if not decision.allowed:
            result = _clone_failure(decision.reason)
        else:
            base = _secure_clone_root(environ)
            transaction_dir = _new_transaction_dir(base, "clone-")

            source_image = transaction_dir / "source.bin"
            target_image = transaction_dir / "target-readback.bin"

            _prepare_private_image(source_image)
            _prepare_private_image(target_image)

            # Capture one point-in-time SOURCE snapshot.
            _run_source_read(runner, source_path, source_image)

            try:
                source_size = source_image.stat().st_size
            except OSError as error:
                raise RuntimeError("source-read-failed") from error

            if source_size != FLASH_SIZE:
                raise RuntimeError("source-size-mismatch")

            os.chmod(source_image, 0o600)
            source_digest = _sha256(source_image)

            # Re-resolve both physical connections before the first
            # destructive operation.
            current_devices = scanner()
            current_source = resolve_connected_device(
                source_identity_key,
                current_devices,
            )
            current_target = resolve_connected_device(
                target_identity_key,
                current_devices,
            )

            if read_connection_token(current_source) != source_token:
                raise RuntimeError("source-connection-changed")

            if read_connection_token(current_target) != target_token:
                raise RuntimeError("target-connection-changed")

            # This is the first destructive operation.
            # Keep the target in the ROM bootloader after the write.
            _run_target_write(
                runner,
                target_path,
                source_image,
            )

            # Independently read the complete TARGET flash.
            _run_target_readback(
                runner,
                target_path,
                target_image,
            )

            try:
                target_size = target_image.stat().st_size
            except OSError as error:
                raise RuntimeError("target-readback-failed") from error

            if target_size != FLASH_SIZE:
                raise RuntimeError("target-size-mismatch")

            os.chmod(target_image, 0o600)
            target_digest = _sha256(target_image)

            # Verify that the same physical TARGET stayed connected.
            final_devices = scanner()
            final_target = resolve_connected_device(
                target_identity_key,
                final_devices,
            )

            if read_connection_token(final_target) != target_token:
                raise RuntimeError("target-connection-changed")

            if target_digest != source_digest:
                raise RuntimeError("verification-mismatch")

            result = {
                "operation": "clone",
                "status": "pass",
                "sourceIdentityKey": source_identity_key,
                "targetIdentityKey": target_identity_key,
                "cloneFamily": decision.clone_family,
                "imageSize": source_size,
                "sourceSha256": source_digest,
                "targetSha256": target_digest,
            }

    except RuntimeError as error:
        result = _clone_failure(str(error))

    if transaction_dir is not None:
        try:
            shutil.rmtree(transaction_dir)
        except OSError:
            return _clone_failure("cleanup-failed")

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

    clone_command = subparsers.add_parser("clone")
    clone_command.add_argument("--source-identity-key", required=True)
    clone_command.add_argument("--target-identity-key", required=True)
    clone_command.add_argument("--confirm-target-identity", required=True)
    args = parser.parse_args(argv)
    scanner = scanner or _default_scanner

    if args.operation == "probe":
        result = _probe_identity(args.identity_key, scanner=scanner, runner=runner)
    elif args.operation == "read-source":
        result = read_source(
            args.identity_key,
            scanner=scanner,
            runner=runner,
            environ=environ,
        )
    elif args.confirm_target_identity != args.target_identity_key:
        result = _clone_failure("target-confirmation-mismatch")
    else:
        result = clone_flash(
            args.source_identity_key,
            args.target_identity_key,
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
    "clone_flash",
    "resolve_connected_device",
]


if __name__ == "__main__":
    raise SystemExit(main())
