import json
import unittest
from subprocess import CompletedProcess

from clone_probe import parse_chip_id, parse_efuse_json, parse_flash_id, run_esp32_probe


CHIP_ID = """\
esptool v5.3.1
Connected to ESP32 on /dev/ttyUSB1:
Chip type:          ESP32-D0WD-V3 (revision v3.1)
Features:           Wi-Fi, BT, Dual Core + LP Core, 240MHz
Crystal frequency:  40MHz
MAC:                68:09:47:9e:3c:88
"""

FLASH_ID = """\
esptool v5.3.1
Connected to ESP32 on /dev/ttyUSB1:
Chip type:          ESP32-D0WD-V3 (revision v3.1)
Crystal frequency:  40MHz
MAC:                68:09:47:9e:3c:88
Flash Memory Information:
=========================
Manufacturer: 68
Device: 4016
Detected flash size: 4MB
Flash voltage set by a strapping pin: 3.3V
"""

EFUSES = json.dumps({
    "FLASH_CRYPT_CNT": {"value": 0, "readable": True, "writeable": True},
    "ABS_DONE_0": {"value": False, "readable": True, "writeable": True},
    "ABS_DONE_1": {"value": False, "readable": True, "writeable": True},
    "UART_DOWNLOAD_DIS": {"value": False, "readable": True, "writeable": True},
    "RD_DIS": {"value": 0, "readable": True, "writeable": True},
    "WR_DIS": {"value": 0, "readable": True, "writeable": True},
})


class ProbeParserTests(unittest.TestCase):
    def test_parses_measured_chip_identity(self):
        result = parse_chip_id(CHIP_ID)
        self.assertEqual(result["chipModel"], "ESP32-D0WD-V3")
        self.assertEqual(result["chipRevision"], "v3.1")
        self.assertEqual(result["chipMac"], "68:09:47:9e:3c:88")
        self.assertEqual(result["crystalMHz"], 40)

    def test_parses_measured_flash_identity(self):
        result = parse_flash_id(FLASH_ID)
        self.assertEqual(result["flashManufacturer"], "68")
        self.assertEqual(result["flashDevice"], "4016")
        self.assertEqual(result["flashSize"], 4194304)
        self.assertEqual(result["flashVoltage"], "3.3V")

    def test_parses_security_gate_from_json(self):
        result = parse_efuse_json(EFUSES)
        self.assertFalse(result["flashEncryption"])
        self.assertFalse(result["secureBootV1"])
        self.assertFalse(result["secureBootV2"])
        self.assertTrue(result["uartDownloadEnabled"])
        self.assertEqual(result["rdDis"], 0)
        self.assertEqual(result["wrDis"], 0)

    def test_flash_encryption_uses_odd_bit_count(self):
        data = json.loads(EFUSES)
        data["FLASH_CRYPT_CNT"]["value"] = 0b1011
        self.assertTrue(parse_efuse_json(json.dumps(data))["flashEncryption"])

    def test_parses_espefuse_5_3_1_preamble_before_json(self):
        text = (
            "espefuse v5.3.1\n"
            "Connecting....\n"
            "Detecting chip type... ESP32\n\n"
            "=== Run \"summary\" command ===\n"
            + EFUSES
        )
        result = parse_efuse_json(text)
        self.assertFalse(result["flashEncryption"])
        self.assertFalse(result["secureBootV1"])
        self.assertFalse(result["secureBootV2"])
        self.assertTrue(result["uartDownloadEnabled"])



class FakeRunner:
    def __init__(self, fail_command=None):
        self.calls = []
        self.fail_command = fail_command

    def __call__(self, args, **kwargs):
        command = list(args)
        self.calls.append(command)
        joined = " ".join(command)
        if self.fail_command and self.fail_command in joined:
            return CompletedProcess(command, 1, "", "failed")
        if command[-1] == "chip-id":
            return CompletedProcess(command, 0, CHIP_ID, "")
        if command[-1] == "flash-id":
            return CompletedProcess(command, 0, FLASH_ID, "")
        if command[-3:] == ["summary", "--format", "json"]:
            return CompletedProcess(command, 0, EFUSES, "")
        raise AssertionError(command)


class ProbeCommandTests(unittest.TestCase):
    def test_probe_uses_only_read_only_commands(self):
        runner = FakeRunner()
        result = run_esp32_probe("/dev/ttyUSB1", runner=runner)
        self.assertTrue(result["ok"])
        self.assertEqual(result["cloneFamily"], "esp32-classic-spi-flash")
        self.assertTrue(result["rawReadSupported"])
        self.assertFalse(result["rawWriteCandidate"])
        flattened = " ".join(" ".join(call) for call in runner.calls)
        self.assertIn("chip-id", flattened)
        self.assertIn("flash-id", flattened)
        self.assertIn("summary --format json", flattened)
        for forbidden in ("write-flash", "erase-flash", "erase-region", "burn", "--force"):
            self.assertNotIn(forbidden, flattened)

    def test_probe_failure_returns_no_partial_evidence(self):
        result = run_esp32_probe("/dev/ttyUSB1", runner=FakeRunner("flash-id"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["cloneFamily"], "")
        self.assertFalse(result["rawReadSupported"])
        self.assertFalse(result["rawWriteCandidate"])
        self.assertEqual(result["error"], "probe-command-failed")

    def test_invalid_efuse_json_fails_closed(self):
        class BadEfuseRunner(FakeRunner):
            def __call__(self, args, **kwargs):
                command = list(args)
                if command[-3:] == ["summary", "--format", "json"]:
                    self.calls.append(command)
                    return CompletedProcess(command, 0, "not-json", "")
                return super().__call__(args, **kwargs)

        result = run_esp32_probe("/dev/ttyUSB1", runner=BadEfuseRunner())
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid-efuse-json")


class ProbeFailureTests(unittest.TestCase):
    def test_missing_executable_fails_closed(self):
        def missing(args, **kwargs):
            raise FileNotFoundError(args[0])

        result = run_esp32_probe("/dev/ttyUSB1", runner=missing)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "probe-command-failed")

    def test_timeout_fails_closed(self):
        import subprocess

        def timeout(args, **kwargs):
            raise subprocess.TimeoutExpired(args, kwargs.get("timeout", 1))

        result = run_esp32_probe("/dev/ttyUSB1", runner=timeout)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "probe-command-failed")

    def test_malformed_chip_output_fails_closed(self):
        class Runner(FakeRunner):
            def __call__(self, args, **kwargs):
                command = list(args)
                if command[-1] == "chip-id":
                    self.calls.append(command)
                    return CompletedProcess(command, 0, "Chip type: unknown\n", "")
                return super().__call__(args, **kwargs)

        result = run_esp32_probe("/dev/ttyUSB1", runner=Runner())
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "missing-chip-model")

    def test_malformed_flash_output_fails_closed(self):
        class Runner(FakeRunner):
            def __call__(self, args, **kwargs):
                command = list(args)
                if command[-1] == "flash-id":
                    self.calls.append(command)
                    return CompletedProcess(command, 0, "Manufacturer: 68\n", "")
                return super().__call__(args, **kwargs)

        result = run_esp32_probe("/dev/ttyUSB1", runner=Runner())
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "missing-flash-device")

    def test_unreadable_required_efuse_fails_closed(self):
        data = json.loads(EFUSES)
        data["FLASH_CRYPT_CNT"]["readable"] = False

        class Runner(FakeRunner):
            def __call__(self, args, **kwargs):
                command = list(args)
                if command[-3:] == ["summary", "--format", "json"]:
                    self.calls.append(command)
                    return CompletedProcess(command, 0, json.dumps(data), "")
                return super().__call__(args, **kwargs)

        result = run_esp32_probe("/dev/ttyUSB1", runner=Runner())
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "missing-efuse-flash_crypt_cnt")


if __name__ == "__main__":
    unittest.main()
