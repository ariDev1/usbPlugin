import json
from pathlib import Path
import unittest

from usb_boards import base_device, device_identity, serial_identity_quality
from tools import usb_boards_acceptance as acceptance


class ScannerIdentityEvidenceTests(unittest.TestCase):
    def device(self, topology, vendor, product, manufacturer, usb_product, serial):
        details = {
            "vendor": vendor,
            "product": product,
            "manufacturer": manufacturer,
            "usb_product": usb_product,
            "serial": serial,
        }
        return base_device(Path("/tmp") / topology, details, True)

    def test_reported_serial_is_portable_and_explicit(self):
        device = self.device(
            "1-2", "0403", "6001", "FTDI", "FT232R USB UART", "AB0JQVS6"
        )
        self.assertEqual(serial_identity_quality("0403", "6001", "AB0JQVS6"), "reported")
        self.assertEqual(device["identityQuality"], "reported")
        self.assertEqual(device["identityKey"], "usb-serial:0403:6001:AB0JQVS6")
        self.assertEqual(device["identityEvidence"], "usb-serial")
        self.assertFalse(device["identityPortBound"])

    def test_cp2102_default_serial_remains_port_bound(self):
        device = self.device(
            "1-1.3.2", "10c4", "ea60", "Silicon Labs", "CP2102 USB to UART", "0001"
        )
        self.assertEqual(serial_identity_quality("10c4", "ea60", "0001"), "known-default")
        self.assertEqual(device["identityQuality"], "known-default")
        self.assertEqual(device["identityKey"], "usb-topology:10c4:ea60:1-1.3.2")
        self.assertEqual(device["identityEvidence"], "usb-topology")
        self.assertTrue(device["identityPortBound"])

    def test_missing_serial_remains_port_bound(self):
        device = self.device(
            "1-4", "1a86", "7523", "QinHeng Electronics", "USB Serial", ""
        )
        self.assertEqual(serial_identity_quality("1a86", "7523", ""), "missing")
        self.assertEqual(device["identityQuality"], "missing")
        self.assertEqual(device["identityKey"], "usb-topology:1a86:7523:1-4")
        self.assertEqual(device["identityEvidence"], "usb-topology")
        self.assertTrue(device["identityPortBound"])

    def test_existing_identity_function_is_unchanged(self):
        self.assertEqual(
            device_identity("10c4", "ea60", "0001", "1-1.3.2"),
            ("usb-topology:10c4:ea60:1-1.3.2", "usb-topology", True),
        )


class RuntimeAcceptanceEvidenceTests(unittest.TestCase):
    def test_runtime_gate_protects_identity_quality(self):
        self.assertIn("identityQuality", acceptance.IDENTITY_FIELDS)

        scanner = [{
            "identityKey": "usb-serial:0403:6001:AB0JQVS6",
            "identityQuality": "reported",
            "connected": True,
        }]
        runtime = [{
            "identityKey": "usb-serial:0403:6001:AB0JQVS6",
            "identityQuality": "known-default",
            "connected": True,
        }]

        with self.assertRaises(acceptance.AcceptanceError):
            acceptance.compare_connected_devices(scanner, runtime)


class PanelIdentityEvidenceContractTests(unittest.TestCase):
    def source(self):
        return Path(__file__).with_name("Panel.qml").read_text()

    def test_panel_exposes_identity_evidence(self):
        source = self.source()
        self.assertIn('return "PORTABLE"', source)
        self.assertIn('return "PORT-BOUND"', source)
        self.assertIn('return "REPORTED USB SERIAL"', source)
        self.assertIn('return "DEFAULT USB SERIAL"', source)
        self.assertIn('return "NO USB SERIAL"', source)
        self.assertIn('id: identityEvidenceDetails', source)
        self.assertIn('Layout.columnSpan: 4', source)
        self.assertIn('CompactLabel { text: "BASIS" }', source)
        self.assertIn('CompactLabel { text: "BOARD SCOPE" }', source)
        self.assertIn('CompactLabel { text: "EVIDENCE" }', source)
        self.assertIn('return "NOT STORED"', source)

    def test_panel_exposes_legacy_profile_problems(self):
        source = self.source()
        self.assertIn('return "PROFILE UNRESOLVED"', source)
        self.assertIn('return "PROFILE CONFLICT"', source)

    def test_profile_write_preserves_scanner_diagnostics(self):
        source = self.source()
        self.assertIn(
            'identityQuality: device.identityQuality || current.identityQuality || ""',
            source,
        )
        self.assertIn(
            'identificationEvidence: device.identificationEvidence || current.identificationEvidence || ""',
            source,
        )
        self.assertIn(
            'identificationScope: device.identificationScope || current.identificationScope || ""',
            source,
        )


class VersionContractTests(unittest.TestCase):
    def test_development_candidate_is_v040(self):
        manifest = json.loads(Path(__file__).with_name("manifest.json").read_text())
        self.assertEqual(manifest["version"], "0.4.0")


if __name__ == "__main__":
    unittest.main()
