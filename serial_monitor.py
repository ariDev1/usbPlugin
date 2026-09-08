#!/usr/bin/env python3
"""Interactive dependency-free serial monitor."""

from __future__ import annotations

import argparse
from datetime import datetime
import errno
import fcntl
import grp
import os
from pathlib import Path
import select
import stat
import struct
import subprocess
import sys
import termios
import tty


BAUD_RATES = {
    rate: getattr(termios, f"B{rate}")
    for rate in (1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600)
    if hasattr(termios, f"B{rate}")
}

LINE_ENDINGS = {
    "none": b"",
    "lf": b"\n",
    "cr": b"\r",
    "crlf": b"\r\n",
}
DATA_FORMATS = ("8N1", "8N2", "7E1", "7O1")


def parse_data_format(value: str) -> tuple[int, str, int]:
    normalized = value.upper()
    if len(normalized) != 3 or normalized[0] not in "78" or normalized[1] not in "NEO" or normalized[2] not in "12":
        raise ValueError(f"unsupported serial format: {value}")
    bits, parity, stop_bits = int(normalized[0]), normalized[1], int(normalized[2])
    if bits == 7 and parity == "N":
        raise ValueError(f"unsupported serial format: {value}")
    return bits, parity, stop_bits


def session_log_path(directory: Path, clock=None) -> Path:
    stamp = (clock or (lambda: datetime.now().isoformat(timespec="seconds")))()
    return directory / f"{stamp.replace(':', '-').replace(' ', '_')}.log"


def line_ending_bytes(name: str) -> bytes:
    try:
        return LINE_ENDINGS[name]
    except KeyError as error:
        raise ValueError(f"unknown line ending: {name}") from error


def ensure_private_directory(directory: Path) -> None:
    """Create or tighten a log directory so only its owner can access it."""

    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(directory, flags)
    try:
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise NotADirectoryError(str(directory))
        os.fchmod(fd, 0o700)
    finally:
        os.close(fd)


def open_log_file(path: Path, *, exclusive: bool) -> object:
    """Open a regular log file without following a final-component symlink."""

    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW
    if exclusive:
        flags |= os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, f"log path is not a regular file: {path}")
        os.fchmod(fd, 0o600)
        stream = os.fdopen(fd, "a", encoding="utf-8")
        fd = -1
        return stream
    finally:
        if fd >= 0:
            os.close(fd)


class SessionLogger:
    """Append human-readable serial traffic to a private session log."""

    def __init__(self, path: Path, clock=None, *, exclusive: bool = False,
                 private_directory: bool = False) -> None:
        if private_directory:
            ensure_private_directory(path.parent)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open_log_file(path, exclusive=exclusive)
        self._clock = clock or (lambda: datetime.now().isoformat(timespec="seconds"))

    @classmethod
    def create_in_directory(cls, directory: Path, clock=None) -> "SessionLogger":
        ensure_private_directory(directory)
        base = session_log_path(directory, clock=clock)
        for suffix in range(1000):
            path = base if suffix == 0 else base.with_name(f"{base.stem}-{suffix}{base.suffix}")
            try:
                return cls(path, clock=clock, exclusive=True)
            except FileExistsError:
                try:
                    existing_mode = path.lstat().st_mode
                except FileNotFoundError:
                    continue
                if stat.S_ISLNK(existing_mode):
                    raise OSError(errno.ELOOP, f"refusing symlink log path: {path}")
                continue
        raise FileExistsError(errno.EEXIST, "could not allocate a unique session log", str(base))

    def write(self, direction: str, data: bytes) -> None:
        text = data.decode("utf-8", errors="replace")
        escaped = text.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n")
        self._file.write(f"{self._clock()} {direction} {escaped}\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


def configure(fd: int, baud: int, data_format: str = "8N1") -> None:
    bits, parity, stop_bits = parse_data_format(data_format)
    attributes = termios.tcgetattr(fd)
    attributes[0] = termios.IGNPAR
    attributes[1] = 0
    attributes[2] &= ~(termios.CSIZE | termios.PARENB | termios.PARODD | termios.CSTOPB)
    attributes[2] |= (termios.CS7 if bits == 7 else termios.CS8) | termios.CREAD | termios.CLOCAL
    if parity == "E":
        attributes[2] |= termios.PARENB
    elif parity == "O":
        attributes[2] |= termios.PARENB | termios.PARODD
    if stop_bits == 2:
        attributes[2] |= termios.CSTOPB
    attributes[3] = 0
    attributes[4] = BAUD_RATES[baud]
    attributes[5] = BAUD_RATES[baud]
    attributes[6][termios.VMIN] = 0
    attributes[6][termios.VTIME] = 1
    termios.tcsetattr(fd, termios.TCSANOW, attributes)
    fcntl.ioctl(
        fd,
        termios.TIOCMBIC,
        struct.pack("I", termios.TIOCM_DTR | termios.TIOCM_RTS),
    )
    termios.tcflush(fd, termios.TCIFLUSH)


def monitor(port: str, baud: int, line_ending: str = "lf", log_path: Path | None = None,
            reconnect: bool = True, data_format: str = "8N1",
            log_dir: Path | None = None) -> int:
    ending = line_ending_bytes(line_ending)
    logger = (
        SessionLogger.create_in_directory(log_dir)
        if log_dir
        else (SessionLogger(log_path) if log_path else None)
    )
    fd = None
    old_terminal = None
    permission_denied = False

    def close_port() -> None:
        nonlocal fd
        if fd is not None:
            os.close(fd)
            fd = None

    def open_port() -> bool:
        nonlocal fd, permission_denied
        permission_denied = False
        try:
            fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            configure(fd, baud, data_format)
            return True
        except PermissionError:
            permission_denied = True
            print(f"Permission denied: {port}", file=sys.stderr)
            close_port()
            return False
        except OSError as error:
            print(f"Could not open {port}: {error.strerror}", file=sys.stderr)
            close_port()
            return False

    def offer_access_help() -> int:
        try:
            group = grp.getgrgid(os.stat(port).st_gid).gr_name
        except (KeyError, OSError):
            group = "uucp"
        user = os.environ.get("USER", "")
        if sys.stdin.isatty() and user:
            answer = input(f"Grant {user} serial access through the {group} group now? [Y/n] ").strip().lower()
            if answer in {"", "y", "yes"}:
                result = subprocess.run(["sudo", "usermod", "-aG", group, user], check=False)
                if result.returncode == 0:
                    print("Access granted. Log out and back in, then reconnect the board.")
                    return 0
        print(f"Run: sudo usermod -aG {group} {user or '$USER'}", file=sys.stderr)
        print("Then log out and back in.", file=sys.stderr)
        return 2
    try:
        if not open_port():
            return offer_access_help() if permission_denied else 2
        if sys.stdin.isatty():
            old_terminal = termios.tcgetattr(sys.stdin.fileno())
            tty.setraw(sys.stdin.fileno())

        sys.stdout.write(f"Connected to {port} at {baud} baud\r\n")
        sys.stdout.write(f"Format: {data_format}, line ending: {line_ending}. Press Ctrl+] to close.\r\n\r\n")
        sys.stdout.flush()

        while True:
            inputs = [fd]
            if sys.stdin.isatty():
                inputs.append(sys.stdin.fileno())
            readable, _, _ = select.select(inputs, [], [])
            if fd in readable:
                try:
                    data = os.read(fd, 4096)
                except BlockingIOError:
                    data = b""
                except OSError as error:
                    if error.errno in (errno.EIO, errno.ENODEV):
                        sys.stdout.write("\r\nDevice disconnected.\r\n")
                        sys.stdout.flush()
                        close_port()
                        if not reconnect:
                            return 0
                        while fd is None:
                            if sys.stdin.isatty():
                                readable, _, _ = select.select([sys.stdin.fileno()], [], [], 1.0)
                                if readable and b"\x1d" in os.read(sys.stdin.fileno(), 1024):
                                    return 130
                            else:
                                select.select([], [], [], 1.0)
                            if open_port():
                                sys.stdout.write(f"\r\nReconnected to {port}.\r\n")
                                sys.stdout.flush()
                        continue
                    raise
                if data:
                    if logger:
                        logger.write("RX", data)
                    os.write(sys.stdout.fileno(), data)

            if sys.stdin.isatty() and sys.stdin.fileno() in readable:
                data = os.read(sys.stdin.fileno(), 1024)
                if b"\x1d" in data:
                    return 130
                if data:
                    if ending and (data.endswith(b"\n") or data.endswith(b"\r")):
                        data = data.rstrip(b"\r\n") + ending
                    if logger:
                        logger.write("TX", data)
                    os.write(fd, data)
    except (OSError, termios.error) as error:
        print(f"\r\nSerial monitor stopped: {error}", file=sys.stderr)
        return 1
    finally:
        if old_terminal is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_terminal)
        close_port()
        if logger:
            logger.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", type=Path, help="serial device path")
    parser.add_argument("--baud", type=int, default=115200, choices=sorted(BAUD_RATES))
    parser.add_argument("--line-ending", choices=sorted(LINE_ENDINGS), default="lf")
    parser.add_argument("--format", choices=DATA_FORMATS, default="8N1", dest="data_format")
    parser.add_argument("--log", type=Path, help="append RX/TX traffic to this log file")
    parser.add_argument("--log-dir", type=Path, help="write a timestamped RX/TX log in this directory")
    parser.add_argument("--no-reconnect", action="store_true", help="exit when the device disconnects")
    args = parser.parse_args()
    log_dir = None if args.log else args.log_dir
    return monitor(
        str(args.port),
        args.baud,
        args.line_ending,
        args.log,
        not args.no_reconnect,
        args.data_format,
        log_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
