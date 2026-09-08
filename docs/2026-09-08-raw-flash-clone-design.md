# USB Boards Raw Flash Clone Design

Date: 2026-09-08

Repository: `ariDev1/usbPlugin`

Development branch baseline before this design: `c88459007d4a736388382c6b14f4a17e97c992a4`

Release baseline: USB Boards v0.4.0

## 1. Purpose

This document defines the first clone architecture for USB Boards for Omarchy.

The first clone feature is a raw memory clone feature. It is not an Arduino sketch copy function. It is not an IDE deployment function. It is not a project-file copy function.

The first supported direction is a byte-for-byte clone of the complete external SPI flash of a supported classic ESP32 device.

The feature runs only on Omarchy / Arch Linux. Omarchy is the user interface and integration environment.

This design does not authorize a target write yet. Target write acceptance needs a second physical ESP32 and destructive hardware validation.

## 2. Protected Baseline

The following behavior is protected and must remain unchanged unless later evidence proves that a change is required:

- USB discovery behavior
- board identification evidence
- physical identity behavior
- connection-path behavior
- profile schema version 1
- profile migration behavior
- serial monitor behavior
- private RX/TX session logging
- runtime acceptance behavior
- generic USB bridge policy

`master` must remain unchanged while Omarchy Marketplace verification issue #5759 is pending.

Development work is permitted only on `development`.

## 3. Existing Architecture

USB Boards already separates three concepts:

1. Detection
2. Identity
3. Connection

The clone subsystem must keep this separation.

Current responsibilities are:

- `usb_boards.py`: passive USB discovery, board evidence, identity evidence, connection information
- `ProfileStore.js`: profile persistence and migration policy
- `serial_monitor.py`: serial RX/TX and private session logging
- `Panel.qml`: operator interface and process launch
- `tools/usb_boards_acceptance.py`: deterministic runtime acceptance

The clone feature must consume this evidence. It must not redefine it.

## 4. Clone Definition

For the first supported family, clone means:

> Read the complete external SPI flash from SOURCE, write the same byte sequence to TARGET, read the complete external SPI flash from TARGET, and require byte-for-byte equality before reporting PASS.

For the current proven ESP32 specimen, the complete external flash size is 4 MiB, or 4,194,304 bytes.

The clone payload includes every byte in the external SPI flash address range that is read by the supported raw flash operation.

This can include:

- bootloader image
- partition table
- application images
- OTA slots
- NVS
- filesystem data
- configuration data
- other data stored in external SPI flash

The clone operation does not interpret these regions during the raw copy.

## 5. Explicit Non-Clone Data

The first clone implementation must not copy or modify:

- mask ROM
- eFuses
- OTP values
- hardware MAC address
- flash-encryption keys
- secure-boot keys
- JTAG eFuse state
- chip calibration eFuses
- USB Boards profiles
- USB Boards nicknames
- serial-monitor settings
- host connection paths

The clone backend must never burn eFuses as part of a normal clone transaction.

## 6. Proven Hardware Evidence

The initial hardware audit used Omarchy / Arch Linux and `esptool` / `espefuse` version 5.3.1.

The tested SOURCE produced this active hardware evidence:

- SoC: ESP32-D0WD-V3
- silicon revision: v3.1
- crystal: 40 MHz
- physical-chip MAC: `68:09:47:9e:3c:88`
- flash manufacturer ID: `0x68`
- flash device ID: `0x4016`
- detected flash size: 4 MiB
- flash voltage: 3.3 V
- flash encryption: disabled
- secure boot V1: disabled
- secure boot V2: disabled
- UART download mode: enabled
- eFuse read-disable mask: zero
- eFuse write-disable mask: zero

Three full-flash reads were performed from address `0x00000000` for `0x400000` bytes.

Two reads used the faster transport path. One read used 115200 baud.

All reads produced the same 4,194,304-byte image.

The measured SHA-256 value was:

`48d84d45b396ee9d316b78258fe0387760a9ef794b0a976aae389836046b5319`

Byte comparison passed.

This is evidence that full external SPI flash readback is deterministic on the tested specimen and is independent of the two tested serial transport rates.

This evidence proves the read side only. It does not prove target write or target verification.

## 7. Evidence Layers

The clone architecture uses two separate evidence layers.

### 7.1 Passive USB Evidence

Passive USB evidence is produced by the existing scanner.

Examples are:

- VID/PID
- USB descriptors
- reported USB serial
- USB topology
- bridge classification
- current serial connection path

This evidence remains authoritative for the existing USB Boards identity and profile architecture.

A generic USB bridge does not prove which board or MCU is behind it.

For example, CH340 evidence remains bridge-only evidence in normal USB discovery.

### 7.2 Active Clone Evidence

Active clone evidence is produced by direct protocol interrogation through the current connection.

For the first family, the backend communicates with the Espressif ROM bootloader and related read-only tools.

Active clone evidence can include:

- clone family
- SoC family
- exact detected chip model
- silicon revision
- physical-chip MAC
- flash manufacturer ID
- flash device ID
- flash capacity
- flash voltage information
- flash-encryption state
- secure-boot state
- UART-download availability
- raw-read capability
- raw-write capability

Active clone evidence may prove that an ESP32 exists behind a generic serial bridge.

It must not rewrite the passive USB identification fields.

## 8. First Clone Family

The first clone-family identifier is conceptually:

`esp32-classic-spi-flash`

Initial implementation support is fail-closed.

The first hardware class with real read evidence is classic ESP32 with ESP32-D0WD-V3 silicon revision v3.1.

The initial validated read profile is therefore limited to the measured combination:

- chip model: ESP32-D0WD-V3
- silicon revision: v3.1
- flash size: 4 MiB
- flash JEDEC: `0x68:0x4016`
- flash encryption: disabled
- secure boot: disabled
- UART download: enabled

Other revisions, flash combinations, and Espressif families remain unsupported for destructive cloning until separate hardware evidence exists.

Examples that remain outside the first proven scope include:

- ESP32-S2
- ESP32-S3
- ESP32-C3
- other later Espressif families

The architecture can add them later without changing the existing USB identity model.

## 9. Proposed Components

The smallest architecture adds three Python components.

### 9.1 `clone_probe.py`

Responsibility:

- perform active, read-only hardware interrogation
- normalize the result into deterministic clone evidence
- report explicit probe failures

It must not write flash.

It must not modify eFuses.

It must not contain UI code.

### 9.2 `clone_policy.py`

Responsibility:

- make pure compatibility decisions from scanner evidence and active probe evidence
- fail closed when evidence is missing or unsupported
- return a machine-readable reason

It must not call subprocesses.

It must not access hardware.

It must not contain QML behavior.

### 9.3 `usb_clone.py`

Responsibility:

- control the clone transaction
- resolve SOURCE and TARGET from current scanner evidence
- revalidate evidence before destructive stages
- read SOURCE
- hash SOURCE
- write TARGET when hardware write acceptance is later approved
- read TARGET back
- compare bytes and hashes
- produce deterministic operation results

The target write path must remain disabled until destructive hardware acceptance exists.

## 10. No Programmer Framework Yet

The first implementation must not add a generic programmer-adapter framework.

There is only one proven clone family at this stage.

The ESP32-specific backend can use small focused functions around the external tool.

A shared adapter interface becomes justified only when a second substantially different hardware family is proven.

This avoids unnecessary abstraction.

## 11. External Tool Boundary

For the first clone family, the external hardware transport is `esptool` / `espefuse` on Omarchy / Arch Linux.

The plugin must not use Arduino IDE, PlatformIO, Windows tools, macOS tools, or a cross-platform compatibility layer.

The backend must detect required tools and versions through deterministic command execution.

Missing tools must produce an explicit unsupported or dependency failure state.

The UI must not construct `esptool` command strings.

## 12. SOURCE and TARGET Rules

The operator selects SOURCE and TARGET explicitly.

The software must never select TARGET because it is the second `/dev` path.

SOURCE and TARGET must never be accepted as the same physical device.

The clone policy must require separate current device observations.

Physical-chip evidence must also distinguish the two supported ESP32 devices when available.

For classic ESP32, the eFuse MAC is useful operation evidence that the two chips differ.

The MAC is not a compatibility property.

Different MAC values are expected.

## 13. Compatibility Gate

The first compatibility gate must require all applicable conditions below:

- SOURCE is connected
- TARGET is connected
- SOURCE and TARGET are distinct current identities
- SOURCE active probe passes
- TARGET active probe passes
- SOURCE and TARGET use the same supported clone family
- SOURCE and TARGET use the same supported SoC class
- SOURCE and TARGET have the same flash capacity
- flash encryption is disabled on both
- secure boot is disabled on both
- UART download is available on both
- SOURCE raw read is supported
- TARGET raw write is supported when the write path is enabled
- physical-chip evidence does not indicate the same chip
- no required evidence is missing

Any failed condition blocks cloning.

## 14. Flash Compatibility

Flash capacity is a required compatibility property for the first raw clone.

The initial reference device uses a 4 MiB flash.

Flash JEDEC manufacturer and device IDs are recorded as active evidence.

The first implementation must not assume that any different flash part is compatible only because its capacity matches.

The safe first policy is a validated hardware combination table.

A new flash combination can be added only after evidence proves that the raw write and readback behavior is correct.

This policy can later be relaxed if testing proves that a broader rule is safe.

## 15. Security Gate

The first clone implementation must fail closed when security state prevents a scientifically valid raw clone.

Initial unsupported conditions include:

- flash encryption enabled
- secure boot enabled
- UART download disabled
- required read operation blocked
- required write operation blocked
- required security state cannot be determined

The software must not bypass these states with force options.

The software must not alter eFuses to make a board cloneable.

## 16. Connection Revalidation

A destructive operation needs stronger continuity checks than normal profile matching.

The backend must capture operation-local connection evidence before the write stage.

This operation-local evidence is not a replacement identity.

It exists only to prove that the validated USB enumeration did not change during the transaction.

For the first Linux implementation, the operation-local connection token is:

- the current scanner `sysPath`
- the current USB `devnum` read from that same sysfs device directory

The backend captures both values immediately before SOURCE read and again before TARGET write.

These values are transaction-continuity evidence only. They must not enter `ProfileStore.js` and must not replace `identityKey`.

If either value changes unexpectedly, the transaction aborts.

## 17. Clone Transaction

The complete future transaction is:

1. Scan current devices.
2. Resolve explicit SOURCE identity.
3. Resolve explicit TARGET identity.
4. Probe SOURCE.
5. Probe TARGET.
6. Apply compatibility policy.
7. Require explicit operator confirmation.
8. Capture current operation-local connection evidence.
9. Read complete SOURCE external SPI flash.
10. Verify exact expected image size.
11. Calculate SOURCE SHA-256.
12. Rescan SOURCE and TARGET.
13. Reprobe TARGET before write.
14. Reapply compatibility policy.
15. Abort if any protected evidence changed.
16. Write the complete image to TARGET.
17. Read the complete TARGET external SPI flash.
18. Verify exact expected image size.
19. Calculate TARGET SHA-256.
20. Compare SOURCE and TARGET bytes.
21. Report PASS only if the byte comparison succeeds.
22. Remove private temporary images according to the operation policy.

No target write may occur when a source read or source validation failed.

## 18. Current Development Lock

The current hardware evidence does not include a second ESP32.

Therefore initial implementation is limited to:

- active probe
- clone fingerprint generation
- compatibility policy tests with synthetic observations
- SOURCE full-flash read
- exact size validation
- SHA-256 generation
- read-only UI evidence

The following remains disabled:

- TARGET erase
- TARGET write
- TARGET destructive validation
- final CLONE PASS state

There must be no hidden bypass for this lock.

## 19. Raw Image Data Policy

A raw flash image can contain sensitive application or operator data.

Normal session logs must not contain raw image bytes.

Temporary clone data must use private permissions.

Target permissions are:

- private directory: mode `0700`
- image files: mode `0600`

Temporary raw images must use:

`${XDG_RUNTIME_DIR}/omarchy/usb-boards/clone/<transaction-id>/`

The backend must fail closed if a private runtime directory cannot be created with the required permissions.

Persistent operation metadata, if enabled later, belongs under the existing XDG state model and must not contain raw image bytes.

Normal deterministic operation logs may contain:

- transaction identifier
- timestamps
- source identity evidence
- target identity evidence
- active probe summary
- external tool version
- image size
- source SHA-256
- target SHA-256
- stage results
- final state

Normal logs must not contain:

- full flash image bytes
- private firmware dumps
- eFuse secret material beyond the minimum evidence needed for the gate

## 20. State Model

The backend uses a small operation state model.

Candidate states are:

- `unavailable`
- `probing`
- `unsupported`
- `incompatible`
- `ready`
- `reading-source`
- `writing-target`
- `verifying`
- `pass`
- `failed`
- `aborted`

Failure detail is a separate machine-readable reason.

Candidate reasons are:

- `insufficient-devices`
- `same-device`
- `identity-insufficient`
- `probe-failed`
- `unsupported-soc`
- `unsupported-flash`
- `flash-size-mismatch`
- `security-restricted`
- `source-disconnected`
- `target-disconnected`
- `identity-changed`
- `connection-changed`
- `source-read-failed`
- `target-write-failed`
- `target-read-failed`
- `verify-mismatch`
- `dependency-missing`

Final names can change during implementation if tests show a clearer deterministic contract.

## 21. UI Design Goal

The v0.4.0 panel is optimized for discovery and serial monitoring.

Clone workflows need more visible information and easier multi-device comparison.

The panel must remain comfortable with four connected boards.

The UI must not become a narrow vertical stack that forces the operator to repeatedly scroll between SOURCE and TARGET evidence.

## 22. Adaptive Panel Layout

The preferred design is an adaptive wider panel.

Normal small-device use can remain compact.

When multiple boards are connected, or when clone workflow is active, the panel can enter a wider layout.

The preferred wide layout has:

- two columns of board summaries
- a dedicated clone section below the board area
- no horizontal scrolling
- vertical scrolling only as a safety mechanism for small displays

The exact final width must be selected from real Omarchy runtime evidence.

The design must not hard-code a larger width only because it looks reasonable in source code.

## 23. Four-Board Usability

With four connected devices, the operator should be able to identify all four board summaries in one practical workspace.

The board area should use a two-column layout when enough width is available.

Each board summary should show only the evidence needed for fast selection.

Always-visible summary information should include:

- friendly name or board label
- connection state
- board-identification result
- USB ID
- identity class
- interface or bridge
- clone eligibility indication when clone probing exists

Detailed evidence should be available on selection or expansion.

Detailed evidence can include:

- identity key
- identity evidence
- identity quality
- identification evidence
- identification scope
- complete paths
- active SoC probe
- flash information
- security information

This keeps the four-board view compact without deleting evidence.

## 24. SOURCE and TARGET UI

SOURCE and TARGET selection must be explicit.

A board card can provide separate actions for SOURCE and TARGET.

Selecting SOURCE must not automatically select TARGET.

Selecting TARGET must not start the clone.

The clone section must show both selected devices side by side when possible.

The operator must see the most important active compatibility evidence before a destructive action becomes available.

The final destructive action must require explicit target confirmation.

## 25. QML Responsibility

`Panel.qml` remains an operator interface.

It may:

- display clone state
- display active evidence
- collect explicit SOURCE selection
- collect explicit TARGET selection
- request probe or clone backend actions
- display progress and final result

It must not:

- construct hardware flashing commands
- contain flash parsing logic
- decide low-level compatibility rules
- directly implement target write behavior

## 26. Error Handling

All safety-relevant failures must be explicit.

The backend must fail closed when evidence is insufficient.

Examples include:

- source disconnect
- target disconnect
- changed current identity
- changed active SoC evidence
- changed flash evidence
- changed security evidence
- failed source read
- incomplete source image
- failed target write
- failed target readback
- byte mismatch

The backend must not continue from a partially validated state.

## 27. Test Design

Tests must exist before destructive implementation.

Required policy and transaction tests include:

- fewer than two devices means cloning unavailable
- source equals target is rejected
- incompatible devices are rejected
- generic bridge-only evidence is rejected without stronger active probe evidence
- generic bridge plus proven supported active ESP32 evidence can enter supported evaluation
- different SoC class is rejected
- different flash capacity is rejected
- unsupported flash combination is rejected
- flash encryption is rejected
- secure boot is rejected
- UART download disabled is rejected
- missing security evidence is rejected
- source disconnect aborts
- target disconnect aborts
- current identity change aborts
- operation-local connection change aborts
- active probe change aborts
- source read failure causes zero target writes
- wrong source image size blocks write
- target write failure gives explicit failure
- target read failure gives explicit failure
- target readback mismatch gives failure
- source is never written
- raw image directory permissions are private
- raw image file permissions are private
- normal logs do not contain image bytes
- temporary image cleanup follows the approved policy
- existing USB discovery remains unchanged
- existing identity behavior remains unchanged
- existing profile behavior remains unchanged
- serial monitor behavior remains unchanged

CI tests must not require physical hardware.

Hardware-specific command execution must be testable through controlled subprocess or runner substitution.

## 28. Regression Acceptance

After every meaningful implementation stage, run the existing project acceptance commands:

```text
node test_profile_store.js
python3 -m unittest -v
python3 -m py_compile usb_boards.py serial_monitor.py \
  tools/usb_boards_acceptance.py \
  test_usb_boards.py test_acceptance.py test_identity_evidence.py
bash -n install.sh
omarchy plugin validate .
python3 tools/usb_boards_acceptance.py
```

When new Python files exist, the Python compilation gate and CI workflow must also compile those new files.

Existing acceptance must remain green.

## 29. Development Stages

Development should proceed in these stages after this design is approved and an implementation plan is approved.

### Stage 1: Active Read-Only Probe

Add deterministic ESP32 classic active probing.

No flash write.

### Stage 2: Pure Compatibility Policy

Add fail-closed compatibility decisions with synthetic SOURCE/TARGET test evidence.

No hardware write.

### Stage 3: Read-Only Clone Backend

Add complete SOURCE raw flash read, exact size validation, hashing, and private temporary image handling.

No target write.

### Stage 4: Adaptive Multi-Board UI

Add the wider two-column board workspace, SOURCE/TARGET selection, active probe evidence, and read-only clone state.

No target write.

### Stage 5: Second Physical ESP32 Hardware Gate

Acquire a second suitable ESP32 and collect TARGET probe evidence.

### Stage 6: Controlled Target Write

Implement the minimum target write path and test it only against the approved second test board.

### Stage 7: Independent Readback Verification

Read the complete TARGET image after programming and require byte-for-byte equality.

### Stage 8: Full Omarchy Acceptance

Run the complete automated and real-runtime acceptance before any promotion decision.

## 30. Promotion Rule

No clone feature may be promoted to `master` without explicit user approval.

No destructive write behavior may be described as proven until it has passed a real second-board write and independent readback test.

A synthetic unit test cannot replace that hardware evidence.

## 31. Design Decision Summary

The approved direction is:

- Omarchy / Arch Linux only
- raw external flash cloning
- classic ESP32 as the first hardware family
- active hardware interrogation as a new evidence layer
- no change to the trusted USB identity architecture
- no profile schema change
- no serial monitor change
- no generic programmer framework yet
- three small Python clone components
- external `esptool` boundary
- fail-closed compatibility
- private temporary raw images
- byte-for-byte target verification before PASS
- target write disabled until a second physical ESP32 is available
- adaptive wider two-column UI for comfortable four-board operation

This design preserves the existing v0.4.0 architecture and adds the smallest evidence-based path toward deep hardware-level cloning.
