import unittest
import fcntl
from pathlib import Path
import struct
import termios
from tempfile import TemporaryDirectory
from unittest.mock import patch

from usb_boards import device_access, identify_board, infer_mode, is_board_candidate, lock_info, scan
from serial_monitor import SessionLogger, configure, line_ending_bytes, parse_data_format, session_log_path


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

    def test_bootloader_without_tty_is_reported(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_usb(root, "2-1", "2e8a", "0003", "Raspberry Pi", "RP2 Boot")

            devices = self.fixture_scan(root)

            self.assertEqual(len(devices), 1)
            self.assertEqual(devices[0]["board"], "Raspberry Pi RP2 Bootloader")
            self.assertEqual(devices[0]["mode"], "bootloader")
            self.assertFalse(devices[0]["serialAvailable"])

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

    def test_unrelated_usb_device_without_tty_is_ignored(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_usb(root, "4-1", "046d", "c534", "Logitech", "USB Receiver")
            self.assertEqual(self.fixture_scan(root), [])


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
