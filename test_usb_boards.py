import unittest
import fcntl
import os
import stat
from pathlib import Path
import struct
import termios
from tempfile import TemporaryDirectory
from unittest.mock import patch

from usb_boards import device_access, device_identity, identify_board, infer_mode, is_board_candidate, lock_info, scan
from serial_monitor import SessionLogger, configure, line_ending_bytes, monitor, parse_data_format, session_log_path


class IdentifyBoardTests(unittest.TestCase):
    def test_native_espressif_usb(self):
        self.assertEqual(
            identify_board("303a", "1001", "Espressif", "USB JTAG serial debug unit"),
            ("Espressif USB JTAG/Serial", "exact"),
        )

    def test_arduino_nano_esp32_is_exact(self):
        self.assertEqual(
            identify_board("2341", "0070", "Arduino", "Nano ESP32"),
            ("Arduino Nano ESP32", "exact"),
        )

    def test_ch340_does_not_guess_board(self):
        self.assertEqual(
            identify_board("1a86", "7523", "QinHeng Electronics", "USB Serial"),
            ("Serial development board (CH340/CH341)", "bridge-only"),
        )

    def test_additional_board_families(self):
        self.assertEqual(
            identify_board("2e8a", "0003", "Raspberry Pi", "RP2 Boot"),
            ("Raspberry Pi RP2 Bootloader", "exact"),
        )
        self.assertEqual(
            identify_board("0483", "df11", "STMicroelectronics", "STM32 BOOTLOADER"),
            ("STM32 DFU Bootloader", "exact"),
        )
        self.assertEqual(
            identify_board("239a", "80f4", "Adafruit", "Feather RP2040"),
            ("Feather RP2040", "probable"),
        )

    def test_descriptor_match_is_probable_not_exact(self):
        self.assertEqual(
            identify_board("ffff", "0001", "Arduino", "Nano ESP32"),
            ("Arduino Nano ESP32", "probable"),
        )

    def test_modes_are_inferred_from_usb_description(self):
        self.assertEqual(infer_mode("STM32 DFU", False), "dfu")
        self.assertEqual(infer_mode("CMSIS-DAP", False), "debug")
        self.assertEqual(infer_mode("UF2 Bootloader", False), "bootloader")
        self.assertEqual(infer_mode("USB Serial", True), "serial")

    def test_generic_usb_peripheral_is_not_a_board_candidate(self):
        self.assertFalse(is_board_candidate("046d", "c534", "Logitech", "USB Receiver"))
        self.assertTrue(is_board_candidate("303a", "4001", "Espressif", "USB Device"))


class ScannerFixtureTests(unittest.TestCase):
    def make_usb(self, root: Path, name: str, vendor: str, product: str,
                 manufacturer: str, description: str, serial: str = "") -> Path:
        usb = root / "sys" / "devices" / name
        usb.mkdir(parents=True)
        (usb / "idVendor").write_text(vendor)
        (usb / "idProduct").write_text(product)
        (usb / "manufacturer").write_text(manufacturer)
        (usb / "product").write_text(description)
        if serial:
            (usb / "serial").write_text(serial)
        usb_bus = root / "sys" / "bus" / "usb" / "devices"
        usb_bus.mkdir(parents=True, exist_ok=True)
        (usb_bus / name).symlink_to(usb)
        return usb

    def add_tty(self, root: Path, usb: Path, tty_name: str) -> Path:
        tty_device = usb / f"{usb.name}:1.0" / "tty" / tty_name
        tty_device.mkdir(parents=True)
        tty_class = root / "sys" / "class" / "tty"
        tty_class.mkdir(parents=True, exist_ok=True)
        (tty_class / tty_name).symlink_to(tty_device)
        dev = root / "dev"
        dev.mkdir(exist_ok=True)
        port = dev / tty_name
        port.touch()
        return port

    def fixture_scan(self, root: Path):
        return scan(
            sys_tty=root / "sys" / "class" / "tty",
            sys_usb=root / "sys" / "bus" / "usb" / "devices",
            dev_root=root / "dev",
            serial_by_id=root / "dev" / "serial" / "by-id",
            properties_reader=lambda port: {},
        )

    def test_serial_fixture_reports_stable_path(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            usb = self.make_usb(root, "1-2", "1a86", "55d4", "WCH", "USB Serial", "ABC")
            port = self.add_tty(root, usb, "ttyUSB0")
            by_id = root / "dev" / "serial" / "by-id"
            by_id.mkdir(parents=True)
            (by_id / "usb-WCH_ABC-if00-port0").symlink_to(port)

            devices = self.fixture_scan(root)

            self.assertEqual(len(devices), 1)
            self.assertEqual(devices[0]["bridge"], "CH9102/CH343")
            self.assertEqual(devices[0]["port"], str(port))
            self.assertEqual(devices[0]["stablePath"], str(by_id / "usb-WCH_ABC-if00-port0"))
            self.assertTrue(devices[0]["serialAvailable"])
            self.assertEqual(devices[0].get("identificationEvidence"), "bridge")

    def test_bootloader_without_tty_is_reported(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_usb(root, "2-1", "2e8a", "0003", "Raspberry Pi", "RP2 Boot")

            devices = self.fixture_scan(root)

            self.assertEqual(len(devices), 1)
            self.assertEqual(devices[0]["board"], "Raspberry Pi RP2 Bootloader")
            self.assertEqual(devices[0]["mode"], "bootloader")
            self.assertFalse(devices[0]["serialAvailable"])
            self.assertEqual(devices[0].get("identificationEvidence"), "vid-pid")

    def test_multiple_ttys_are_deduplicated_by_physical_device(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            usb = self.make_usb(root, "3-1", "303a", "1001", "Espressif", "USB JTAG/serial")
            first = self.add_tty(root, usb, "ttyACM0")
            second = self.add_tty(root, usb, "ttyACM1")

            devices = self.fixture_scan(root)

            self.assertEqual(len(devices), 1)
            self.assertEqual(devices[0]["port"], str(first))
            self.assertEqual(devices[0]["ports"], [str(first), str(second)])

    def test_descriptor_identification_reports_descriptor_evidence(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            usb = self.make_usb(root, "5-1", "ffff", "0001", "Arduino", "Nano ESP32")
            self.add_tty(root, usb, "ttyACM0")

            devices = self.fixture_scan(root)

            self.assertEqual(len(devices), 1)
            self.assertEqual(devices[0]["board"], "Arduino Nano ESP32")
            self.assertEqual(devices[0]["confidence"], "probable")
            self.assertEqual(devices[0].get("identificationEvidence"), "descriptor")

    def test_unknown_serial_device_reports_unknown_evidence(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            usb = self.make_usb(root, "6-1", "ffff", "0002", "Example", "USB Serial")
            self.add_tty(root, usb, "ttyUSB0")

            devices = self.fixture_scan(root)

            self.assertEqual(len(devices), 1)
            self.assertEqual(devices[0]["confidence"], "unknown")
            self.assertEqual(devices[0].get("identificationEvidence"), "unknown")

    def test_vendor_fallback_reports_vendor_evidence(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            usb = self.make_usb(root, "7-1", "239a", "9999", "Adafruit", "")
            self.add_tty(root, usb, "ttyACM0")

            devices = self.fixture_scan(root)

            self.assertEqual(len(devices), 1)
            self.assertEqual(devices[0]["board"], "Adafruit development board")
            self.assertEqual(devices[0]["confidence"], "probable")
            self.assertEqual(devices[0].get("identificationEvidence"), "vendor")

    def test_usb_serial_identity_is_not_port_bound(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            usb = self.make_usb(root, "8-1", "10c4", "ea60", "Silicon Labs", "CP2102 USB to UART", "ABC123")
            self.add_tty(root, usb, "ttyUSB0")

            devices = self.fixture_scan(root)

            self.assertEqual(devices[0].get("identityKey"), "usb-serial:10c4:ea60:ABC123")
            self.assertEqual(devices[0].get("identityEvidence"), "usb-serial")
            self.assertFalse(devices[0].get("identityPortBound"))

    def test_device_without_usb_serial_uses_port_bound_topology_identity(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            usb = self.make_usb(root, "2-1.2", "1a86", "7523", "QinHeng Electronics", "USB Serial")
            self.add_tty(root, usb, "ttyUSB0")

            devices = self.fixture_scan(root)

            self.assertEqual(devices[0].get("identityKey"), "usb-topology:1a86:7523:2-1.2")
            self.assertEqual(devices[0].get("identityEvidence"), "usb-topology")
            self.assertTrue(devices[0].get("identityPortBound"))

    def test_unlabelled_unknown_device_does_not_require_board_knowledge(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            usb = self.make_usb(root, "9-3", "ffff", "1234", "", "")
            self.add_tty(root, usb, "ttyUSB0")

            devices = self.fixture_scan(root)

            self.assertEqual(devices[0]["board"], "USB serial device")
            self.assertEqual(devices[0]["confidence"], "unknown")
            self.assertEqual(devices[0].get("identityEvidence"), "usb-topology")
            self.assertTrue(devices[0].get("identityPortBound"))

    def test_unrelated_usb_device_without_tty_is_ignored(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_usb(root, "4-1", "046d", "c534", "Logitech", "USB Receiver")
            self.assertEqual(self.fixture_scan(root), [])


class DeviceIdentityQualityTests(unittest.TestCase):
    def test_cp2102_default_serial_is_not_portable_identity(self):
        self.assertEqual(
            device_identity("10c4", "ea60", "0001", "2-1.2"),
            ("usb-topology:10c4:ea60:2-1.2", "usb-topology", True),
        )

    def test_cp2102_non_default_serial_remains_portable_identity(self):
        self.assertEqual(
            device_identity("10c4", "ea60", "ABC123", "2-1.2"),
            ("usb-serial:10c4:ea60:ABC123", "usb-serial", False),
        )


class PanelIdentityContractTests(unittest.TestCase):
    def panel_source(self):
        return Path(__file__).with_name("Panel.qml").read_text()

    def test_profile_key_prefers_scanner_identity_key(self):
        source = self.panel_source()
        self.assertIn("device.identityKey ? device.identityKey : legacyProfileKey(device)", source)

    def test_port_bound_identity_does_not_reuse_legacy_profile(self):
        source = self.panel_source()
        self.assertIn('device.identityEvidence !== "usb-topology"', source)

    def test_panel_explains_port_bound_identity(self):
        source = self.panel_source()
        self.assertIn('return "USB PORT"', source)



class DeviceAccessTests(unittest.TestCase):
    @patch("usb_boards.grp.getgrgid")
    @patch("usb_boards.os.access")
    @patch("usb_boards.os.stat")
    def test_reports_permissions_and_device_group(self, stat, access, getgrgid):
        stat.return_value.st_mode = 0o20660
        stat.return_value.st_gid = 984
        access.side_effect = [False, False]
        getgrgid.return_value.gr_name = "uucp"

        self.assertEqual(
            device_access("/dev/ttyUSB0"),
            {
                "readable": False,
                "writable": False,
                "permissions": "0o660",
                "group": "uucp",
            },
        )

    @patch("usb_boards.Path.exists", return_value=True)
    @patch("usb_boards.Path.read_text", return_value="1234\n")
    @patch("usb_boards.os.path.exists", return_value=True)
    def test_reports_serial_lock_owner(self, path_exists, read_text, os_exists):
        info = lock_info("/dev/ttyUSB0", lock_dirs=("/run/lock",))
        self.assertEqual(info["locked"], True)
        self.assertEqual(info["lockPath"], "/run/lock/LCK..ttyUSB0")
        self.assertEqual(info["lockPid"], 1234)

    @patch("usb_boards.Path.exists", return_value=False)
    def test_reports_unlocked_serial_port(self, path_exists):
        self.assertEqual(lock_info("/dev/ttyACM0", lock_dirs=("/run/lock",)), {
            "locked": False,
            "lockPath": "",
            "lockPid": 0,
        })


class SerialMonitorTests(unittest.TestCase):
    def test_serial_data_formats_are_parsed(self):
        self.assertEqual(parse_data_format("8N1"), (8, "N", 1))
        self.assertEqual(parse_data_format("7E1"), (7, "E", 1))
        self.assertEqual(parse_data_format("8N2"), (8, "N", 2))
        with self.assertRaises(ValueError):
            parse_data_format("6X1")

    def test_line_ending_options_are_explicit(self):
        self.assertEqual(line_ending_bytes("none"), b"")
        self.assertEqual(line_ending_bytes("lf"), b"\n")
        self.assertEqual(line_ending_bytes("cr"), b"\r")
        self.assertEqual(line_ending_bytes("crlf"), b"\r\n")

    def test_session_logger_records_direction_and_payload(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as directory:
            logger = SessionLogger(Path(directory) / "session.log", clock=lambda: "2026-08-27T10:00:00")
            logger.write("TX", b"status\n")
            logger.write("RX", "ready\r\n".encode())
            logger.close()

            self.assertEqual(
                (Path(directory) / "session.log").read_text(),
                "2026-08-27T10:00:00 TX status\\n\n"
                "2026-08-27T10:00:00 RX ready\\r\\n\n",
            )

    def test_session_log_path_uses_requested_directory(self):
        from pathlib import Path

        path = session_log_path(Path("/tmp/usb-logs"), clock=lambda: "2026-08-27T10:00:00")
        self.assertEqual(path, Path("/tmp/usb-logs/2026-08-27T10-00-00.log"))

    def test_session_logger_creates_private_directory_and_log_under_umask_022(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sessions" / "session.log"
            previous_umask = os.umask(0o022)
            try:
                logger = SessionLogger(path, exclusive=True, private_directory=True)
                logger.write("RX", b"secret\n")
                logger.close()
            finally:
                os.umask(previous_umask)

            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_session_logger_rejects_symlink_log_path(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.txt"
            target.write_text("unchanged\n")
            path = root / "session.log"
            path.symlink_to(target)

            with self.assertRaises(OSError):
                SessionLogger(path, exclusive=False)

            self.assertEqual(target.read_text(), "unchanged\n")

    def test_session_logger_tightens_existing_private_directory(self):
        with TemporaryDirectory() as directory:
            sessions = Path(directory) / "sessions"
            sessions.mkdir()
            sessions.chmod(0o755)
            path = sessions / "session.log"

            logger = SessionLogger(path, exclusive=True, private_directory=True)
            logger.close()

            self.assertEqual(stat.S_IMODE(sessions.stat().st_mode), 0o700)

    def test_exclusive_session_logger_does_not_reuse_existing_log(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "session.log"
            path.write_text("existing\n")

            with self.assertRaises(FileExistsError):
                SessionLogger(path, exclusive=True)

            self.assertEqual(path.read_text(), "existing\n")

    def test_session_logger_directory_factory_uses_collision_suffix(self):
        with TemporaryDirectory() as directory:
            sessions = Path(directory) / "sessions"
            sessions.mkdir()
            first = sessions / "2026-08-27T10-00-00.log"
            first.write_text("existing\n")

            logger = SessionLogger.create_in_directory(
                sessions, clock=lambda: "2026-08-27T10:00:00"
            )
            logger.close()

            self.assertTrue((sessions / "2026-08-27T10-00-00-1.log").exists())
            self.assertEqual(first.read_text(), "existing\n")

    def test_session_logger_directory_factory_rejects_symlink_candidate(self):
        with TemporaryDirectory() as directory:
            sessions = Path(directory) / "sessions"
            sessions.mkdir()
            target = Path(directory) / "target.txt"
            target.write_text("unchanged\n")
            candidate = sessions / "2026-08-27T10-00-00.log"
            candidate.symlink_to(target)

            with self.assertRaises(OSError):
                SessionLogger.create_in_directory(
                    sessions, clock=lambda: "2026-08-27T10:00:00"
                )

            self.assertEqual(target.read_text(), "unchanged\n")
            self.assertFalse((sessions / "2026-08-27T10-00-00-1.log").exists())

    def test_monitor_log_directory_uses_private_session_log(self):
        with TemporaryDirectory() as directory:
            sessions = Path(directory) / "sessions"
            with patch("serial_monitor.sys.stderr"):
                result = monitor(
                    "/dev/usb-plugin-test-device-that-does-not-exist",
                    115200,
                    reconnect=False,
                    log_dir=sessions,
                )

            self.assertEqual(result, 2)
            logs = list(sessions.glob("*.log"))
            self.assertEqual(len(logs), 1)
            self.assertEqual(stat.S_IMODE(sessions.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(logs[0].stat().st_mode), 0o600)

    @patch("serial_monitor.termios.tcflush")
    @patch("serial_monitor.termios.tcsetattr")
    @patch("serial_monitor.termios.tcgetattr")
    def test_configure_disables_dtr_and_rts(self, tcgetattr, tcsetattr, tcflush):
        tcgetattr.return_value = [0, 0, 0, 0, 0, 0, [0] * 32]

        with patch.object(fcntl, "ioctl") as ioctl:
            configure(7, 115200)

        ioctl.assert_called_once_with(
            7,
            termios.TIOCMBIC,
            struct.pack("I", termios.TIOCM_DTR | termios.TIOCM_RTS),
        )


if __name__ == "__main__":
    unittest.main()
