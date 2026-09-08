import hashlib
import json
import os
from pathlib import Path
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from usb_clone import (
    ConnectionToken,
    main,
    device_path,
    read_connection_token,
    read_source,
    resolve_connected_device,
)

from test_clone_probe import CHIP_ID, EFUSES, FLASH_ID


IDENTITY = "usb-topology:1a86:7523:3-1.3"


def source_device(sys_path, *, dev_path="/dev/ttyUSB1"):
    return {
        "connected": True,
        "identityKey": IDENTITY,
        "serialAvailable": True,
        "readable": True,
        "writable": True,
        "locked": False,
        "stablePath": "",
        "port": dev_path,
        "sysPath": str(sys_path),
    }


class IdentityResolutionTests(unittest.TestCase):
    def test_resolves_exact_current_identity(self):
        devices = [
            {"connected": True, "identityKey": "source"},
            {"connected": True, "identityKey": "target"},
        ]
        self.assertEqual(resolve_connected_device("source", devices)["identityKey"], "source")

    def test_duplicate_identity_fails_closed(self):
        devices = [
            {"connected": True, "identityKey": "source"},
            {"connected": True, "identityKey": "source"},
        ]
        with self.assertRaisesRegex(RuntimeError, "duplicate-identity"):
            resolve_connected_device("source", devices)

    def test_missing_identity_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "identity-not-connected"):
            resolve_connected_device("source", [])

    def test_stable_path_is_communication_preference_only(self):
        device = {"identityKey": "identity", "stablePath": "/dev/serial/by-id/x", "port": "/dev/ttyUSB1"}
        self.assertEqual(device_path(device), "/dev/serial/by-id/x")
        self.assertEqual(device["identityKey"], "identity")


class ConnectionTokenTests(unittest.TestCase):
    def test_token_uses_sys_path_and_devnum(self):
        with TemporaryDirectory() as directory:
            usb = Path(directory) / "3-1.3"
            usb.mkdir()
            (usb / "devnum").write_text("7\n")
            token = read_connection_token({"sysPath": str(usb)})
            self.assertEqual(token, ConnectionToken(str(usb), "7"))

    def test_missing_devnum_fails_closed(self):
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "missing-devnum"):
                read_connection_token({"sysPath": directory})


class FakeRunner:
    def __init__(self, *, image_byte=b"\x00", fail_read=False):
        self.calls = []
        self.image_byte = image_byte
        self.fail_read = fail_read

    def __call__(self, args, **kwargs):
        command = list(args)
        self.calls.append(command)
        if command[-1] == "chip-id":
            return CompletedProcess(command, 0, CHIP_ID, "")
        if command[-1] == "flash-id":
            return CompletedProcess(command, 0, FLASH_ID, "")
        if command[-3:] == ["summary", "--format", "json"]:
            return CompletedProcess(command, 0, EFUSES, "")
        if "read-flash" in command:
            if self.fail_read:
                return CompletedProcess(command, 1, "", "read failed")
            output = Path(command[-1])
            with output.open("wb") as stream:
                block = self.image_byte * 4096
                for _ in range(1024):
                    stream.write(block)
            return CompletedProcess(command, 0, "read ok", "")
        raise AssertionError(command)


class SourceReadTests(unittest.TestCase):
    def make_scanner(self, usb_path, *, change_devnum=False):
        calls = {"count": 0}

        def scanner():
            calls["count"] += 1
            if change_devnum and calls["count"] == 2:
                (usb_path / "devnum").write_text("8\n")
            return [source_device(usb_path)]

        return scanner

    def test_complete_source_read_hashes_and_cleans_private_image(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            runtime.mkdir()
            usb = root / "usb"
            usb.mkdir()
            (usb / "devnum").write_text("7\n")
            runner = FakeRunner(image_byte=b"\x00")

            result = read_source(
                IDENTITY,
                scanner=self.make_scanner(usb),
                runner=runner,
                environ={"XDG_RUNTIME_DIR": str(runtime)},
            )

            expected = hashlib.sha256(b"\x00" * 4194304).hexdigest()
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["imageSize"], 4194304)
            self.assertEqual(result["sha256"], expected)
            commands = " ".join(" ".join(call) for call in runner.calls)
            self.assertIn("read-flash 0 0x400000", commands)
            clone_root = runtime / "omarchy" / "usb-boards" / "clone"
            self.assertEqual(list(clone_root.rglob("*.bin")), [])
            self.assertEqual(os.stat(clone_root).st_mode & 0o777, 0o700)

    def test_missing_runtime_dir_fails_closed(self):
        with TemporaryDirectory() as directory:
            usb = Path(directory) / "usb"
            usb.mkdir()
            (usb / "devnum").write_text("7\n")
            result = read_source(
                IDENTITY,
                scanner=self.make_scanner(usb),
                runner=FakeRunner(),
                environ={},
            )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["reason"], "runtime-dir-unavailable")

    def test_read_failure_returns_failure_and_leaves_no_image(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            runtime.mkdir()
            usb = root / "usb"
            usb.mkdir()
            (usb / "devnum").write_text("7\n")
            result = read_source(
                IDENTITY,
                scanner=self.make_scanner(usb),
                runner=FakeRunner(fail_read=True),
                environ={"XDG_RUNTIME_DIR": str(runtime)},
            )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["reason"], "source-read-failed")
            self.assertEqual(list((runtime / "omarchy" / "usb-boards" / "clone").rglob("*.bin")), [])

    def test_connection_change_after_read_aborts_result(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            runtime.mkdir()
            usb = root / "usb"
            usb.mkdir()
            (usb / "devnum").write_text("7\n")
            result = read_source(
                IDENTITY,
                scanner=self.make_scanner(usb, change_devnum=True),
                runner=FakeRunner(),
                environ={"XDG_RUNTIME_DIR": str(runtime)},
            )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["reason"], "connection-changed")

    def test_production_clone_sources_contain_no_destructive_command(self):
        sources = "\n".join(
            Path(name).read_text()
            for name in ("clone_probe.py", "clone_policy.py", "usb_clone.py")
        )
        for forbidden in (
            "write-flash",
            "erase-flash",
            "erase-region",
            "--force",
            "burn-key",
            "burn-efuse",
        ):
            self.assertNotIn(forbidden, sources)


class CliContractTests(unittest.TestCase):
    def test_probe_cli_outputs_json_by_identity(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            usb = root / "usb"
            usb.mkdir()
            (usb / "devnum").write_text("7\n")
            scanner = lambda: [source_device(usb)]
            output = []

            status = main(
                ["probe", "--identity-key", IDENTITY],
                scanner=scanner,
                runner=FakeRunner(),
                printer=output.append,
            )

            self.assertEqual(status, 0)
            payload = json.loads(output[-1])
            self.assertEqual(payload["operation"], "probe")
            self.assertEqual(payload["status"], "pass")
            self.assertEqual(payload["identityKey"], IDENTITY)
            self.assertEqual(payload["probe"]["chipModel"], "ESP32-D0WD-V3")

    def test_read_source_cli_returns_nonzero_json_failure(self):
        output = []
        status = main(
            ["read-source", "--identity-key", IDENTITY],
            scanner=lambda: [],
            runner=FakeRunner(),
            environ={},
            printer=output.append,
        )
        self.assertNotEqual(status, 0)
        payload = json.loads(output[-1])
        self.assertEqual(payload["operation"], "read-source")
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["reason"], "identity-not-connected")


class AdditionalConnectionTests(unittest.TestCase):
    def test_missing_sys_path_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "missing-sys-path"):
            read_connection_token({})


class AdditionalSourceReadTests(unittest.TestCase):
    def _usb(self, root):
        usb = root / "usb"
        usb.mkdir()
        (usb / "devnum").write_text("7\n")
        return usb

    def test_wrong_source_size_is_rejected(self):
        class ShortRunner(FakeRunner):
            def __call__(self, args, **kwargs):
                command = list(args)
                if "read-flash" in command:
                    self.calls.append(command)
                    Path(command[-1]).write_bytes(b"short")
                    return CompletedProcess(command, 0, "ok", "")
                return super().__call__(args, **kwargs)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            runtime.mkdir()
            usb = self._usb(root)
            result = read_source(
                IDENTITY,
                scanner=lambda: [source_device(usb)],
                runner=ShortRunner(),
                environ={"XDG_RUNTIME_DIR": str(runtime)},
            )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["reason"], "source-size-mismatch")

    def test_source_disconnect_after_read_is_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            runtime.mkdir()
            usb = self._usb(root)
            calls = {"count": 0}

            def scanner():
                calls["count"] += 1
                return [source_device(usb)] if calls["count"] == 1 else []

            result = read_source(
                IDENTITY,
                scanner=scanner,
                runner=FakeRunner(),
                environ={"XDG_RUNTIME_DIR": str(runtime)},
            )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["reason"], "source-disconnected")

    def test_image_is_private_during_read(self):
        class ModeRunner(FakeRunner):
            def __init__(self):
                super().__init__()
                self.output_mode = None

            def __call__(self, args, **kwargs):
                result = super().__call__(args, **kwargs)
                command = list(args)
                if "read-flash" in command:
                    self.output_mode = os.stat(command[-1]).st_mode & 0o777
                return result

        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            runtime.mkdir()
            usb = self._usb(root)
            runner = ModeRunner()
            result = read_source(
                IDENTITY,
                scanner=lambda: [source_device(usb)],
                runner=runner,
                environ={"XDG_RUNTIME_DIR": str(runtime)},
            )
            self.assertEqual(result["status"], "pass")
            self.assertEqual(runner.output_mode, 0o600)

    def test_cleanup_failure_returns_explicit_failure(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            runtime.mkdir()
            usb = self._usb(root)
            real_rmtree = __import__("shutil").rmtree

            def failing_rmtree(path, *args, **kwargs):
                if "read-" in Path(path).name:
                    raise OSError("cleanup blocked")
                return real_rmtree(path, *args, **kwargs)

            with patch("usb_clone.shutil.rmtree", side_effect=failing_rmtree):
                result = read_source(
                    IDENTITY,
                    scanner=lambda: [source_device(usb)],
                    runner=FakeRunner(),
                    environ={"XDG_RUNTIME_DIR": str(runtime)},
                )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["reason"], "cleanup-failed")


if __name__ == "__main__":
    unittest.main()
