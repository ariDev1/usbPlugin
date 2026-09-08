# ESP32 Read-Only Clone Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fail-closed, read-only ESP32 raw-flash clone foundation to USB Boards on Omarchy, including active hardware evidence, compatibility policy, deterministic SOURCE readback, and an adaptive four-board UI, while keeping every TARGET flash write disabled.

**Architecture:** Keep `usb_boards.py` as the passive USB discovery and identity authority. Add three focused Python components: `clone_probe.py` for explicit read-only Espressif interrogation, `clone_policy.py` for pure compatibility decisions, and `usb_clone.py` for identity resolution, private temporary image handling, complete SOURCE flash reads, hashing, and cleanup. `Panel.qml` only launches the backend and displays evidence; it contains no `esptool` command construction or flash policy.

**Tech Stack:** Omarchy / Arch Linux, Python 3.12 standard library, QML / Quickshell, `esptool` / `espefuse` 5.3.1 or compatible tested CLI, Node 22 for existing profile tests, Python `unittest`.

**Spec:** `docs/2026-09-08-raw-flash-clone-design.md`

## Global Constraints

- Work only on `development`.
- Do not modify `master`.
- Preserve USB Boards v0.4.0 behavior unless this plan explicitly adds isolated clone behavior.
- Preserve `ProfileStore.js` schema version 1 and all migration behavior.
- Preserve `serial_monitor.py` behavior and private RX/TX session logging.
- Preserve existing passive USB detection, physical identity, and connection-path semantics.
- Generic CH340, CP210x, FTDI, PL2303, and similar bridge evidence must never become board proof.
- `/dev/ttyUSBx`, `/dev/ttyACMx`, and `/dev/serial/by-id/...` remain connection paths, not physical identity evidence.
- Active Espressif probing is a separate evidence layer and must not rewrite existing scanner identity fields.
- Active probe actions are explicit operator actions because the Espressif bootloader interaction resets the connected MCU.
- Omarchy / Arch Linux is the only supported operating environment for this implementation.
- External flashing commands must not be constructed in `Panel.qml`.
- The first validated read profile is limited to ESP32-D0WD-V3 revision v3.1, 4 MiB flash, JEDEC `68:4016`, flash encryption disabled, secure boot disabled, UART download enabled.
- Other silicon revisions, flash combinations, and Espressif families remain fail-closed.
- TARGET erase and TARGET write are not implemented in this plan.
- No command containing `write-flash`, `erase-flash`, `erase-region`, eFuse burn, or `--force` may be added to production clone code in this plan.
- Raw flash images use `${XDG_RUNTIME_DIR}/omarchy/usb-boards/clone/<transaction-id>/`, directory mode `0700`, file mode `0600`.
- If `XDG_RUNTIME_DIR` is absent or cannot be secured, raw read fails closed.
- Operation-local continuity evidence is `sysPath + devnum`; it is transaction evidence only and never enters `ProfileStore.js`.
- CI and runtime acceptance must remain green after each meaningful stage.
- Do not change `manifest.json` version in this implementation plan.
- Do not update `README.md` until the read-only feature has passed field acceptance.
- Do not claim TARGET cloning or CLONE PASS until a second physical ESP32 has passed destructive write and independent readback acceptance.

---

## File Structure

### Create

- `clone_probe.py`
  - Read-only Espressif hardware interrogation.
  - Parse `esptool chip-id`, `esptool flash-id`, and JSON eFuse summary.
  - Return normalized active clone evidence.
  - Never read a full flash image and never write flash.

- `clone_policy.py`
  - Pure policy.
  - No subprocess, filesystem, QML, or hardware access.
  - Decide whether a SOURCE is eligible for raw read.
  - Decide whether two synthetic/current devices are hardware-compatible for a future clone.
  - Keep future TARGET write capability separate from compatibility.

- `usb_clone.py`
  - Resolve a current scanner device by `identityKey`.
  - Read operation-local `sysPath + devnum`.
  - Create private runtime transaction storage.
  - Perform complete SOURCE flash read only.
  - Verify exact size.
  - Calculate SHA-256.
  - Revalidate SOURCE continuity.
  - Remove raw image before normal completion.
  - Provide JSON CLI output for QML.

- `test_clone_probe.py`
  - Deterministic parser, command, failure, and security-evidence tests.

- `test_clone_policy.py`
  - Fail-closed SOURCE and pair compatibility tests.

- `test_usb_clone.py`
  - Identity resolution, private file handling, SOURCE-read transaction, cleanup, and forbidden-command tests.

- `test_clone_ui.py`
  - Static QML contract tests for adaptive layout and backend/UI separation.

### Modify

- `Panel.qml`
  - Add clone backend path.
  - Add explicit SOURCE/TARGET selection.
  - Add explicit active probe action.
  - Add read-only SOURCE action.
  - Add adaptive wide mode and two-column board layout.
  - Add clone evidence section.
  - Do not add flash command strings.

- `.github/workflows/ci.yml`
  - Compile the three new Python modules and new Python test modules.

- `docs/USB_IDENTITY_MODEL.md`
  - Add a short section stating that active clone evidence is separate from passive USB identification and does not rewrite identity.

### Intentionally Unchanged

- `ProfileStore.js`
- `test_profile_store.js`
- `serial_monitor.py`
- `install.sh`
- `manifest.json`
- `tools/usb_boards_acceptance.py`
- `master`

---

### Task 1: Freeze the Baseline and Add Read-Only Probe Parsing

**Files:**
- Create: `clone_probe.py`
- Create: `test_clone_probe.py`
- Do not modify existing production files.

**Interfaces:**
- Consumes: serial connection path supplied by `usb_clone.py` later.
- Produces:
  - `ProbeError(RuntimeError)`
  - `run_esp32_probe(port: str, runner=subprocess.run) -> dict[str, object]`
  - `parse_chip_id(text: str) -> dict[str, object]`
  - `parse_flash_id(text: str) -> dict[str, object]`
  - `parse_efuse_json(text: str) -> dict[str, object]`
  - normalized probe dictionary with keys `ok`, `cloneFamily`, `socFamily`, `chipModel`, `chipRevision`, `chipMac`, `crystalMHz`, `flashManufacturer`, `flashDevice`, `flashSize`, `flashVoltage`, `flashEncryption`, `secureBootV1`, `secureBootV2`, `uartDownloadEnabled`, `rdDis`, `wrDis`, `rawReadSupported`, `rawWriteCandidate`, `toolVersion`, `error`.

- [ ] **Step 1: Verify the protected baseline before new code exists**

Run:

```bash
git status -sb
git branch --show-current
git log -2 --oneline
node test_profile_store.js
python3 -m unittest -v
python3 -m py_compile usb_boards.py serial_monitor.py \
  tools/usb_boards_acceptance.py \
  test_usb_boards.py test_acceptance.py test_identity_evidence.py
bash -n install.sh
omarchy plugin validate .
python3 tools/usb_boards_acceptance.py
```

Expected:

- branch is `development`
- design commit `b9761d9` is present
- all existing gates PASS

If any existing gate fails, stop this task and explain the baseline failure before adding clone code.

- [ ] **Step 2: Write failing parser tests using the measured hardware evidence**

Create `test_clone_probe.py` with measured fixtures:

```python
import json
import unittest

from clone_probe import parse_chip_id, parse_efuse_json, parse_flash_id


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
    "MAC": {"value": "68:09:47:9e:3c:88 (CRC 0x05 OK)", "readable": True, "writeable": True},
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
```

- [ ] **Step 3: Run the parser tests and verify they fail**

```bash
python3 -m unittest -v test_clone_probe.py
```

Expected: FAIL because `clone_probe` does not exist.

- [ ] **Step 4: Add the minimum parser implementation**

Implement strict parsing and fail closed if any required field is missing:

```python
#!/usr/bin/env python3
"""Read-only active hardware evidence for supported clone families."""

from __future__ import annotations

import json
import re
import subprocess


class ProbeError(RuntimeError):
    """Raised when active clone evidence cannot be proven."""


def _required_match(pattern: str, text: str, label: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise ProbeError(f"missing-{label}")
    return match.group(1).strip()


def parse_chip_id(text: str) -> dict[str, object]:
    model = _required_match(r"^Chip type:\s+(.+?)\s+\(revision ", text, "chip-model")
    revision = _required_match(r"\(revision\s+([^)]+)\)", text, "chip-revision")
    mac = _required_match(r"^MAC:\s+([0-9a-fA-F:]{17})\s*$", text, "chip-mac").lower()
    crystal = int(_required_match(r"^Crystal frequency:\s+(\d+)MHz\s*$", text, "crystal"))
    return {
        "socFamily": "ESP32",
        "chipModel": model,
        "chipRevision": revision,
        "chipMac": mac,
        "crystalMHz": crystal,
    }


def parse_flash_id(text: str) -> dict[str, object]:
    manufacturer = _required_match(r"^Manufacturer:\s+([0-9a-fA-F]+)\s*$", text, "flash-manufacturer").lower()
    device = _required_match(r"^Device:\s+([0-9a-fA-F]+)\s*$", text, "flash-device").lower()
    size_mb = int(_required_match(r"^Detected flash size:\s+(\d+)MB\s*$", text, "flash-size"))
    voltage = _required_match(r"^Flash voltage.*:\s+([0-9.]+V)\s*$", text, "flash-voltage")
    return {
        "flashManufacturer": manufacturer,
        "flashDevice": device,
        "flashSize": size_mb * 1024 * 1024,
        "flashVoltage": voltage,
    }


def _efuse_value(data: dict[str, object], name: str) -> object:
    field = data.get(name)
    if not isinstance(field, dict) or field.get("readable") is not True or "value" not in field:
        raise ProbeError(f"missing-efuse-{name.lower()}")
    return field["value"]


def parse_efuse_json(text: str) -> dict[str, object]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ProbeError("invalid-efuse-json") from error
    if not isinstance(data, dict):
        raise ProbeError("invalid-efuse-json")
    crypt_count = int(_efuse_value(data, "FLASH_CRYPT_CNT"))
    return {
        "flashEncryption": crypt_count.bit_count() % 2 == 1,
        "secureBootV1": bool(_efuse_value(data, "ABS_DONE_0")),
        "secureBootV2": bool(_efuse_value(data, "ABS_DONE_1")),
        "uartDownloadEnabled": not bool(_efuse_value(data, "UART_DOWNLOAD_DIS")),
        "rdDis": int(_efuse_value(data, "RD_DIS")),
        "wrDis": int(_efuse_value(data, "WR_DIS")),
    }
```

- [ ] **Step 5: Run parser tests**

```bash
python3 -m unittest -v test_clone_probe.py
```

Expected: PASS for parser tests.

- [ ] **Step 6: Add command-contract tests**

Use a fake runner and assert only these hardware commands are used:

```text
esptool -p <port> chip-id
esptool -p <port> flash-id
espefuse -p <port> summary --format json
```

The JSON eFuse summary is preferred over parsing the human-readable table because Espressif documents `--format json` for ESP32.

Assert no command contains:

```text
write-flash
erase-flash
erase-region
burn
--force
```

- [ ] **Step 7: Implement `run_esp32_probe()`**

Use a checked runner:

```python
def _run_checked(runner, args: list[str], timeout: float = 20.0) -> str:
    try:
        result = runner(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ProbeError("probe-command-failed") from error
    if result.returncode != 0:
        raise ProbeError("probe-command-failed")
    return str(result.stdout or "")
```

The public function catches `ProbeError` and returns a failure dictionary instead of leaking a partial probe.

Success includes:

```python
{
    "ok": True,
    "cloneFamily": "esp32-classic-spi-flash",
    "rawReadSupported": True,
    "rawWriteCandidate": False,
    "error": "",
}
```

`rawWriteCandidate` stays `False` for this entire implementation plan.

- [ ] **Step 8: Add fail-closed probe tests**

Test:

- `esptool` missing
- `espefuse` missing
- command timeout
- nonzero command exit
- malformed chip output
- malformed flash output
- invalid eFuse JSON
- missing required eFuse
- unreadable required eFuse

- [ ] **Step 9: Run Task 1 tests**

```bash
python3 -m unittest -v test_clone_probe.py
python3 -m py_compile clone_probe.py test_clone_probe.py
```

Expected: PASS.

- [ ] **Step 10: Commit Task 1**

```bash
git add clone_probe.py test_clone_probe.py
git commit -m "Add read-only ESP32 clone probe"
```

---

### Task 2: Add Pure Fail-Closed Clone Policy

**Files:**
- Create: `clone_policy.py`
- Create: `test_clone_policy.py`

**Interfaces:**
- Consumes scanner dictionaries and normalized probe dictionaries.
- Produces:
  - `CloneDecision`
  - `evaluate_source(device, probe)`
  - `evaluate_pair(source_device, target_device, source_probe, target_probe)`

Use:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class CloneDecision:
    allowed: bool
    state: str
    reason: str
    clone_family: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "state": self.state,
            "reason": self.reason,
            "cloneFamily": self.clone_family,
        }
```

- [ ] **Step 1: Write failing SOURCE policy tests**

Use one exact validated read profile:

```python
VALIDATED_READ_PROFILES = {
    (
        "ESP32-D0WD-V3",
        "v3.1",
        4194304,
        "68",
        "4016",
    ): "esp32-classic-spi-flash",
}
```

Test success and these failures:

- disconnected
- missing identity
- no serial interface
- missing read/write permission
- lock reported
- probe failed
- flash encryption enabled
- secure boot V1 enabled
- secure boot V2 enabled
- UART download disabled
- raw read unsupported
- unsupported chip
- unsupported revision
- unsupported flash size
- unsupported JEDEC combination

- [ ] **Step 2: Run and verify failure**

```bash
python3 -m unittest -v test_clone_policy.py
```

Expected: FAIL because `clone_policy` does not exist.

- [ ] **Step 3: Implement `evaluate_source()`**

Evaluate in deterministic order and return the first machine-readable failure reason.

A validated source returns:

```python
CloneDecision(
    allowed=True,
    state="ready",
    reason="",
    clone_family="esp32-classic-spi-flash",
)
```

- [ ] **Step 4: Write pair compatibility tests**

Test:

- equal `identityKey` -> `same-device`
- equal non-empty eFuse MAC -> `same-device`
- missing MAC -> `identity-insufficient`
- different clone family -> `incompatible`
- different chip model -> `incompatible`
- different revision -> `incompatible`
- different flash capacity -> `flash-size-mismatch`
- unsupported flash combination -> `unsupported-flash`
- security restriction on either side -> `security-restricted`
- matching validated pair -> compatibility ready

The compatible pair result does **not** enable writing.

- [ ] **Step 5: Implement `evaluate_pair()`**

Call the SOURCE gate for both sides, then compare pair evidence.

Do not use connection paths as compatibility evidence.

- [ ] **Step 6: Run policy tests and side-effect check**

```bash
python3 -m unittest -v test_clone_policy.py
python3 -m py_compile clone_policy.py test_clone_policy.py
grep -nE 'subprocess|open\(|Path\(|esptool|espefuse|write-flash|erase' clone_policy.py
```

Expected:

- tests PASS
- grep returns no output

- [ ] **Step 7: Commit Task 2**

```bash
git add clone_policy.py test_clone_policy.py
git commit -m "Add fail-closed clone compatibility policy"
```

---

### Task 3: Add Read-Only SOURCE Transaction Backend

**Files:**
- Create: `usb_clone.py`
- Create: `test_usb_clone.py`

**Interfaces:**
- Consumes:
  - `usb_boards.scan()`
  - `clone_probe.run_esp32_probe()`
  - `clone_policy.evaluate_source()`
- Produces:
  - `resolve_connected_device(identity_key, devices)`
  - `device_path(device)`
  - `read_connection_token(device)`
  - `read_source(identity_key, scanner=scan, runner=subprocess.run, environ=os.environ)`
  - CLI subcommands `probe` and `read-source`

Use:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectionToken:
    sys_path: str
    devnum: str
```

- [ ] **Step 1: Write failing identity-resolution tests**

Require exact current `identityKey` matching.

Reject:

- missing identity
- duplicate connected identity
- disconnected-only match

Do not accept a `/dev` path as a replacement identity.

- [ ] **Step 2: Implement identity resolution and device path selection**

Use `stablePath` for communication when present, else current `port`.

This selection is communication only.

- [ ] **Step 3: Add continuity-token tests**

Build temporary fake sysfs directories with `devnum`.

Require:

```text
token = exact sysPath + exact devnum
```

Reject missing or unreadable `sysPath/devnum`.

- [ ] **Step 4: Implement continuity token read**

Read `Path(device["sysPath"]) / "devnum"` and fail closed.

Never persist this token into profile data.

- [ ] **Step 5: Add private runtime-directory tests**

Test:

- missing `XDG_RUNTIME_DIR` -> fail
- base clone directory mode `0700`
- transaction directory mode `0700`
- image file mode `0600`
- cleanup after success
- cleanup after read failure

- [ ] **Step 6: Implement private transaction context**

Use:

```text
${XDG_RUNTIME_DIR}/omarchy/usb-boards/clone/read-<random-safe-suffix>/
```

Use `tempfile.mkdtemp()` inside the secured base directory.

Do not fall back to `/tmp`.

- [ ] **Step 7: Add SOURCE read transaction tests with a fake runner**

Simulate the probe and full flash read.

The full read command must be exactly equivalent to:

```bash
esptool -p <current-path> -b 460800 read-flash 0 0x400000 <private-image>
```

Use a sparse 4 MiB test file to avoid slow test allocation.

Assert:

- exact file size `4194304`
- SHA-256 returned
- initial continuity token captured
- SOURCE rescanned after read
- final continuity token equals initial token
- image removed before normal return
- no destructive command string appears anywhere in production clone files

- [ ] **Step 8: Implement `read_source()`**

Required order:

```text
scan
resolve SOURCE identity
capture token A
probe SOURCE
evaluate SOURCE policy
create private transaction directory
read 4 MiB
verify exact size
chmod image 0600
calculate SHA-256
rescan SOURCE
capture token B
require token A == token B
return metadata
remove raw image
```

If SOURCE is disconnected or token changes after the read, return failure even if the image hash was calculated.

- [ ] **Step 9: Add CLI JSON contract tests**

`probe` success example:

```json
{
  "operation": "probe",
  "status": "pass",
  "identityKey": "usb-topology:...",
  "probe": {}
}
```

`read-source` success example:

```json
{
  "operation": "read-source",
  "status": "pass",
  "identityKey": "usb-topology:...",
  "cloneFamily": "esp32-classic-spi-flash",
  "imageSize": 4194304,
  "sha256": "..."
}
```

Failure uses nonzero exit and:

```json
{
  "operation": "read-source",
  "status": "failed",
  "reason": "source-read-failed"
}
```

- [ ] **Step 10: Add destructive-command source guard**

Search `clone_probe.py`, `clone_policy.py`, and `usb_clone.py` in a test and reject:

```text
write-flash
erase-flash
erase-region
--force
burn-key
burn-efuse
```

- [ ] **Step 11: Run backend tests**

```bash
python3 -m unittest -v test_clone_probe.py test_clone_policy.py test_usb_clone.py
python3 -m py_compile clone_probe.py clone_policy.py usb_clone.py \
  test_clone_probe.py test_clone_policy.py test_usb_clone.py
```

Expected: PASS.

- [ ] **Step 12: Commit Task 3**

```bash
git add usb_clone.py test_usb_clone.py
git commit -m "Add private read-only source flash transaction"
```

---

### Task 4: Prove the Backend on the Real ESP32 Before UI Work

**Files:**
- No production file change expected.

**Interfaces:**
- Produces real Omarchy evidence for the implemented read-only backend.

- [ ] **Step 1: Find the current SOURCE by USB Boards identity**

```bash
python3 usb_boards.py --pretty
```

Record the current `identityKey`.

Do not assume it is still `/dev/ttyUSB1`.

- [ ] **Step 2: Run the backend probe**

```bash
python3 usb_clone.py probe --identity-key '<actual identityKey>'
```

Expected active evidence matches the measured supported profile:

```text
ESP32-D0WD-V3
v3.1
4 MiB
68:4016
flash encryption off
secure boot off
UART download enabled
```

- [ ] **Step 3: Run one backend SOURCE read**

```bash
python3 usb_clone.py read-source --identity-key '<actual identityKey>'
```

Required:

- `status = pass`
- `imageSize = 4194304`
- deterministic SHA-256 for current contents

If the board contents have not changed since the audit, the expected hash is:

```text
48d84d45b396ee9d316b78258fe0387760a9ef794b0a976aae389836046b5319
```

A different hash is not automatically a backend failure if the flash contents changed after the audit.

- [ ] **Step 4: Verify raw image cleanup**

```bash
find "${XDG_RUNTIME_DIR}/omarchy/usb-boards/clone" -type f -print 2>/dev/null
```

Expected: no completed raw image remains.

- [ ] **Step 5: Run existing acceptance**

```bash
node test_profile_store.js
python3 -m unittest -v
bash -n install.sh
omarchy plugin validate .
python3 tools/usb_boards_acceptance.py
```

Expected: PASS.

---

### Task 5: Add Adaptive Multi-Board Panel Layout

**Files:**
- Modify: `Panel.qml`
- Create: `test_clone_ui.py`

**Interfaces:**
- Produces `wideMode` and a two-column board grid.

Initial candidate dimensions:

```qml
readonly property int compactPanelWidth: Style.space(380)
readonly property int widePanelWidth: Style.space(760)
readonly property int compactPanelHeight: Style.space(600)
readonly property int widePanelHeight: Style.space(760)
```

Exact final dimensions require real Omarchy field evidence.

- [ ] **Step 1: Write failing layout contract tests**

Require:

```text
readonly property bool wideMode
widePanelWidth
widePanelHeight
id: deviceGrid
columns: root.wideMode ? 2 : 1
ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
```

- [ ] **Step 2: Run and verify failure**

```bash
python3 -m unittest -v test_clone_ui.py
```

Expected: FAIL.

- [ ] **Step 3: Add adaptive panel dimensions**

Wide mode becomes true when:

```text
connected device count >= 2
OR SOURCE selected
OR TARGET selected
```

Keep one-device view compact.

- [ ] **Step 4: Convert the device container to `GridLayout`**

Use one column in compact mode and two columns in wide mode.

Preserve the existing board-card content and actions.

Existing separators are visible only in one-column mode.

Do not add decorative borders.

- [ ] **Step 5: Run UI tests and plugin validation**

```bash
python3 -m unittest -v test_clone_ui.py
python3 -m unittest -v
omarchy plugin validate .
python3 tools/usb_boards_acceptance.py
```

Expected: PASS.

- [ ] **Step 6: Field-check available devices**

Required:

- no horizontal scrolling
- no clipped board actions
- keyboard selection still maps to correct device
- compact one-device layout still works
- two-or-more-device wide layout works
- vertical scroll remains available

If four real boards are available, verify 2x2 usability.

If not, record `FOUR-BOARD FIELD ACCEPTANCE: NOT YET TESTED`.

- [ ] **Step 7: Commit Task 5**

```bash
git add Panel.qml test_clone_ui.py
git commit -m "Add adaptive multi-board panel layout"
```

---

### Task 6: Add Explicit SOURCE/TARGET Selection and Active Probe UI

**Files:**
- Modify: `Panel.qml`
- Modify: `test_clone_ui.py`

**Interfaces:**
- QML state:
  - `cloneSourceKey`
  - `cloneTargetKey`
  - `cloneProbeByIdentity`
  - `cloneProbePendingKey`
  - `cloneError`

- [ ] **Step 1: Write failing QML separation tests**

Require:

- SOURCE/TARGET use identity keys
- no `cloneSourcePath` or `cloneTargetPath`
- explicit `probeCloneDevice()`
- backend command includes `probe --identity-key`
- QML source contains no `esptool`, `espefuse`, `read-flash`, `write-flash`, `erase-flash`

- [ ] **Step 2: Add clone backend path and state**

Resolve `usb_clone.py` through `Qt.resolvedUrl()` like existing scanner and monitor paths.

Do not persist SOURCE/TARGET in profile settings.

- [ ] **Step 3: Add explicit SOURCE/TARGET helpers**

Reject selecting the same `identityKey` for both roles.

Selection alone performs no hardware operation.

- [ ] **Step 4: Add explicit PROBE action**

PROBE is manual.

It launches only:

```text
python3 usb_clone.py probe --identity-key <key>
```

The board reset is expected and should be indicated in the tooltip or status text.

- [ ] **Step 5: Add compact clone evidence section**

Show selected SOURCE/TARGET and active evidence:

- chip model
- revision
- flash size
- JEDEC
- security summary
- eFuse MAC
- compatibility state when both are available

With one board, valid state is:

```text
SOURCE READ READY
TARGET NOT SELECTED
TARGET WRITE LOCKED
```

Never display `CLONE PASS`.

- [ ] **Step 6: Run tests and field probe**

```bash
python3 -m unittest -v test_clone_ui.py
python3 -m unittest -v
omarchy plugin validate .
python3 tools/usb_boards_acceptance.py
```

Then probe the real ESP32 from the panel and confirm passive scanner evidence remains unchanged.

- [ ] **Step 7: Commit Task 6**

```bash
git add Panel.qml test_clone_ui.py
git commit -m "Add explicit clone selection and probe UI"
```

---

### Task 7: Add Read-Only SOURCE Action to the Panel

**Files:**
- Modify: `Panel.qml`
- Modify: `test_clone_ui.py`

**Interfaces:**
- Uses `usb_clone.py read-source --identity-key`.
- Produces running state, exact image size, SHA-256, and explicit failure reason.

- [ ] **Step 1: Write failing read-action UI tests**

Require:

- `read-source`
- `--identity-key`
- visible text `RESETS BOARD`
- no target write handler
- no destructive command string

- [ ] **Step 2: Add read-only process state**

Add:

```qml
property bool cloneReadRunning: false
property var cloneReadResult: ({})
```

Guard against:

- no SOURCE
- no successful SOURCE probe
- probe already running
- read already running

- [ ] **Step 3: Add explicit SOURCE read action**

Label:

```text
READ SOURCE · RESETS BOARD
```

Launch only:

```text
python3 usb_clone.py read-source --identity-key <sourceKey>
```

Show:

- `READING SOURCE`
- final image size
- SHA-256
- failure reason

Do not display temporary image path.

- [ ] **Step 4: Run tests and real read**

```bash
python3 -m unittest -v test_clone_ui.py
python3 -m unittest -v
omarchy plugin validate .
```

Then run one real panel SOURCE read.

Required:

- size `4194304`
- SHA-256 shown
- raw file removed
- serial monitor still works after board reset

- [ ] **Step 5: Commit Task 7**

```bash
git add Panel.qml test_clone_ui.py
git commit -m "Expose read-only source flash evidence"
```

---

### Task 8: Document the Active Evidence Boundary

**Files:**
- Modify: `docs/USB_IDENTITY_MODEL.md`
- Modify: `test_clone_ui.py`
- Do not modify: `README.md`

- [ ] **Step 1: Add concise `## Active Clone Evidence` section**

State:

- passive USB evidence is unchanged
- generic bridges remain bridge-only passive evidence
- explicit active probing can prove supported silicon behind a connection
- active probe evidence does not construct or replace `identityKey`
- active probe evidence is not a profile identity
- `sysPath + devnum` is transaction continuity only
- security fails closed
- TARGET write is not enabled

Do not repeat the complete design document.

- [ ] **Step 2: Add documentation contract test**

Require the section, `bridge-only`, `identityKey`, and `devnum`.

- [ ] **Step 3: Run tests**

```bash
python3 -m unittest -v
```

Expected: PASS.

- [ ] **Step 4: Commit Task 8**

```bash
git add docs/USB_IDENTITY_MODEL.md test_clone_ui.py
git commit -m "Document active clone evidence boundary"
```

---

### Task 9: Extend CI and Run Full Acceptance

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `test_clone_ui.py`

- [ ] **Step 1: Add CI contract test**

Require CI compilation references for:

```text
clone_probe.py
clone_policy.py
usb_clone.py
test_clone_probe.py
test_clone_policy.py
test_usb_clone.py
test_clone_ui.py
```

- [ ] **Step 2: Extend only the existing Python compile command**

Do not change workflow branch triggers.

- [ ] **Step 3: Run the complete local gate**

```bash
node test_profile_store.js

python3 -m unittest -v

python3 -m py_compile \
  usb_boards.py \
  serial_monitor.py \
  clone_probe.py \
  clone_policy.py \
  usb_clone.py \
  tools/usb_boards_acceptance.py \
  test_usb_boards.py \
  test_acceptance.py \
  test_identity_evidence.py \
  test_clone_probe.py \
  test_clone_policy.py \
  test_usb_clone.py \
  test_clone_ui.py

bash -n install.sh
omarchy plugin validate .
python3 tools/usb_boards_acceptance.py
```

Expected: all PASS.

- [ ] **Step 4: Verify protected files are unchanged**

```bash
git diff c88459007d4a736388382c6b14f4a17e97c992a4 -- \
  ProfileStore.js serial_monitor.py install.sh manifest.json tools/usb_boards_acceptance.py
```

Expected: no diff for these protected files.

- [ ] **Step 5: Commit CI update**

```bash
git add .github/workflows/ci.yml test_clone_ui.py
git commit -m "Extend CI for read-only clone foundation"
```

- [ ] **Step 6: Push development only**

```bash
git status -sb
git push origin development
```

Do not push or merge `master`.

- [ ] **Step 7: Verify GitHub CI**

Do not claim CI PASS until the actual development workflow run is green.

---

### Task 10: Final Read-Only Field Acceptance

**Files:**
- No code change unless a proven defect is found.

- [ ] **Step 1: Confirm repository state**

```bash
git status -sb
git branch --show-current
git log -10 --oneline
```

Required:

- `development`
- clean worktree
- synchronized with `origin/development`

- [ ] **Step 2: Reconfirm trusted existing behavior**

Verify:

- USB discovery
- passive identity
- board evidence
- saved profiles
- profile migration behavior
- serial monitor
- private RX/TX logs
- offline profiles
- runtime acceptance

- [ ] **Step 3: Reconfirm real ESP32 active evidence**

Expected supported specimen:

```text
ESP32-D0WD-V3
v3.1
4 MiB
68:4016
flash encryption false
secure boot false
UART download enabled
```

- [ ] **Step 4: Reconfirm real SOURCE full-flash read**

Required:

- explicit operator action
- board reset expected
- exactly 4,194,304 bytes
- SHA-256 reported
- raw image removed
- no target operation
- serial monitor remains usable afterward

- [ ] **Step 5: Reconfirm adaptive panel**

Required:

- one-device compact mode
- multi-device wide mode when hardware is present
- no horizontal scroll
- no clipped actions
- keyboard navigation remains correct

If four boards are available, test 2x2 operation.

If not, record:

```text
FOUR-BOARD FIELD ACCEPTANCE: NOT YET TESTED
```

- [ ] **Step 6: Record the exact implementation boundary**

Final read-only acceptance statement:

```text
ESP32 RAW READ FOUNDATION: PASS
TARGET WRITE: NOT IMPLEMENTED
TARGET VERIFY: NOT IMPLEMENTED
CLONE PASS: NOT CLAIMED
```

---

## Deferred Destructive Plan

A second implementation plan is required after a second physical ESP32 is available.

That future plan begins with:

1. TARGET passive identity capture
2. TARGET active hardware fingerprint
3. SOURCE/TARGET compatibility evidence
4. controlled TARGET backup policy
5. controlled raw TARGET write
6. complete TARGET readback
7. byte-for-byte comparison
8. reconnect and power-cycle acceptance
9. explicit failure-recovery evidence
10. only then, normal `CLONE` action and `CLONE PASS`

No step in this plan authorizes those operations.
