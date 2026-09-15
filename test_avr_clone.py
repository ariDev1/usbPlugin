import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from avr_clone import (
    APPLICATION_SIZE,
    BOOTLOADER_SIZE,
    BOOTLOADER_START,
    FULL_FLASH_SIZE,
    validate_full_image,
)


class AvrImageValidationTests(unittest.TestCase):
    def _write_image(
        self,
        path: Path,
        application: bytes,
        bootloader: bytes,
    ) -> None:
        self.assertEqual(len(application), APPLICATION_SIZE)
        self.assertEqual(len(bootloader), BOOTLOADER_SIZE)
        path.write_bytes(application + bootloader)

    def test_validated_full_image_reports_exact_evidence(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "source.bin"
            application = b"\x5a" * APPLICATION_SIZE
            bootloader = b"\xa5" * BOOTLOADER_SIZE
            self._write_image(path, application, bootloader)

            expected_bootloader = hashlib.sha256(bootloader).hexdigest()
            expected_application = hashlib.sha256(application).hexdigest()
            expected_full = hashlib.sha256(
                application + bootloader
            ).hexdigest()

            with patch(
                "avr_clone.VALIDATED_BOOTLOADER_SHA256",
                expected_bootloader,
            ):
                evidence = validate_full_image(path)

            self.assertEqual(FULL_FLASH_SIZE, 32768)
            self.assertEqual(APPLICATION_SIZE, 32256)
            self.assertEqual(BOOTLOADER_START, 0x7E00)
            self.assertEqual(BOOTLOADER_SIZE, 512)

            self.assertEqual(
                evidence.full_size,
                FULL_FLASH_SIZE,
            )
            self.assertEqual(
                evidence.full_sha256,
                expected_full,
            )
            self.assertEqual(
                evidence.application_sha256,
                expected_application,
            )
            self.assertEqual(
                evidence.bootloader_sha256,
                expected_bootloader,
            )

    def test_wrong_full_image_size_fails_closed(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "short.bin"
            path.write_bytes(b"\xff" * (FULL_FLASH_SIZE - 1))

            with self.assertRaisesRegex(
                RuntimeError,
                "avr-geometry-mismatch",
            ):
                validate_full_image(path)

    def test_wrong_bootloader_hash_fails_closed(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "source.bin"
            application = b"\x5a" * APPLICATION_SIZE
            bootloader = b"\xa5" * BOOTLOADER_SIZE
            self._write_image(path, application, bootloader)

            with patch(
                "avr_clone.VALIDATED_BOOTLOADER_SHA256",
                "0" * 64,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "avr-bootloader-mismatch",
                ):
                    validate_full_image(path)


import subprocess
from subprocess import CompletedProcess

import avr_clone


AVR_PROBE_STDOUT = """\
0x1e,0x95,0xf
"""

AVR_PROBE_STDERR = """\
Avrdude version 8.2
Using port            : /dev/serial/by-id/test
Using programmer      : arduino
Setting baud rate     : 115200
AVR part              : ATmega328P
Programmer type       : Arduino
Description           : Arduino bootloader using STK500 v1 protocol
HW Version            : 3
FW Version            : 4.4
AVR device initialized and ready to accept instructions
Device signature = 1E 95 0F (ATmega328P, ATA6614Q, LGT8F328P)
Reading signature memory ...
Avrdude done.  Thank you.
"""


class AvrProbeRedGateTests(unittest.TestCase):
    def test_read_only_avr_probe_api_exists(self):
        self.assertTrue(
            hasattr(avr_clone, "run_avr_probe"),
            "run_avr_probe is not implemented",
        )


@unittest.skipUnless(
    hasattr(avr_clone, "run_avr_probe"),
    "run_avr_probe is not implemented",
)
class AvrProbeContractTests(unittest.TestCase):
    PORT = "/dev/serial/by-id/test"

    class Runner:
        def __init__(
            self,
            *,
            returncode=0,
            stdout=AVR_PROBE_STDOUT,
            stderr=AVR_PROBE_STDERR,
        ):
            self.calls = []
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

        def __call__(self, args, **kwargs):
            command = list(args)
            self.calls.append((command, kwargs))
            return CompletedProcess(
                command,
                self.returncode,
                self.stdout,
                self.stderr,
            )

    def test_success_reports_only_measured_serial_interface_evidence(self):
        runner = self.Runner()

        result = avr_clone.run_avr_probe(
            self.PORT,
            runner=runner,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["cloneFamily"],
            "avr-stk500v1-serial",
        )
        self.assertEqual(result["protocol"], "stk500v1")
        self.assertEqual(result["baud"], 115200)
        self.assertEqual(
            result["bootloaderReportedSignature"],
            "1e950f",
        )
        self.assertTrue(result["rawReadSupported"])
        self.assertTrue(result["rawWriteCandidate"])
        self.assertEqual(result["error"], "")

        # The bootloader-reported signature is not independent
        # physical-silicon evidence.
        self.assertNotIn("chipModel", result)
        self.assertNotIn("socFamily", result)

    def test_probe_command_is_exactly_read_only(self):
        runner = self.Runner()

        avr_clone.run_avr_probe(
            self.PORT,
            runner=runner,
        )

        self.assertEqual(len(runner.calls), 1)
        command, kwargs = runner.calls[0]

        self.assertEqual(
            command,
            [
                "avrdude",
                "-v",
                "-n",
                "-p",
                "m328p",
                "-c",
                "arduino",
                "-P",
                self.PORT,
                "-b",
                "115200",
                "-U",
                "signature:r:-:h",
            ],
        )

        self.assertTrue(kwargs["capture_output"])
        self.assertTrue(kwargs["text"])
        self.assertFalse(kwargs["check"])

        flattened = " ".join(command)

        for forbidden in (
            "flash:w:",
            "eeprom",
            "lfuse",
            "hfuse",
            "efuse",
            "lock:w:",
            "-F",
            "--force",
            "erase",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, flattened)

    def test_nonzero_avrdude_exit_fails_closed(self):
        result = avr_clone.run_avr_probe(
            self.PORT,
            runner=self.Runner(returncode=1),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["error"],
            "avr-probe-command-failed",
        )
        self.assertFalse(result["rawReadSupported"])
        self.assertFalse(result["rawWriteCandidate"])

    def test_missing_avrdude_fails_closed(self):
        def missing(args, **kwargs):
            raise FileNotFoundError(args[0])

        result = avr_clone.run_avr_probe(
            self.PORT,
            runner=missing,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["error"],
            "avr-probe-command-failed",
        )

    def test_probe_timeout_fails_closed(self):
        def timeout(args, **kwargs):
            raise subprocess.TimeoutExpired(
                args,
                kwargs.get("timeout", 1),
            )

        result = avr_clone.run_avr_probe(
            self.PORT,
            runner=timeout,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["error"],
            "avr-probe-command-failed",
        )

    def test_missing_signature_fails_closed(self):
        runner = self.Runner(
            stdout="",
            stderr="AVR device initialized\n",
        )

        result = avr_clone.run_avr_probe(
            self.PORT,
            runner=runner,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["error"],
            "avr-signature-missing",
        )

    def test_unexpected_signature_fails_closed(self):
        runner = self.Runner(
            stdout="0x1e,0x95,0x14\n",
            stderr=AVR_PROBE_STDERR.replace(
                "1E 95 0F",
                "1E 95 14",
            ),
        )

        result = avr_clone.run_avr_probe(
            self.PORT,
            runner=runner,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["error"],
            "avr-signature-mismatch",
        )


class AvrFlashReadRedGateTests(unittest.TestCase):
    def test_read_avr_flash_api_exists(self):
        self.assertTrue(
            hasattr(avr_clone, "read_avr_flash"),
            "read_avr_flash is not implemented",
        )


@unittest.skipUnless(
    hasattr(avr_clone, "read_avr_flash"),
    "read_avr_flash is not implemented",
)
class AvrFlashReadContractTests(unittest.TestCase):
    PORT = "/dev/serial/by-id/test"

    @staticmethod
    def _image():
        application = b"\x5a" * avr_clone.APPLICATION_SIZE
        bootloader = b"\xa5" * avr_clone.BOOTLOADER_SIZE
        return application, bootloader

    class Runner:
        def __init__(
            self,
            image: bytes,
            *,
            returncode=0,
            write_output=True,
        ):
            self.image = image
            self.returncode = returncode
            self.write_output = write_output
            self.calls = []
            self.output_existed_before_run = None

        def __call__(self, args, **kwargs):
            command = list(args)
            self.calls.append((command, kwargs))

            update = next(
                item
                for index, item in enumerate(command)
                if index > 0 and command[index - 1] == "-U"
            )
            prefix = "flash:r:"
            suffix = ":r"

            if not update.startswith(prefix) or not update.endswith(suffix):
                raise AssertionError(update)

            output_path = Path(
                update[len(prefix):-len(suffix)]
            )

            self.output_existed_before_run = output_path.exists()

            if self.write_output and self.returncode == 0:
                output_path.write_bytes(self.image)

            return CompletedProcess(
                command,
                self.returncode,
                "",
                "",
            )

    def test_success_returns_validated_image_evidence(self):
        application, bootloader = self._image()

        with TemporaryDirectory() as directory:
            output = Path(directory) / "source.bin"
            runner = self.Runner(application + bootloader)

            expected_boot = hashlib.sha256(bootloader).hexdigest()
            expected_app = hashlib.sha256(application).hexdigest()
            expected_full = hashlib.sha256(
                application + bootloader
            ).hexdigest()

            with patch(
                "avr_clone.VALIDATED_BOOTLOADER_SHA256",
                expected_boot,
            ):
                evidence = avr_clone.read_avr_flash(
                    self.PORT,
                    output,
                    runner=runner,
                )

            self.assertEqual(
                evidence.full_size,
                avr_clone.FULL_FLASH_SIZE,
            )
            self.assertEqual(
                evidence.full_sha256,
                expected_full,
            )
            self.assertEqual(
                evidence.application_sha256,
                expected_app,
            )
            self.assertEqual(
                evidence.bootloader_sha256,
                expected_boot,
            )

    def test_read_command_is_exactly_read_only(self):
        application, bootloader = self._image()

        with TemporaryDirectory() as directory:
            output = Path(directory) / "source.bin"
            runner = self.Runner(application + bootloader)
            expected_boot = hashlib.sha256(bootloader).hexdigest()

            with patch(
                "avr_clone.VALIDATED_BOOTLOADER_SHA256",
                expected_boot,
            ):
                avr_clone.read_avr_flash(
                    self.PORT,
                    output,
                    runner=runner,
                )

            self.assertEqual(len(runner.calls), 1)
            command, kwargs = runner.calls[0]

            self.assertEqual(
                command,
                [
                    "avrdude",
                    "-v",
                    "-n",
                    "-A",
                    "-p",
                    "m328p",
                    "-c",
                    "arduino",
                    "-P",
                    self.PORT,
                    "-b",
                    "115200",
                    "-U",
                    f"flash:r:{output}:r",
                ],
            )

            self.assertTrue(kwargs["capture_output"])
            self.assertTrue(kwargs["text"])
            self.assertFalse(kwargs["check"])

            flattened = " ".join(command)

            for forbidden in (
                "flash:w:",
                "eeprom",
                "lfuse",
                "hfuse",
                "efuse",
                "lock:w:",
                "-F",
                "--force",
                "erase",
            ):
                with self.subTest(forbidden=forbidden):
                    self.assertNotIn(forbidden, flattened)

    def test_preexisting_output_is_removed_before_read(self):
        application, bootloader = self._image()

        with TemporaryDirectory() as directory:
            output = Path(directory) / "source.bin"
            output.write_bytes(b"stale-data")

            runner = self.Runner(application + bootloader)
            expected_boot = hashlib.sha256(bootloader).hexdigest()

            with patch(
                "avr_clone.VALIDATED_BOOTLOADER_SHA256",
                expected_boot,
            ):
                avr_clone.read_avr_flash(
                    self.PORT,
                    output,
                    runner=runner,
                )

            self.assertFalse(
                runner.output_existed_before_run,
                "stale output survived until AVRDUDE execution",
            )

    def test_nonzero_avrdude_exit_fails_closed(self):
        application, bootloader = self._image()

        with TemporaryDirectory() as directory:
            output = Path(directory) / "source.bin"
            runner = self.Runner(
                application + bootloader,
                returncode=1,
            )

            with self.assertRaisesRegex(
                RuntimeError,
                "avr-flash-read-failed",
            ):
                avr_clone.read_avr_flash(
                    self.PORT,
                    output,
                    runner=runner,
                )

    def test_missing_avrdude_fails_closed(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "source.bin"

            def missing(args, **kwargs):
                raise FileNotFoundError(args[0])

            with self.assertRaisesRegex(
                RuntimeError,
                "avr-flash-read-failed",
            ):
                avr_clone.read_avr_flash(
                    self.PORT,
                    output,
                    runner=missing,
                )

    def test_timeout_fails_closed(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "source.bin"

            def timeout(args, **kwargs):
                raise subprocess.TimeoutExpired(
                    args,
                    kwargs.get("timeout", 1),
                )

            with self.assertRaisesRegex(
                RuntimeError,
                "avr-flash-read-failed",
            ):
                avr_clone.read_avr_flash(
                    self.PORT,
                    output,
                    runner=timeout,
                )

    def test_success_without_output_fails_closed(self):
        application, bootloader = self._image()

        with TemporaryDirectory() as directory:
            output = Path(directory) / "source.bin"
            runner = self.Runner(
                application + bootloader,
                write_output=False,
            )

            with self.assertRaisesRegex(
                RuntimeError,
                "avr-image-read-failed",
            ):
                avr_clone.read_avr_flash(
                    self.PORT,
                    output,
                    runner=runner,
                )


class AvrApplicationWriteRedGateTests(unittest.TestCase):
    def test_write_application_api_exists(self):
        self.assertTrue(
            hasattr(avr_clone, "write_application"),
            "write_application is not implemented",
        )


@unittest.skipUnless(
    hasattr(avr_clone, "write_application"),
    "write_application is not implemented",
)
class AvrApplicationWriteContractTests(unittest.TestCase):
    PORT = "/dev/serial/by-id/test"

    @staticmethod
    def _source_image():
        application = bytes(
            index % 251
            for index in range(avr_clone.APPLICATION_SIZE)
        )
        bootloader = b"\xa5" * avr_clone.BOOTLOADER_SIZE
        return application, bootloader

    class Runner:
        def __init__(self, *, returncode=0):
            self.returncode = returncode
            self.calls = []
            self.written_path = None
            self.written_data = None

        def __call__(self, args, **kwargs):
            command = list(args)
            self.calls.append((command, kwargs))

            update = next(
                item
                for index, item in enumerate(command)
                if index > 0 and command[index - 1] == "-U"
            )

            prefix = "flash:w:"
            suffix = ":r"

            if not update.startswith(prefix) or not update.endswith(suffix):
                raise AssertionError(update)

            self.written_path = Path(
                update[len(prefix):-len(suffix)]
            )

            self.written_data = self.written_path.read_bytes()

            return CompletedProcess(
                command,
                self.returncode,
                "",
                "",
            )

    def test_extracts_exact_application_region_before_write(self):
        application, bootloader = self._source_image()

        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            application_path = root / "application.bin"

            source.write_bytes(application + bootloader)

            runner = self.Runner()
            expected_boot = hashlib.sha256(bootloader).hexdigest()

            with patch(
                "avr_clone.VALIDATED_BOOTLOADER_SHA256",
                expected_boot,
            ):
                evidence = avr_clone.write_application(
                    self.PORT,
                    source,
                    application_path,
                    runner=runner,
                )

            self.assertEqual(
                len(runner.written_data),
                avr_clone.APPLICATION_SIZE,
            )
            self.assertEqual(
                runner.written_data,
                application,
            )
            self.assertEqual(
                evidence.application_sha256,
                hashlib.sha256(application).hexdigest(),
            )

    def test_write_command_is_exact_application_only_contract(self):
        application, bootloader = self._source_image()

        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            application_path = root / "application.bin"

            source.write_bytes(application + bootloader)

            runner = self.Runner()
            expected_boot = hashlib.sha256(bootloader).hexdigest()

            with patch(
                "avr_clone.VALIDATED_BOOTLOADER_SHA256",
                expected_boot,
            ):
                avr_clone.write_application(
                    self.PORT,
                    source,
                    application_path,
                    runner=runner,
                )

            self.assertEqual(len(runner.calls), 1)
            command, kwargs = runner.calls[0]

            self.assertEqual(
                command,
                [
                    "avrdude",
                    "-v",
                    "-D",
                    "-A",
                    "-p",
                    "m328p",
                    "-c",
                    "arduino",
                    "-P",
                    self.PORT,
                    "-b",
                    "115200",
                    "-U",
                    f"flash:w:{application_path}:r",
                ],
            )

            self.assertTrue(kwargs["capture_output"])
            self.assertTrue(kwargs["text"])
            self.assertFalse(kwargs["check"])

            flattened = " ".join(command)

            for forbidden in (
                "eeprom",
                "lfuse",
                "hfuse",
                "efuse",
                "lock:w:",
                "-F",
                "--force",
                "erase-flash",
                "erase-region",
            ):
                with self.subTest(forbidden=forbidden):
                    self.assertNotIn(forbidden, flattened)

    def test_full_32768_byte_image_is_never_given_to_avrdude_write(self):
        application, bootloader = self._source_image()

        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            application_path = root / "application.bin"

            source.write_bytes(application + bootloader)

            runner = self.Runner()
            expected_boot = hashlib.sha256(bootloader).hexdigest()

            with patch(
                "avr_clone.VALIDATED_BOOTLOADER_SHA256",
                expected_boot,
            ):
                avr_clone.write_application(
                    self.PORT,
                    source,
                    application_path,
                    runner=runner,
                )

            self.assertEqual(
                len(runner.written_data),
                32256,
            )
            self.assertNotEqual(
                len(runner.written_data),
                32768,
            )

    def test_wrong_source_bootloader_fails_before_write(self):
        application, bootloader = self._source_image()

        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            application_path = root / "application.bin"

            source.write_bytes(application + bootloader)

            runner = self.Runner()

            with patch(
                "avr_clone.VALIDATED_BOOTLOADER_SHA256",
                "0" * 64,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "avr-bootloader-mismatch",
                ):
                    avr_clone.write_application(
                        self.PORT,
                        source,
                        application_path,
                        runner=runner,
                    )

            self.assertEqual(runner.calls, [])

    def test_nonzero_avrdude_exit_fails_closed(self):
        application, bootloader = self._source_image()

        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            application_path = root / "application.bin"

            source.write_bytes(application + bootloader)

            runner = self.Runner(returncode=1)
            expected_boot = hashlib.sha256(bootloader).hexdigest()

            with patch(
                "avr_clone.VALIDATED_BOOTLOADER_SHA256",
                expected_boot,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "avr-application-write-failed",
                ):
                    avr_clone.write_application(
                        self.PORT,
                        source,
                        application_path,
                        runner=runner,
                    )

    def test_missing_avrdude_fails_closed(self):
        application, bootloader = self._source_image()

        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            application_path = root / "application.bin"

            source.write_bytes(application + bootloader)

            expected_boot = hashlib.sha256(bootloader).hexdigest()

            def missing(args, **kwargs):
                raise FileNotFoundError(args[0])

            with patch(
                "avr_clone.VALIDATED_BOOTLOADER_SHA256",
                expected_boot,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "avr-application-write-failed",
                ):
                    avr_clone.write_application(
                        self.PORT,
                        source,
                        application_path,
                        runner=missing,
                    )

    def test_timeout_fails_closed(self):
        application, bootloader = self._source_image()

        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            application_path = root / "application.bin"

            source.write_bytes(application + bootloader)

            expected_boot = hashlib.sha256(bootloader).hexdigest()

            def timeout(args, **kwargs):
                raise subprocess.TimeoutExpired(
                    args,
                    kwargs.get("timeout", 1),
                )

            with patch(
                "avr_clone.VALIDATED_BOOTLOADER_SHA256",
                expected_boot,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "avr-application-write-failed",
                ):
                    avr_clone.write_application(
                        self.PORT,
                        source,
                        application_path,
                        runner=timeout,
                    )


class AvrCloneVerificationContractTests(unittest.TestCase):
    def test_verify_clone_evidence_api_exists(self):
        import avr_clone

        self.assertTrue(
            hasattr(avr_clone, "verify_clone_evidence"),
            "verify_clone_evidence is not implemented",
        )


@unittest.skipUnless(
    hasattr(__import__("avr_clone"), "verify_clone_evidence"),
    "verify_clone_evidence is not implemented",
)
class AvrCloneVerificationBehaviorTests(unittest.TestCase):
    def evidence(
        self,
        *,
        application_sha256="application-a",
        bootloader_sha256=None,
    ):
        import avr_clone

        if bootloader_sha256 is None:
            bootloader_sha256 = (
                avr_clone.VALIDATED_BOOTLOADER_SHA256
            )

        return avr_clone.AvrImageEvidence(
            full_size=avr_clone.FULL_FLASH_SIZE,
            full_sha256="full-image",
            application_sha256=application_sha256,
            bootloader_sha256=bootloader_sha256,
        )

    def test_matching_application_and_validated_bootloader_pass(self):
        import avr_clone

        result = avr_clone.verify_clone_evidence(
            self.evidence(),
            self.evidence(),
        )

        self.assertEqual(
            result.application_sha256,
            "application-a",
        )
        self.assertEqual(
            result.bootloader_sha256,
            avr_clone.VALIDATED_BOOTLOADER_SHA256,
        )

    def test_application_mismatch_fails(self):
        import avr_clone

        with self.assertRaisesRegex(
            RuntimeError,
            "^avr-application-verification-mismatch$",
        ):
            avr_clone.verify_clone_evidence(
                self.evidence(
                    application_sha256="application-a",
                ),
                self.evidence(
                    application_sha256="application-b",
                ),
            )

    def test_unvalidated_bootloader_fails(self):
        import avr_clone

        with self.assertRaisesRegex(
            RuntimeError,
            "^avr-bootloader-mismatch$",
        ):
            avr_clone.verify_clone_evidence(
                self.evidence(),
                self.evidence(
                    bootloader_sha256="not-validated",
                ),
            )


if __name__ == "__main__":
    unittest.main()
