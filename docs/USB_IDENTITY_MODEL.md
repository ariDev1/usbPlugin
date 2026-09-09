# USB Identity Model

USB Boards separates three concepts:

- **Detection**: what the connected USB device appears to be
- **Identity**: which observations belong to the same physical device or profile
- **Connection**: which current Linux path is used to communicate with the device

These concepts use different evidence. A connection path is not physical identity evidence.

## Detection, Identity, and Connection

Detection describes the USB observation. It can identify a board, family, USB function, bootloader, bridge, or an unknown device.

Identity determines the profile key. USB Boards uses a reported USB serial when that serial is suitable for portable identity. Otherwise it uses USB topology and treats the identity as port-bound.

Connection describes the current Linux interface. Examples are:

```text
/dev/ttyUSB0
/dev/ttyACM0
/dev/serial/by-id/...
```

USB Boards can show and use these paths for communication. It does not use them as proof that two observations are the same physical device.

## Board Identification Evidence

Connected scanner observations contain these fields:

| Field | Meaning |
| --- | --- |
| `board` | Human-readable description supported by USB evidence |
| `confidence` | Strength of the identification result |
| `identificationEvidence` | Evidence class used for the result |
| `identificationScope` | What the result identifies |

`confidence`: `exact`, `probable`, `bridge-only`, `unknown`.

`identificationEvidence`: `vid-pid`, `descriptor`, `vendor`, `bridge`, `unknown`.

`identificationScope`: `board`, `family`, `function`, `bootloader`, `bridge`, `unknown`.

A result with scope `function` or `bootloader` is not proof of the complete board identity.

## Generic USB Bridges
FTDI, CP210x, CH34x, CH91xx, and PL2303 devices can identify a USB-to-serial bridge. They do not prove which development board is behind the bridge.

For example, VID:PID `1a86:7523` identifies a CH340/CH341 bridge. It does not prove that the attached board is an ESP32, Arduino, or another board.

Generic bridge evidence therefore uses `confidence = bridge-only` and `identificationScope = bridge`. USB Boards does not guess the board behind the bridge.

## Physical Identity

| Field | Meaning |
| --- | --- |
| `identityKey` | Deterministic key used for profiles and observation matching |
| `identityEvidence` | Physical identity evidence used to construct the key |
| `identityPortBound` | `true` when the identity depends on USB topology |
| `identityQuality` | Quality of the USB serial evidence |

`identityQuality` can be:

- `reported`: a non-empty serial that is not classified as a known default
- `known-default`: a reported serial that is not safe as portable identity
- `missing`: no USB serial is available

The current `identityEvidence` values are `usb-serial` and `usb-topology`.

## Portable Identity

A device with `identityQuality = reported` uses:

```text
usb-serial:<VID>:<PID>:<serial>
```

It has `identityEvidence = usb-serial` and `identityPortBound = false`. The profile key does not depend on USB topology, so the profile can follow the device to another USB port.

Example:

```text
VID:PID           0403:6001
USB serial        AB0JQVS6
identityQuality   reported
identityKey       usb-serial:0403:6001:AB0JQVS6
identityEvidence  usb-serial
identityPortBound false
```

A remembered nickname such as `gnarftz` stays attached to this identity.

## Port-Bound Identity

If the USB serial is missing or is a known default, USB Boards uses:

```text
usb-topology:<VID>:<PID>:<topology>
```

It has `identityEvidence = usb-topology` and `identityPortBound = true`. Moving the device to another USB port can produce a different identity key.

### CP2102 with serial `0001`

The classic CP2102 VID:PID `10c4:ea60` can report the factory default serial `0001`. USB Boards classifies this value as `known-default` and does not use it as portable identity evidence.

```text
VID:PID           10c4:ea60
USB serial        0001
identityQuality   known-default
identityKey       usb-topology:10c4:ea60:3-1.3
identityEvidence  usb-topology
identityPortBound true
```

### CH340 without a serial
A CH340/CH341 device with VID:PID `1a86:7523` and no USB serial has `identityQuality = missing`.

```text
VID:PID           1a86:7523
USB serial        <missing>
identityQuality   missing
identityKey       usb-topology:1a86:7523:2-1.2
identityEvidence  usb-topology
identityPortBound true
```

## Multiple Identical Devices
Devices with distinct reported USB serials can each have portable identity. Devices without safe serial evidence are distinguished by topology and are port-bound.

If two port-bound devices exchange USB ports, their topology keys follow the ports. USB Boards does not claim that it can follow the physical units because the scanner has no stronger identity evidence.

## Profile Persistence
`ProfileStore.js` is the pure profile component. The active profile store uses `schemaVersion = 1`.

Current profiles are stored by `identityKey`. A disconnected device can remain visible as an offline profile without using a current `/dev` path as identity proof.

Legacy `deviceProfiles` data remains available as rollback evidence. Schema-v1 migration does not delete that legacy setting.

An existing profile for the current identity has priority. Migration does not overwrite it.

## Legacy Migration

Legacy profile migration is evidence-based. Path equality alone is never migration evidence.

Legacy records that already use an explicit `usb-serial:` or `usb-topology:` key can be imported without changing that identity.

Older path-keyed records start as unresolved records. A path-keyed record can migrate only when:

1. the current scanner identity is portable
2. recorded VID matches
3. recorded PID matches
4. recorded USB serial matches
5. exactly one legacy source maps to the target
6. the target identity profile does not already exist

A successful path-keyed migration records:

```text
migrationState    migrated
migrationEvidence recorded-serial-matched-current-identity
```

A CP2102 with serial `0001` and a no-serial CH340 do not satisfy the portable-identity condition. Topology identities do not inherit legacy path profiles only because a path looks related.

## Migration States and Conflicts
- `unresolved`: evidence is not sufficient for safe migration
- `migrated`: profile data was copied to one supported identity target
- `conflict`: migration cannot choose or replace a target safely

Conflict reasons include `multiple-legacy-sources` and `target-already-exists`. A topology-related legacy record can remain unresolved with reason `topology-identity`.

Migration is deterministic and idempotent. Repeating it with the same inputs produces the same canonical store and no additional change.

## Identity Evidence and Migration Evidence
`identityEvidence` is physical identity evidence. It explains why the current identity key was selected.

`migrationEvidence` is profile-copy provenance. It explains why legacy profile data was copied.

Do not use `migrationEvidence` to construct an identity key. Do not use `identityEvidence` alone as proof that legacy profile data should be copied.

## Active Clone Evidence

USB identity evidence and active clone evidence are separate.

The passive scanner remains the authority for USB detection and physical identity.
For example, a CH340/CH341 bridge can remain `bridge-only` and `BOARD UNKNOWN`
even when a later active Espressif ROM probe identifies an ESP32 behind that
bridge. Active evidence does not rewrite `board`, `confidence`,
`identificationEvidence`, or `identificationScope`.

An active clone probe can observe silicon and flash properties that passive USB
enumeration cannot prove. Current read-only probe evidence can include the SoC
model and revision, chip MAC, crystal frequency, flash JEDEC identity, flash
capacity, flash voltage, flash-encryption state, secure-boot state, UART
download state, and relevant eFuse read/write-disable masks.

Active probe evidence is operation state. It is not stored in
`ProfileStore.js`. SOURCE and TARGET selections are also runtime-only. They use
`identityKey`, require a currently connected device, and cannot refer to the
same identity at the same time.

`/dev/ttyUSBx`, `/dev/ttyACMx`, and stable `/dev/serial/...` paths remain
connection paths. They are not promoted to physical identity evidence by clone
operations.

During one active transaction, USB Boards uses the scanner identity plus
`sysPath` and the USB device number (`devnum`) as continuity evidence. This
continuity check is local to that transaction. It is not a persistent identity
scheme.

Espressif ROM probing resets the target MCU. The UI therefore starts probing
and source reads only after an explicit operator action and states that the
operation resets the board.

Raw source images are temporary private data. The clone backend creates them
under:

```text
${XDG_RUNTIME_DIR}/omarchy/usb-boards/clone/<transaction-id>/
```

The transaction directory is owner-only (`0700`) and the raw image is
owner-only (`0600`). A completed source read reports metadata such as exact
image size and SHA-256. The temporary raw image is then removed.

eFuses are evidence only in the current architecture. USB Boards can read
security state for compatibility decisions. It does not copy, burn, or modify
eFuses as part of a normal clone operation.

The current implementation boundary is explicit:

```text
SOURCE READ: IMPLEMENTED
TARGET WRITE: NOT IMPLEMENTED
TARGET VERIFY: NOT IMPLEMENTED
CLONE PASS: NOT CLAIMED
```

## Fail-Closed Behavior
Invalid JSON fails closed. An unsupported schema version fails closed. An invalid store shape fails closed.

Migration does not invent a replacement identity or silently recover incompatible profile data.

## Deterministic Runtime Acceptance
Run the workstation acceptance gate with:

```bash
python3 tools/usb_boards_acceptance.py
```

The gate requires the `development` branch and requires the active Omarchy plugin path to resolve to that checkout.

It validates the plugin, scans devices directly, restarts the Omarchy shell, verifies IPC readiness, reads runtime state, and compares connected scanner and runtime identities.

The comparison includes the physical identity fields, VID/PID/serial, and the board-identification evidence fields. Missing, duplicate, unexpected, or changed connected identity evidence causes acceptance to fail.
