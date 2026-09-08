import unittest

from clone_policy import evaluate_pair, evaluate_source


def scanner_device(identity="usb-topology:1a86:7523:3-1.3"):
    return {
        "connected": True,
        "identityKey": identity,
        "serialAvailable": True,
        "readable": True,
        "writable": True,
        "locked": False,
    }


def valid_probe(mac="68:09:47:9e:3c:88"):
    return {
        "ok": True,
        "cloneFamily": "esp32-classic-spi-flash",
        "socFamily": "ESP32",
        "chipModel": "ESP32-D0WD-V3",
        "chipRevision": "v3.1",
        "chipMac": mac,
        "flashManufacturer": "68",
        "flashDevice": "4016",
        "flashSize": 4194304,
        "flashEncryption": False,
        "secureBootV1": False,
        "secureBootV2": False,
        "uartDownloadEnabled": True,
        "rawReadSupported": True,
        "rawWriteCandidate": False,
    }


class SourcePolicyTests(unittest.TestCase):
    def test_validated_source_is_read_ready(self):
        decision = evaluate_source(scanner_device(), valid_probe())
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.state, "ready")
        self.assertEqual(decision.reason, "")

    def test_disconnected_source_is_rejected(self):
        device = scanner_device()
        device["connected"] = False
        self.assertEqual(evaluate_source(device, valid_probe()).reason, "source-disconnected")

    def test_probe_failure_is_rejected(self):
        probe = valid_probe()
        probe["ok"] = False
        self.assertEqual(evaluate_source(scanner_device(), probe).reason, "probe-failed")

    def test_flash_encryption_is_rejected(self):
        probe = valid_probe()
        probe["flashEncryption"] = True
        self.assertEqual(evaluate_source(scanner_device(), probe).reason, "security-restricted")

    def test_secure_boot_is_rejected(self):
        for field in ("secureBootV1", "secureBootV2"):
            probe = valid_probe()
            probe[field] = True
            with self.subTest(field=field):
                self.assertEqual(evaluate_source(scanner_device(), probe).reason, "security-restricted")

    def test_uart_download_disabled_is_rejected(self):
        probe = valid_probe()
        probe["uartDownloadEnabled"] = False
        self.assertEqual(evaluate_source(scanner_device(), probe).reason, "security-restricted")

    def test_unvalidated_flash_is_rejected(self):
        probe = valid_probe()
        probe["flashDevice"] = "9999"
        self.assertEqual(evaluate_source(scanner_device(), probe).reason, "unsupported-flash")

    def test_missing_identity_is_rejected(self):
        device = scanner_device("")
        self.assertEqual(evaluate_source(device, valid_probe()).reason, "identity-insufficient")

    def test_locked_port_is_rejected(self):
        device = scanner_device()
        device["locked"] = True
        self.assertEqual(evaluate_source(device, valid_probe()).reason, "port-in-use")


class PairPolicyTests(unittest.TestCase):
    def test_same_identity_is_rejected(self):
        source = scanner_device("source")
        target = scanner_device("source")
        decision = evaluate_pair(source, target, valid_probe("00:00:00:00:00:01"), valid_probe("00:00:00:00:00:02"))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "same-device")

    def test_same_chip_mac_is_rejected(self):
        source = scanner_device("source")
        target = scanner_device("target")
        decision = evaluate_pair(source, target, valid_probe("00:00:00:00:00:01"), valid_probe("00:00:00:00:00:01"))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "same-device")

    def test_missing_chip_mac_is_rejected(self):
        source_probe = valid_probe("")
        target_probe = valid_probe("00:00:00:00:00:02")
        decision = evaluate_pair(scanner_device("source"), scanner_device("target"), source_probe, target_probe)
        self.assertEqual(decision.reason, "identity-insufficient")

    def test_different_flash_size_is_rejected(self):
        source_probe = valid_probe("00:00:00:00:00:01")
        target_probe = valid_probe("00:00:00:00:00:02")
        target_probe["flashSize"] = 8388608
        decision = evaluate_pair(scanner_device("source"), scanner_device("target"), source_probe, target_probe)
        self.assertEqual(decision.reason, "flash-size-mismatch")

    def test_matching_validated_pair_is_compatible_but_not_write_enabled(self):
        source_probe = valid_probe("00:00:00:00:00:01")
        target_probe = valid_probe("00:00:00:00:00:02")
        decision = evaluate_pair(scanner_device("source"), scanner_device("target"), source_probe, target_probe)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.state, "ready")
        self.assertEqual(decision.clone_family, "esp32-classic-spi-flash")
        self.assertFalse(source_probe["rawWriteCandidate"])
        self.assertFalse(target_probe["rawWriteCandidate"])


class AdditionalSourcePolicyTests(unittest.TestCase):
    def test_serial_interface_unavailable_is_rejected(self):
        device = scanner_device()
        device["serialAvailable"] = False
        self.assertEqual(evaluate_source(device, valid_probe()).reason, "serial-interface-unavailable")

    def test_permission_required_is_rejected(self):
        for field in ("readable", "writable"):
            device = scanner_device()
            device[field] = False
            with self.subTest(field=field):
                self.assertEqual(evaluate_source(device, valid_probe()).reason, "permission-required")

    def test_raw_read_unsupported_is_rejected(self):
        probe = valid_probe()
        probe["rawReadSupported"] = False
        self.assertEqual(evaluate_source(scanner_device(), probe).reason, "raw-read-unsupported")

    def test_unvalidated_revision_is_rejected(self):
        probe = valid_probe()
        probe["chipRevision"] = "v3.0"
        self.assertEqual(evaluate_source(scanner_device(), probe).reason, "unsupported-soc")

    def test_unvalidated_size_is_rejected(self):
        probe = valid_probe()
        probe["flashSize"] = 8388608
        self.assertEqual(evaluate_source(scanner_device(), probe).reason, "unsupported-soc")


class AdditionalPairPolicyTests(unittest.TestCase):
    def test_different_chip_model_is_rejected(self):
        source_probe = valid_probe("00:00:00:00:00:01")
        target_probe = valid_probe("00:00:00:00:00:02")
        target_probe["chipModel"] = "ESP32-S3"
        decision = evaluate_pair(scanner_device("source"), scanner_device("target"), source_probe, target_probe)
        self.assertEqual(decision.reason, "incompatible")

    def test_different_revision_is_rejected(self):
        source_probe = valid_probe("00:00:00:00:00:01")
        target_probe = valid_probe("00:00:00:00:00:02")
        target_probe["chipRevision"] = "v3.0"
        decision = evaluate_pair(scanner_device("source"), scanner_device("target"), source_probe, target_probe)
        self.assertEqual(decision.reason, "incompatible")

    def test_target_security_restriction_is_rejected(self):
        source_probe = valid_probe("00:00:00:00:00:01")
        target_probe = valid_probe("00:00:00:00:00:02")
        target_probe["flashEncryption"] = True
        decision = evaluate_pair(scanner_device("source"), scanner_device("target"), source_probe, target_probe)
        self.assertEqual(decision.reason, "security-restricted")


if __name__ == "__main__":
    unittest.main()
