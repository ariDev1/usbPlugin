import json
from pathlib import Path
from subprocess import CompletedProcess
import unittest
from unittest.mock import patch

import clone_tools
import usb_clone
import tools.usb_boards_acceptance as acceptance


class CloneToolPreflightTests(unittest.TestCase):
    def test_reports_available_tools_and_versions_without_device_access(self):

        paths = {
            "esptool": "/usr/bin/esptool",
            "espefuse": "/usr/bin/espefuse",
            "avrdude": "/usr/bin/avrdude",
        }

        calls = []

        def resolver(name):
            return paths.get(name)

        def runner(args, **kwargs):
            command = list(args)
            calls.append(command)

            joined = " ".join(command)

            self.assertNotIn("/dev/", joined)
            self.assertNotIn("--port", command)
            self.assertNotIn("-p", command)
            self.assertNotIn("chip-id", command)
            self.assertNotIn("flash-id", command)
            self.assertNotIn("summary", command)

            if command == ["/usr/bin/esptool", "version"]:
                return CompletedProcess(
                    command,
                    0,
                    "esptool v5.3.1\n",
                    "",
                )

            if command == ["/usr/bin/avrdude", "--version"]:
                return CompletedProcess(
                    command,
                    0,
                    "avrdude version 8.1\n",
                    "",
                )

            raise AssertionError(
                f"unexpected preflight command: {command}"
            )

        result = clone_tools.run_preflight(
            resolver=resolver,
            runner=runner,
        )

        self.assertEqual(result["operation"], "preflight")
        self.assertEqual(result["status"], "pass")

        self.assertEqual(
            result["tools"]["esptool"],
            {
                "available": True,
                "path": "/usr/bin/esptool",
                "version": "5.3.1",
                "versionStatus": "reported",
                "reason": "",
            },
        )

        self.assertEqual(
            result["tools"]["espefuse"],
            {
                "available": True,
                "path": "/usr/bin/espefuse",
                "version": "",
                "versionStatus": "not-queried",
                "reason": "",
            },
        )

        self.assertEqual(
            result["tools"]["avrdude"],
            {
                "available": True,
                "path": "/usr/bin/avrdude",
                "version": "8.1",
                "versionStatus": "reported",
                "reason": "",
            },
        )

        self.assertEqual(
            result["families"]["esp32-classic-spi-flash"],
            {
                "ready": True,
                "reason": "",
            },
        )

        self.assertEqual(
            result["families"]["avr-stk500v1-serial"],
            {
                "ready": True,
                "reason": "",
            },
        )

        self.assertEqual(
            calls,
            [
                ["/usr/bin/esptool", "version"],
                ["/usr/bin/avrdude", "--version"],
            ],
        )

    def test_missing_tool_blocks_only_the_dependent_family(self):

        paths = {
            "esptool": "/usr/bin/esptool",
            "espefuse": None,
            "avrdude": "/usr/bin/avrdude",
        }

        def resolver(name):
            return paths.get(name)

        def runner(args, **kwargs):
            command = list(args)

            if command == ["/usr/bin/esptool", "version"]:
                return CompletedProcess(
                    command,
                    0,
                    "esptool v5.3.1\n",
                    "",
                )

            if command == ["/usr/bin/avrdude", "--version"]:
                return CompletedProcess(
                    command,
                    0,
                    "avrdude version 8.1\n",
                    "",
                )

            raise AssertionError(command)

        result = clone_tools.run_preflight(
            resolver=resolver,
            runner=runner,
        )

        self.assertFalse(
            result["tools"]["espefuse"]["available"]
        )
        self.assertEqual(
            result["tools"]["espefuse"]["reason"],
            "missing-espefuse",
        )

        self.assertEqual(
            result["families"]["esp32-classic-spi-flash"],
            {
                "ready": False,
                "reason": "missing-espefuse",
            },
        )

        self.assertEqual(
            result["families"]["avr-stk500v1-serial"],
            {
                "ready": True,
                "reason": "",
            },
        )

    def test_failed_version_query_is_explicit_and_fail_closed(self):

        paths = {
            "esptool": "/usr/bin/esptool",
            "espefuse": "/usr/bin/espefuse",
            "avrdude": "/usr/bin/avrdude",
        }

        def resolver(name):
            return paths.get(name)

        def runner(args, **kwargs):
            command = list(args)

            if command == ["/usr/bin/esptool", "version"]:
                return CompletedProcess(
                    command,
                    1,
                    "",
                    "version failed",
                )

            if command == ["/usr/bin/avrdude", "--version"]:
                return CompletedProcess(
                    command,
                    0,
                    "avrdude version 8.1\n",
                    "",
                )

            raise AssertionError(command)

        result = clone_tools.run_preflight(
            resolver=resolver,
            runner=runner,
        )

        self.assertEqual(
            result["tools"]["esptool"]["versionStatus"],
            "query-failed",
        )
        self.assertEqual(
            result["tools"]["esptool"]["reason"],
            "esptool-version-query-failed",
        )

        self.assertEqual(
            result["families"]["esp32-classic-spi-flash"],
            {
                "ready": False,
                "reason": "esptool-version-query-failed",
            },
        )

        self.assertTrue(
            result["families"]["avr-stk500v1-serial"]["ready"]
        )

    def test_preflight_cli_does_not_scan_or_probe_devices(self):
        payload = {
            "operation": "preflight",
            "status": "pass",
            "tools": {},
            "families": {},
        }

        output = []

        def scanner():
            self.fail(
                "preflight must not scan connected devices"
            )

        with patch(
            "usb_clone.run_tool_preflight",
            return_value=payload,
        ) as preflight:
            try:
                result = usb_clone.main(
                    ["preflight"],
                    scanner=scanner,
                    runner=object(),
                    printer=output.append,
                )
            except SystemExit as error:
                self.fail(
                    "usb_clone preflight subcommand is missing: "
                    f"{error}"
                )

        self.assertEqual(result, 0)
        self.assertEqual(
            json.loads(output[0]),
            payload,
        )
        preflight.assert_called_once()

    def test_clone_tools_is_part_of_runtime_acceptance_copy(self):
        self.assertIn(
            "clone_tools.py",
            acceptance.RUNTIME_FILES,
        )


    def test_installer_copies_clone_tools_runtime_module(self):
        installer = Path("install.sh").read_text()

        self.assertRegex(
            installer,
            r"(?m)^  clone_tools\.py$",
        )


if __name__ == "__main__":
    unittest.main()
