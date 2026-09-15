import hashlib
import json
import os
from pathlib import Path
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
import unittest
import usb_clone
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

    def test_production_clone_sources_contain_no_explicit_erase_or_efuse_write(self):
        protected_sources = "\n".join(
            Path(name).read_text()
            for name in ("clone_probe.py", "clone_policy.py")
        )
        self.assertNotIn("write-flash", protected_sources)

        all_sources = "\n".join(
            Path(name).read_text()
            for name in ("clone_probe.py", "clone_policy.py", "usb_clone.py")
        )
        for forbidden in (
            "erase-flash",
            "erase-region",
            "--force",
            "burn-key",
            "burn-efuse",
        ):
            self.assertNotIn(forbidden, all_sources)


class CloneTransactionTests(unittest.TestCase):
    def test_clone_writes_snapshot_then_independently_reads_back(self):
        self.assertTrue(hasattr(usb_clone, "clone_flash"))

        source_identity = "source"
        target_identity = "target"

        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            runtime.mkdir()

            source_usb = root / "source-usb"
            target_usb = root / "target-usb"
            source_usb.mkdir()
            target_usb.mkdir()
            (source_usb / "devnum").write_text("7\n")
            (target_usb / "devnum").write_text("8\n")

            def device(identity, usb_path, port):
                return {
                    "connected": True,
                    "identityKey": identity,
                    "serialAvailable": True,
                    "readable": True,
                    "writable": True,
                    "locked": False,
                    "stablePath": "",
                    "port": port,
                    "sysPath": str(usb_path),
                }

            def scanner():
                return [
                    device(source_identity, source_usb, "/dev/ttyUSB1"),
                    device(target_identity, target_usb, "/dev/ttyUSB2"),
                ]

            class CloneRunner:
                def __init__(self):
                    self.calls = []
                    self.source_image = b"\x5a" * 4194304
                    self.target_image = b"\xff" * 4194304

                def __call__(self, args, **kwargs):
                    command = list(args)
                    self.calls.append(command)
                    port = command[command.index("-p") + 1]

                    if command[-1] == "chip-id":
                        output = CHIP_ID
                        if port == "/dev/ttyUSB2":
                            output = output.replace(
                                "68:09:47:9e:3c:88",
                                "68:09:47:9e:3c:89",
                            )
                        return CompletedProcess(command, 0, output, "")

                    if command[-1] == "flash-id":
                        return CompletedProcess(command, 0, FLASH_ID, "")

                    if command[-3:] == ["summary", "--format", "json"]:
                        return CompletedProcess(command, 0, EFUSES, "")

                    if "write-flash" in command:
                        self.target_image = Path(command[-1]).read_bytes()
                        return CompletedProcess(command, 0, "write ok", "")

                    if "read-flash" in command:
                        output = Path(command[-1])
                        image = (
                            self.source_image
                            if port == "/dev/ttyUSB1"
                            else self.target_image
                        )
                        output.write_bytes(image)
                        return CompletedProcess(command, 0, "read ok", "")

                    raise AssertionError(command)

            runner = CloneRunner()

            result = usb_clone.clone_flash(
                source_identity,
                target_identity,
                scanner=scanner,
                runner=runner,
                environ={"XDG_RUNTIME_DIR": str(runtime)},
            )

            expected = hashlib.sha256(runner.source_image).hexdigest()

            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["sourceSha256"], expected)
            self.assertEqual(result["targetSha256"], expected)
            self.assertEqual(result["imageSize"], 4194304)

            write_calls = [
                call for call in runner.calls
                if "write-flash" in call
            ]
            self.assertEqual(len(write_calls), 1)
            self.assertIn("--after", write_calls[0])
            self.assertIn("no-reset", write_calls[0])
            self.assertIn("0x0", write_calls[0])

            write_index = next(
                index
                for index, call in enumerate(runner.calls)
                if "write-flash" in call
            )
            target_read_index = max(
                index
                for index, call in enumerate(runner.calls)
                if "read-flash" in call
                and "/dev/ttyUSB2" in call
            )
            self.assertGreater(target_read_index, write_index)

            flattened = " ".join(
                " ".join(call)
                for call in runner.calls
            )
            self.assertNotIn("erase-flash", flattened)
            self.assertNotIn("erase-region", flattened)
            self.assertNotIn("burn-efuse", flattened)
            self.assertNotIn("burn-key", flattened)

            clone_root = runtime / "omarchy" / "usb-boards" / "clone"
            self.assertEqual(list(clone_root.rglob("*.bin")), [])


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

    def test_clone_cli_rejects_wrong_target_confirmation(self):
        output = []

        status = main(
            [
                "clone",
                "--source-identity-key", "source",
                "--target-identity-key", "target",
                "--confirm-target-identity", "wrong-target",
            ],
            scanner=lambda: [],
            runner=FakeRunner(),
            environ={},
            printer=output.append,
        )

        self.assertNotEqual(status, 0)
        payload = json.loads(output[-1])
        self.assertEqual(payload["operation"], "clone")
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["reason"], "target-confirmation-mismatch")

    def test_clone_cli_dispatches_after_exact_target_confirmation(self):
        output = []

        status = main(
            [
                "clone",
                "--source-identity-key", "source",
                "--target-identity-key", "target",
                "--confirm-target-identity", "target",
            ],
            scanner=lambda: [],
            runner=FakeRunner(),
            environ={},
            printer=output.append,
        )

        self.assertNotEqual(status, 0)
        payload = json.loads(output[-1])
        self.assertEqual(payload["operation"], "clone")
        self.assertEqual(payload["reason"], "identity-not-connected")

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


class CloneFamilyDiscoveryRedGateTests(unittest.TestCase):
    def test_probe_clone_family_api_exists(self):
        self.assertTrue(
            hasattr(usb_clone, "probe_clone_family"),
            "probe_clone_family is not implemented",
        )


@unittest.skipUnless(
    hasattr(usb_clone, "probe_clone_family"),
    "probe_clone_family is not implemented",
)
class CloneFamilyDiscoveryContractTests(unittest.TestCase):
    PORT = "/dev/serial/by-id/test"

    def test_existing_esp32_probe_remains_first_and_stops_fallback(self):
        esp32_probe = {
            "ok": True,
            "cloneFamily": "esp32-classic-spi-flash",
        }

        with patch(
            "usb_clone.run_esp32_probe",
            return_value=esp32_probe,
        ) as esp32, patch(
            "usb_clone.run_avr_probe",
        ) as avr:
            result = usb_clone.probe_clone_family(
                self.PORT,
                runner=object(),
            )

        self.assertIs(result, esp32_probe)
        esp32.assert_called_once()
        avr.assert_not_called()

    def test_avr_probe_runs_only_after_esp32_probe_fails(self):
        esp32_failure = {
            "ok": False,
            "cloneFamily": "",
            "error": "probe-command-failed",
        }
        avr_probe = {
            "ok": True,
            "cloneFamily": "avr-stk500v1-serial",
            "protocol": "stk500v1",
            "baud": 115200,
            "bootloaderReportedSignature": "1e950f",
            "rawReadSupported": True,
            "rawWriteCandidate": True,
            "error": "",
        }

        with patch(
            "usb_clone.run_esp32_probe",
            return_value=esp32_failure,
        ) as esp32, patch(
            "usb_clone.run_avr_probe",
            return_value=avr_probe,
        ) as avr:
            result = usb_clone.probe_clone_family(
                self.PORT,
                runner=object(),
            )

        self.assertIs(result, avr_probe)
        esp32.assert_called_once()
        avr.assert_called_once()

    def test_unknown_device_fails_closed_after_both_read_only_probes(self):
        esp32_failure = {
            "ok": False,
            "cloneFamily": "",
            "error": "probe-command-failed",
        }
        avr_failure = {
            "ok": False,
            "cloneFamily": "",
            "error": "avr-probe-command-failed",
        }

        with patch(
            "usb_clone.run_esp32_probe",
            return_value=esp32_failure,
        ), patch(
            "usb_clone.run_avr_probe",
            return_value=avr_failure,
        ):
            result = usb_clone.probe_clone_family(
                self.PORT,
                runner=object(),
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["cloneFamily"], "")
        self.assertEqual(
            result["error"],
            "unsupported-clone-family",
        )


class AvrSourceReadDispatchTests(unittest.TestCase):
    def test_read_source_dispatches_to_avr_backend(self):
        source_identity = "avr-source"

        with TemporaryDirectory() as directory:
            root = Path(directory)

            runtime = root / "runtime"
            runtime.mkdir()

            usb = root / "usb"
            usb.mkdir()
            (usb / "devnum").write_text("7\n")

            device = {
                "connected": True,
                "identityKey": source_identity,
                "serialAvailable": True,
                "readable": True,
                "writable": True,
                "locked": False,
                "stablePath": "",
                "port": "/dev/ttyUSB1",
                "sysPath": str(usb),
            }

            scanner = lambda: [device]

            avr_probe = {
                "ok": True,
                "cloneFamily": "avr-stk500v1-serial",
                "protocol": "stk500v1",
                "baud": 115200,
                "bootloaderReportedSignature": "1e950f",
                "rawReadSupported": True,
                "rawWriteCandidate": True,
                "error": "",
            }

            image = b"\x5a" * 32768
            expected = hashlib.sha256(image).hexdigest()

            def avr_read(port, output_path, *, runner):
                self.assertEqual(port, "/dev/ttyUSB1")
                output_path.write_bytes(image)

            with patch(
                "usb_clone.probe_clone_family",
                return_value=avr_probe,
            ) as discovery, patch(
                "usb_clone.run_esp32_probe",
                side_effect=AssertionError(
                    "read_source bypassed family discovery"
                ),
            ), patch(
                "usb_clone.read_avr_flash",
                side_effect=avr_read,
                create=True,
            ) as avr_backend:
                result = read_source(
                    source_identity,
                    scanner=scanner,
                    runner=object(),
                    environ={
                        "XDG_RUNTIME_DIR": str(runtime),
                    },
                )

            self.assertEqual(result["status"], "pass")
            self.assertEqual(
                result["cloneFamily"],
                "avr-stk500v1-serial",
            )
            self.assertEqual(result["imageSize"], 32768)
            self.assertEqual(result["sha256"], expected)

            discovery.assert_called_once()
            avr_backend.assert_called_once()

            clone_root = (
                runtime
                / "omarchy"
                / "usb-boards"
                / "clone"
            )

            self.assertEqual(
                list(clone_root.rglob("*.bin")),
                [],
            )


class AvrCloneDiscoveryDispatchTests(unittest.TestCase):
    def test_clone_flash_uses_family_discovery_for_both_devices(self):
        source_identity = "avr-source"
        target_identity = "avr-target"

        with TemporaryDirectory() as directory:
            root = Path(directory)

            source_usb = root / "source-usb"
            target_usb = root / "target-usb"
            source_usb.mkdir()
            target_usb.mkdir()

            (source_usb / "devnum").write_text("7\n")
            (target_usb / "devnum").write_text("8\n")

            def device(identity, usb_path, port):
                return {
                    "connected": True,
                    "identityKey": identity,
                    "serialAvailable": True,
                    "readable": True,
                    "writable": True,
                    "locked": False,
                    "stablePath": "",
                    "port": port,
                    "sysPath": str(usb_path),
                }

            def scanner():
                return [
                    device(
                        source_identity,
                        source_usb,
                        "/dev/ttyUSB1",
                    ),
                    device(
                        target_identity,
                        target_usb,
                        "/dev/ttyUSB2",
                    ),
                ]

            avr_probe = {
                "ok": True,
                "cloneFamily": "avr-stk500v1-serial",
                "protocol": "stk500v1",
                "baud": 115200,
                "bootloaderReportedSignature": "1e950f",
                "rawReadSupported": True,
                "rawWriteCandidate": True,
                "error": "",
            }

            class StopDecision:
                allowed = False
                reason = "test-stop"

            with patch(
                "usb_clone.probe_clone_family",
                side_effect=[avr_probe, avr_probe],
            ) as discovery, patch(
                "usb_clone.run_esp32_probe",
                side_effect=AssertionError(
                    "clone_flash bypassed family discovery"
                ),
            ), patch(
                "usb_clone.evaluate_write_pair",
                return_value=StopDecision(),
            ):
                result = usb_clone.clone_flash(
                    source_identity,
                    target_identity,
                    scanner=scanner,
                    runner=object(),
                    environ={},
                )

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["reason"], "test-stop")
            self.assertEqual(discovery.call_count, 2)

            calls = discovery.call_args_list

            self.assertEqual(
                calls[0].args[0],
                "/dev/ttyUSB1",
            )
            self.assertEqual(
                calls[1].args[0],
                "/dev/ttyUSB2",
            )


class AvrCloneSourceSnapshotTests(unittest.TestCase):
    def test_clone_flash_reads_avr_source_before_any_write(self):
        source_identity = "avr-source"
        target_identity = "avr-target"

        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            runtime.mkdir()

            source_usb = root / "source-usb"
            target_usb = root / "target-usb"
            source_usb.mkdir()
            target_usb.mkdir()

            (source_usb / "devnum").write_text("7\n")
            (target_usb / "devnum").write_text("8\n")

            def device(identity, usb_path, port):
                return {
                    "connected": True,
                    "identityKey": identity,
                    "serialAvailable": True,
                    "readable": True,
                    "writable": True,
                    "locked": False,
                    "stablePath": "",
                    "port": port,
                    "sysPath": str(usb_path),
                }

            scan_count = 0

            def scanner():
                nonlocal scan_count
                scan_count += 1

                if scan_count == 2:
                    (target_usb / "devnum").write_text("9\n")

                return [
                    device(
                        source_identity,
                        source_usb,
                        "/dev/ttyUSB1",
                    ),
                    device(
                        target_identity,
                        target_usb,
                        "/dev/ttyUSB2",
                    ),
                ]

            avr_probe = {
                "ok": True,
                "cloneFamily": "avr-stk500v1-serial",
                "protocol": "stk500v1",
                "baud": 115200,
                "bootloaderReportedSignature": "1e950f",
                "rawReadSupported": True,
                "rawWriteCandidate": True,
                "error": "",
            }

            class AllowedDecision:
                allowed = True
                reason = ""
                clone_family = "avr-stk500v1-serial"

            def avr_read(port, output_path, *, runner):
                self.assertEqual(port, "/dev/ttyUSB1")
                output_path.write_bytes(b"\x5a" * 32768)

            with patch(
                "usb_clone.probe_clone_family",
                side_effect=[avr_probe, avr_probe],
            ), patch(
                "usb_clone.evaluate_write_pair",
                return_value=AllowedDecision(),
            ), patch(
                "usb_clone.read_avr_flash",
                side_effect=avr_read,
            ) as avr_backend, patch(
                "usb_clone._run_source_read",
                side_effect=AssertionError(
                    "clone_flash bypassed AVR source backend"
                ),
            ), patch(
                "usb_clone._run_target_write",
                side_effect=AssertionError(
                    "destructive write must not run"
                ),
            ):
                result = usb_clone.clone_flash(
                    source_identity,
                    target_identity,
                    scanner=scanner,
                    runner=object(),
                    environ={
                        "XDG_RUNTIME_DIR": str(runtime),
                    },
                )

            self.assertEqual(result["status"], "failed")
            self.assertEqual(
                result["reason"],
                "target-connection-changed",
            )
            avr_backend.assert_called_once()


class AvrCloneTargetWriteDispatchTests(unittest.TestCase):
    def test_clone_flash_dispatches_avr_application_write(self):
        source_identity = "avr-source"
        target_identity = "avr-target"

        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            runtime.mkdir()

            source_usb = root / "source-usb"
            target_usb = root / "target-usb"
            source_usb.mkdir()
            target_usb.mkdir()

            (source_usb / "devnum").write_text("7\n")
            (target_usb / "devnum").write_text("8\n")

            def device(identity, usb_path, port):
                return {
                    "connected": True,
                    "identityKey": identity,
                    "serialAvailable": True,
                    "readable": True,
                    "writable": True,
                    "locked": False,
                    "stablePath": "",
                    "port": port,
                    "sysPath": str(usb_path),
                }

            def scanner():
                return [
                    device(
                        source_identity,
                        source_usb,
                        "/dev/ttyUSB1",
                    ),
                    device(
                        target_identity,
                        target_usb,
                        "/dev/ttyUSB2",
                    ),
                ]

            avr_probe = {
                "ok": True,
                "cloneFamily": "avr-stk500v1-serial",
                "protocol": "stk500v1",
                "baud": 115200,
                "bootloaderReportedSignature": "1e950f",
                "rawReadSupported": True,
                "rawWriteCandidate": True,
                "error": "",
            }

            class AllowedDecision:
                allowed = True
                reason = ""
                clone_family = "avr-stk500v1-serial"

            def avr_read(port, output_path, *, runner):
                if port == "/dev/ttyUSB1":
                    output_path.write_bytes(b"\x5a" * 32768)
                    return

                if port == "/dev/ttyUSB2":
                    raise RuntimeError(
                        "test-stop-after-avr-write"
                    )

                raise AssertionError(
                    f"unexpected AVR port: {port}"
                )

            with patch(
                "usb_clone.probe_clone_family",
                side_effect=[avr_probe, avr_probe],
            ), patch(
                "usb_clone.evaluate_write_pair",
                return_value=AllowedDecision(),
            ), patch(
                "usb_clone.read_avr_flash",
                side_effect=avr_read,
            ), patch(
                "usb_clone.write_application",
                create=True,
            ) as avr_write, patch(
                "usb_clone._run_target_write",
                side_effect=AssertionError(
                    "clone_flash bypassed AVR write backend"
                ),
            ), patch(
                "usb_clone._run_target_readback",
                side_effect=RuntimeError(
                    "test-stop-after-avr-write"
                ),
            ):
                result = usb_clone.clone_flash(
                    source_identity,
                    target_identity,
                    scanner=scanner,
                    runner=object(),
                    environ={
                        "XDG_RUNTIME_DIR": str(runtime),
                    },
                )

            self.assertEqual(result["status"], "failed")
            self.assertEqual(
                result["reason"],
                "test-stop-after-avr-write",
            )

            avr_write.assert_called_once()

            args = avr_write.call_args.args
            self.assertEqual(args[0], "/dev/ttyUSB2")


class AvrCloneTargetReadbackDispatchTests(unittest.TestCase):
    def test_clone_flash_dispatches_avr_target_readback(self):
        source_identity = "avr-source"
        target_identity = "avr-target"

        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            runtime.mkdir()

            source_usb = root / "source-usb"
            target_usb = root / "target-usb"
            source_usb.mkdir()
            target_usb.mkdir()

            (source_usb / "devnum").write_text("7\n")
            (target_usb / "devnum").write_text("8\n")

            def device(identity, usb_path, port):
                return {
                    "connected": True,
                    "identityKey": identity,
                    "serialAvailable": True,
                    "readable": True,
                    "writable": True,
                    "locked": False,
                    "stablePath": "",
                    "port": port,
                    "sysPath": str(usb_path),
                }

            def scanner():
                return [
                    device(
                        source_identity,
                        source_usb,
                        "/dev/ttyUSB1",
                    ),
                    device(
                        target_identity,
                        target_usb,
                        "/dev/ttyUSB2",
                    ),
                ]

            avr_probe = {
                "ok": True,
                "cloneFamily": "avr-stk500v1-serial",
                "protocol": "stk500v1",
                "baud": 115200,
                "bootloaderReportedSignature": "1e950f",
                "rawReadSupported": True,
                "rawWriteCandidate": True,
                "error": "",
            }

            class AllowedDecision:
                allowed = True
                reason = ""
                clone_family = "avr-stk500v1-serial"

            def avr_read(port, output_path, *, runner):
                if port == "/dev/ttyUSB1":
                    output_path.write_bytes(b"\x5a" * 32768)
                    return

                if port == "/dev/ttyUSB2":
                    raise RuntimeError(
                        "test-stop-after-avr-readback"
                    )

                raise AssertionError(
                    f"unexpected AVR port: {port}"
                )

            with patch(
                "usb_clone.probe_clone_family",
                side_effect=[avr_probe, avr_probe],
            ), patch(
                "usb_clone.evaluate_write_pair",
                return_value=AllowedDecision(),
            ), patch(
                "usb_clone.read_avr_flash",
                side_effect=avr_read,
            ) as avr_backend, patch(
                "usb_clone.write_application",
            ) as avr_write, patch(
                "usb_clone._run_target_readback",
                side_effect=AssertionError(
                    "clone_flash bypassed AVR readback backend"
                ),
            ):
                result = usb_clone.clone_flash(
                    source_identity,
                    target_identity,
                    scanner=scanner,
                    runner=object(),
                    environ={
                        "XDG_RUNTIME_DIR": str(runtime),
                    },
                )

            self.assertEqual(result["status"], "failed")
            self.assertEqual(
                result["reason"],
                "test-stop-after-avr-readback",
            )

            avr_write.assert_called_once()
            self.assertEqual(avr_backend.call_count, 2)

            self.assertEqual(
                avr_backend.call_args_list[1].args[0],
                "/dev/ttyUSB2",
            )


class AvrCloneTargetGeometryTests(unittest.TestCase):
    def test_valid_32k_avr_target_readback_passes_size_gate(self):
        source_identity = "avr-source"
        target_identity = "avr-target"

        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            runtime.mkdir()

            source_usb = root / "source-usb"
            target_usb = root / "target-usb"
            source_usb.mkdir()
            target_usb.mkdir()

            (source_usb / "devnum").write_text("7\n")
            (target_usb / "devnum").write_text("8\n")

            def device(identity, usb_path, port):
                return {
                    "connected": True,
                    "identityKey": identity,
                    "serialAvailable": True,
                    "readable": True,
                    "writable": True,
                    "locked": False,
                    "stablePath": "",
                    "port": port,
                    "sysPath": str(usb_path),
                }

            def scanner():
                return [
                    device(
                        source_identity,
                        source_usb,
                        "/dev/ttyUSB1",
                    ),
                    device(
                        target_identity,
                        target_usb,
                        "/dev/ttyUSB2",
                    ),
                ]

            avr_probe = {
                "ok": True,
                "cloneFamily": "avr-stk500v1-serial",
                "protocol": "stk500v1",
                "baud": 115200,
                "bootloaderReportedSignature": "1e950f",
                "rawReadSupported": True,
                "rawWriteCandidate": True,
                "error": "",
            }

            class AllowedDecision:
                allowed = True
                reason = ""
                clone_family = "avr-stk500v1-serial"

            image = b"\x5a" * 32768

            def avr_read(port, output_path, *, runner):
                output_path.write_bytes(image)

            with patch(
                "usb_clone.probe_clone_family",
                side_effect=[avr_probe, avr_probe],
            ), patch(
                "usb_clone.evaluate_write_pair",
                return_value=AllowedDecision(),
            ), patch(
                "usb_clone.read_avr_flash",
                side_effect=avr_read,
            ), patch(
                "usb_clone.write_application",
            ):
                result = usb_clone.clone_flash(
                    source_identity,
                    target_identity,
                    scanner=scanner,
                    runner=object(),
                    environ={
                        "XDG_RUNTIME_DIR": str(runtime),
                    },
                )

            self.assertNotEqual(
                result.get("reason"),
                "target-size-mismatch",
            )


class AvrCloneVerificationIntegrationTests(unittest.TestCase):
    def run_avr_clone(
        self,
        *,
        source_application_sha,
        target_application_sha,
    ):
        import avr_clone

        source_identity = "avr-source"
        target_identity = "avr-target"

        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        root = Path(temporary.name)
        runtime = root / "runtime"
        runtime.mkdir()

        source_usb = root / "source-usb"
        target_usb = root / "target-usb"
        source_usb.mkdir()
        target_usb.mkdir()

        (source_usb / "devnum").write_text("7\n")
        (target_usb / "devnum").write_text("8\n")

        def device(identity, usb_path, port):
            return {
                "connected": True,
                "identityKey": identity,
                "serialAvailable": True,
                "readable": True,
                "writable": True,
                "locked": False,
                "stablePath": "",
                "port": port,
                "sysPath": str(usb_path),
            }

        def scanner():
            return [
                device(
                    source_identity,
                    source_usb,
                    "/dev/ttyUSB1",
                ),
                device(
                    target_identity,
                    target_usb,
                    "/dev/ttyUSB2",
                ),
            ]

        avr_probe = {
            "ok": True,
            "cloneFamily": "avr-stk500v1-serial",
            "protocol": "stk500v1",
            "baud": 115200,
            "bootloaderReportedSignature": "1e950f",
            "rawReadSupported": True,
            "rawWriteCandidate": True,
            "error": "",
        }

        class AllowedDecision:
            allowed = True
            reason = ""
            clone_family = "avr-stk500v1-serial"

        source_evidence = avr_clone.AvrImageEvidence(
            full_size=avr_clone.FULL_FLASH_SIZE,
            full_sha256="source-full",
            application_sha256=source_application_sha,
            bootloader_sha256=(
                avr_clone.VALIDATED_BOOTLOADER_SHA256
            ),
        )

        target_evidence = avr_clone.AvrImageEvidence(
            full_size=avr_clone.FULL_FLASH_SIZE,
            full_sha256="target-full",
            application_sha256=target_application_sha,
            bootloader_sha256=(
                avr_clone.VALIDATED_BOOTLOADER_SHA256
            ),
        )

        def avr_read(port, output_path, *, runner):
            output_path.write_bytes(b"\x5a" * 32768)

            if port == "/dev/ttyUSB1":
                return source_evidence

            if port == "/dev/ttyUSB2":
                return target_evidence

            raise AssertionError(
                f"unexpected AVR port: {port}"
            )

        with patch(
            "usb_clone.probe_clone_family",
            side_effect=[avr_probe, avr_probe],
        ), patch(
            "usb_clone.evaluate_write_pair",
            return_value=AllowedDecision(),
        ), patch(
            "usb_clone.read_avr_flash",
            side_effect=avr_read,
        ), patch(
            "usb_clone.write_application",
        ):
            return usb_clone.clone_flash(
                source_identity,
                target_identity,
                scanner=scanner,
                runner=object(),
                environ={
                    "XDG_RUNTIME_DIR": str(runtime),
                },
            )

    def test_success_reports_explicit_avr_verification_evidence(self):
        import avr_clone

        result = self.run_avr_clone(
            source_application_sha="same-application",
            target_application_sha="same-application",
        )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(
            result["applicationSha256"],
            "same-application",
        )
        self.assertEqual(
            result["bootloaderSha256"],
            avr_clone.VALIDATED_BOOTLOADER_SHA256,
        )

    def test_application_mismatch_fails_closed(self):
        result = self.run_avr_clone(
            source_application_sha="source-application",
            target_application_sha="target-application",
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            result["reason"],
            "avr-application-verification-mismatch",
        )


class AvrProbeOperationTests(unittest.TestCase):
    def test_probe_identity_uses_family_discovery(self):
        identity = "avr-source"

        device = {
            "connected": True,
            "identityKey": identity,
            "serialAvailable": True,
            "readable": True,
            "writable": True,
            "locked": False,
            "stablePath": "",
            "port": "/dev/ttyUSB1",
            "sysPath": "/sys/test-avr",
        }

        avr_probe = {
            "ok": True,
            "cloneFamily": "avr-stk500v1-serial",
            "protocol": "stk500v1",
            "baud": 115200,
            "bootloaderReportedSignature": "1e950f",
            "rawReadSupported": True,
            "rawWriteCandidate": True,
            "error": "",
        }

        with patch(
            "usb_clone.probe_clone_family",
            return_value=avr_probe,
        ) as discovery, patch(
            "usb_clone.run_esp32_probe",
            side_effect=AssertionError(
                "probe operation bypassed family discovery"
            ),
        ):
            result = usb_clone._probe_identity(
                identity,
                scanner=lambda: [device],
                runner=object(),
            )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(
            result["probe"]["cloneFamily"],
            "avr-stk500v1-serial",
        )
        discovery.assert_called_once()

    def test_probe_identity_fails_closed_for_unknown_family(self):
        identity = "unknown-device"

        device = {
            "connected": True,
            "identityKey": identity,
            "serialAvailable": True,
            "readable": True,
            "writable": True,
            "locked": False,
            "stablePath": "",
            "port": "/dev/ttyUSB9",
            "sysPath": "/sys/test-unknown",
        }

        with patch(
            "usb_clone.probe_clone_family",
            return_value={
                "ok": False,
                "cloneFamily": "",
                "error": "unsupported-clone-family",
            },
        ):
            result = usb_clone._probe_identity(
                identity,
                scanner=lambda: [device],
                runner=object(),
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            result["reason"],
            "unsupported-clone-family",
        )


if __name__ == "__main__":
    unittest.main()
