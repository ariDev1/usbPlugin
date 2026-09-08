import importlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


def load_module():
    try:
        return importlib.import_module("tools.usb_boards_acceptance")
    except Exception as error:
        raise AssertionError(f"acceptance module must load: {error}") from error


class AcceptanceJsonTests(unittest.TestCase):
    def test_valid_scanner_json_is_accepted(self):
        acceptance = load_module()
        devices = acceptance.parse_device_json(
            '[{"identityKey":"usb-serial:0403:6001:ABC"}]', "scanner"
        )
        self.assertEqual(devices[0]["identityKey"], "usb-serial:0403:6001:ABC")

    def test_invalid_scanner_json_fails(self):
        acceptance = load_module()
        with self.assertRaises(acceptance.AcceptanceError):
            acceptance.parse_device_json("{bad", "scanner")

    def test_invalid_runtime_json_fails(self):
        acceptance = load_module()
        with self.assertRaises(acceptance.AcceptanceError):
            acceptance.parse_device_json('{"not":"a-list"}', "runtime")


class IdentityComparisonTests(unittest.TestCase):
    def device(self, key, **changes):
        value = {
            "identityKey": key,
            "identityEvidence": "usb-serial",
            "identityPortBound": False,
            "vendorId": "0403",
            "productId": "6001",
            "serial": "ABC",
            "board": "Serial development board (FTDI FT232)",
            "confidence": "bridge-only",
            "identificationEvidence": "bridge",
            "identificationScope": "bridge",
            "connected": True,
        }
        value.update(changes)
        return value

    def test_connected_scanner_and_runtime_identities_match(self):
        acceptance = load_module()
        scanner = [self.device("usb-serial:0403:6001:ABC")]
        runtime = [self.device("usb-serial:0403:6001:ABC")]
        acceptance.compare_connected_devices(scanner, runtime)

    def test_missing_runtime_identity_fails(self):
        acceptance = load_module()
        with self.assertRaises(acceptance.AcceptanceError):
            acceptance.compare_connected_devices(
                [self.device("usb-serial:0403:6001:ABC")], []
            )

    def test_changed_identity_key_fails(self):
        acceptance = load_module()
        with self.assertRaises(acceptance.AcceptanceError):
            acceptance.compare_connected_devices(
                [self.device("usb-serial:0403:6001:ABC")],
                [self.device("usb-serial:0403:6001:XYZ")],
            )

    def test_changed_identity_evidence_fails(self):
        acceptance = load_module()
        runtime = self.device(
            "usb-serial:0403:6001:ABC",
            identityEvidence="usb-topology",
        )
        with self.assertRaises(acceptance.AcceptanceError):
            acceptance.compare_connected_devices(
                [self.device("usb-serial:0403:6001:ABC")], [runtime]
            )

    def test_changed_identity_port_bound_fails(self):
        acceptance = load_module()
        runtime = self.device(
            "usb-serial:0403:6001:ABC",
            identityPortBound=True,
        )
        with self.assertRaises(acceptance.AcceptanceError):
            acceptance.compare_connected_devices(
                [self.device("usb-serial:0403:6001:ABC")], [runtime]
            )

    def test_offline_profiles_do_not_cause_false_mismatch(self):
        acceptance = load_module()
        scanner = [self.device("usb-serial:0403:6001:ABC")]
        runtime = [
            self.device("usb-serial:0403:6001:ABC"),
            self.device("usb-topology:1a86:7523:1-4", connected=False),
        ]
        acceptance.compare_connected_devices(scanner, runtime)

    def test_device_order_does_not_affect_result(self):
        acceptance = load_module()
        first = self.device("usb-serial:0403:6001:ABC")
        second = self.device(
            "usb-topology:10c4:ea60:1-1.3.2",
            identityEvidence="usb-topology",
            identityPortBound=True,
            vendorId="10c4",
            productId="ea60",
            serial="0001",
            board="Serial development board (CP210x)",
        )
        acceptance.compare_connected_devices([first, second], [second, first])

    def test_duplicate_connected_identity_keys_fail_closed(self):
        acceptance = load_module()
        duplicate = self.device("usb-serial:0403:6001:ABC")
        with self.assertRaises(acceptance.AcceptanceError):
            acceptance.compare_connected_devices([duplicate, duplicate], [duplicate])


class DevelopmentGuardTests(unittest.TestCase):
    class Result:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def test_non_development_branch_is_rejected(self):
        acceptance = load_module()

        def runner(args, **kwargs):
            return self.Result(stdout="master\n")

        with self.assertRaises(acceptance.AcceptanceError):
            acceptance.ensure_development_branch(Path("/tmp/project"), runner)

    def test_command_failure_is_rejected(self):
        acceptance = load_module()

        def runner(args, **kwargs):
            return self.Result(returncode=2, stderr="failure")

        with self.assertRaises(acceptance.AcceptanceError):
            acceptance.ensure_development_branch(Path("/tmp/project"), runner)

    def test_active_plugin_must_resolve_to_checkout(self):
        acceptance = load_module()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            config = root / "config"
            plugin = config / "omarchy" / "plugins" / "dev.usb-boards"
            plugin.parent.mkdir(parents=True)
            other = root / "other"
            other.mkdir()
            plugin.symlink_to(other, target_is_directory=True)
            with self.assertRaises(acceptance.AcceptanceError):
                acceptance.ensure_active_plugin_checkout(
                    project,
                    {"XDG_CONFIG_HOME": str(config), "HOME": str(root)},
                )


if __name__ == "__main__":
    unittest.main()
