"use strict"

const assert = require("assert")
const Store = require("./ProfileStore.js")

function test(name, fn) {
  try {
    fn()
    process.stdout.write("PASS " + name + "\n")
  } catch (error) {
    process.stderr.write("FAIL " + name + "\n")
    throw error
  }
}

test("empty store has schema version 1", () => {
  assert.deepStrictEqual(Store.emptyStore(), {
    schemaVersion: 1,
    profiles: {},
    legacyProfiles: {}
  })
})

test("missing store parses as a new schema-1 store", () => {
  const result = Store.parseStore("")
  assert.strictEqual(result.ok, true)
  assert.strictEqual(result.status, "missing")
  assert.deepStrictEqual(result.store, Store.emptyStore())
})

test("invalid JSON fails closed", () => {
  const result = Store.parseStore("{bad")
  assert.strictEqual(result.ok, false)
  assert.strictEqual(result.status, "invalid")
})

test("future schema fails closed", () => {
  const result = Store.parseStore(JSON.stringify({
    schemaVersion: 2,
    profiles: {},
    legacyProfiles: {}
  }))
  assert.strictEqual(result.ok, false)
  assert.strictEqual(result.status, "unsupported")
})

test("canonical JSON sorts object keys recursively", () => {
  assert.strictEqual(
    Store.canonicalStringify({z: 1, a: {y: 2, b: 3}}),
    '{"a":{"b":3,"y":2},"z":1}'
  )
})

function portableDevice(key, vendor, product, serial) {
  return {
    identityKey: key,
    identityEvidence: "usb-serial",
    identityPortBound: false,
    vendorId: vendor,
    productId: product,
    serial: serial,
    connected: true
  }
}

function topologyDevice(key, vendor, product, serial) {
  return {
    identityKey: key,
    identityEvidence: "usb-topology",
    identityPortBound: true,
    vendorId: vendor,
    productId: product,
    serial: serial,
    connected: true
  }
}

test("existing explicit identity profile imports without changing identity", () => {
  const legacy = {
    "usb-topology:1a86:7523:2-1.2": {
      nickname: "CH340 port",
      identityKey: "usb-topology:1a86:7523:2-1.2",
      identityEvidence: "usb-topology",
      identityPortBound: true,
      vendorId: "1a86",
      productId: "7523",
      serial: ""
    }
  }
  const result = Store.migrate("", legacy, [])
  assert.strictEqual(result.ok, true)
  assert.strictEqual(
    result.store.profiles["usb-topology:1a86:7523:2-1.2"].nickname,
    "CH340 port"
  )
  assert.strictEqual(
    result.store.profiles["usb-topology:1a86:7523:2-1.2"].identityKey,
    "usb-topology:1a86:7523:2-1.2"
  )
})

test("unique legacy profile migrates only to scanner supplied portable identity", () => {
  const legacyKey = "/dev/serial/by-id/usb-Silicon_Labs_ABC123-if00-port0"
  const legacy = {}
  legacy[legacyKey] = {
    nickname: "Bench controller",
    baudRate: 230400,
    vendorId: "10c4",
    productId: "ea60",
    serial: "ABC123"
  }
  const device = portableDevice(
    "usb-serial:10c4:ea60:ABC123", "10c4", "ea60", "ABC123"
  )

  const result = Store.migrate("", legacy, [device])

  assert.strictEqual(result.ok, true)
  assert.strictEqual(
    result.store.profiles["usb-serial:10c4:ea60:ABC123"].nickname,
    "Bench controller"
  )
  assert.strictEqual(
    result.store.profiles["usb-serial:10c4:ea60:ABC123"].baudRate,
    230400
  )
  assert.strictEqual(
    result.store.legacyProfiles[legacyKey].migrationState,
    "migrated"
  )
  assert.strictEqual(
    result.store.legacyProfiles[legacyKey].migrationEvidence,
    "recorded-serial-matched-current-identity"
  )
})

test("CP2102 0001 topology identity never receives legacy portable migration", () => {
  const key = "/dev/serial/by-id/usb-Silicon_Labs_CP2102_0001-if00-port0"
  const legacy = {}
  legacy[key] = {
    nickname: "Old CP2102",
    vendorId: "10c4",
    productId: "ea60",
    serial: "0001"
  }

  const result = Store.migrate("", legacy, [
    topologyDevice("usb-topology:10c4:ea60:3-1.3", "10c4", "ea60", "0001")
  ])

  assert.strictEqual(
    result.store.profiles["usb-topology:10c4:ea60:3-1.3"],
    undefined
  )
  assert.strictEqual(result.store.legacyProfiles[key].migrationState, "unresolved")
  assert.strictEqual(result.store.legacyProfiles[key].migrationReason, "topology-identity")
})

test("no-serial CH340 topology identity never inherits stable-path profile", () => {
  const key = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
  const legacy = {}
  legacy[key] = {
    nickname: "Old CH340",
    vendorId: "1a86",
    productId: "7523",
    serial: ""
  }

  const result = Store.migrate("", legacy, [
    topologyDevice("usb-topology:1a86:7523:2-1.2", "1a86", "7523", "")
  ])

  assert.strictEqual(
    result.store.profiles["usb-topology:1a86:7523:2-1.2"],
    undefined
  )
  assert.strictEqual(result.store.legacyProfiles[key].migrationState, "unresolved")
  assert.strictEqual(result.store.legacyProfiles[key].migrationReason, "topology-identity")
})

test("stable path equality alone is never migration evidence", () => {
  const key = "/dev/serial/by-id/shared"
  const legacy = {}
  legacy[key] = {
    nickname: "Wrong device",
    vendorId: "1a86",
    productId: "7523",
    serial: ""
  }
  const device = portableDevice(
    "usb-serial:10c4:ea60:ABC123", "10c4", "ea60", "ABC123"
  )
  device.stablePath = key

  const result = Store.migrate("", legacy, [device])
  assert.strictEqual(
    result.store.profiles["usb-serial:10c4:ea60:ABC123"],
    undefined
  )
  assert.strictEqual(result.store.legacyProfiles[key].migrationReason, "insufficient-identity-evidence")
})

test("VID mismatch does not migrate", () => {
  const key = "/dev/serial/by-id/old"
  const legacy = {[key]: {vendorId: "1a86", productId: "ea60", serial: "ABC123"}}
  const result = Store.migrate("", legacy, [portableDevice(
    "usb-serial:10c4:ea60:ABC123", "10c4", "ea60", "ABC123"
  )])
  assert.strictEqual(result.store.profiles["usb-serial:10c4:ea60:ABC123"], undefined)
})

test("PID mismatch does not migrate", () => {
  const key = "/dev/serial/by-id/old"
  const legacy = {[key]: {vendorId: "10c4", productId: "7523", serial: "ABC123"}}
  const result = Store.migrate("", legacy, [portableDevice(
    "usb-serial:10c4:ea60:ABC123", "10c4", "ea60", "ABC123"
  )])
  assert.strictEqual(result.store.profiles["usb-serial:10c4:ea60:ABC123"], undefined)
})

test("serial mismatch does not migrate", () => {
  const key = "/dev/serial/by-id/old"
  const legacy = {[key]: {vendorId: "10c4", productId: "ea60", serial: "XYZ999"}}
  const result = Store.migrate("", legacy, [portableDevice(
    "usb-serial:10c4:ea60:ABC123", "10c4", "ea60", "ABC123"
  )])
  assert.strictEqual(result.store.profiles["usb-serial:10c4:ea60:ABC123"], undefined)
})

test("existing target profile is never overwritten", () => {
  const target = "usb-serial:10c4:ea60:ABC123"
  const raw = JSON.stringify({
    schemaVersion: 1,
    profiles: {
      [target]: {
        nickname: "Current",
        identityKey: target,
        identityEvidence: "usb-serial",
        identityPortBound: false
      }
    },
    legacyProfiles: {}
  })
  const legacyKey = "/dev/serial/by-id/old"
  const legacy = {
    [legacyKey]: {
      nickname: "Legacy",
      vendorId: "10c4",
      productId: "ea60",
      serial: "ABC123"
    }
  }

  const result = Store.migrate(raw, legacy, [
    portableDevice(target, "10c4", "ea60", "ABC123")
  ])

  assert.strictEqual(result.store.profiles[target].nickname, "Current")
  assert.strictEqual(result.store.legacyProfiles[legacyKey].migrationState, "conflict")
  assert.strictEqual(result.store.legacyProfiles[legacyKey].migrationReason, "target-already-exists")
})

test("two legacy sources for one identity are both conflicts", () => {
  const legacy = {
    "/dev/serial/by-id/a": {
      nickname: "A", vendorId: "10c4", productId: "ea60", serial: "ABC123"
    },
    "/dev/serial/by-id/b": {
      nickname: "B", vendorId: "10c4", productId: "ea60", serial: "ABC123"
    }
  }
  const result = Store.migrate("", legacy, [
    portableDevice("usb-serial:10c4:ea60:ABC123", "10c4", "ea60", "ABC123")
  ])

  assert.strictEqual(
    result.store.legacyProfiles["/dev/serial/by-id/a"].migrationReason,
    "multiple-legacy-sources"
  )
  assert.strictEqual(
    result.store.legacyProfiles["/dev/serial/by-id/b"].migrationReason,
    "multiple-legacy-sources"
  )
})

test("migration is byte-stable when repeated with the same inputs", () => {
  const legacy = {
    "/dev/serial/by-id/old": {
      nickname: "Bench",
      vendorId: "10c4",
      productId: "ea60",
      serial: "ABC123"
    }
  }
  const devices = [
    portableDevice("usb-serial:10c4:ea60:ABC123", "10c4", "ea60", "ABC123")
  ]

  const first = Store.migrate("", legacy, devices)
  const second = Store.migrate(first.canonical, legacy, devices)

  assert.strictEqual(second.ok, true)
  assert.strictEqual(second.changed, false)
  assert.strictEqual(second.canonical, first.canonical)
})

test("connected device profile lookup uses only exact scanner identity", () => {
  const store = {
    schemaVersion: 1,
    profiles: {
      "usb-topology:1a86:7523:2-1.2": {nickname: "Port A"}
    },
    legacyProfiles: {
      "/dev/serial/by-id/shared": {
        profile: {nickname: "Legacy"},
        migrationState: "unresolved",
        migrationReason: "topology-identity",
        targetKey: ""
      }
    }
  }
  const device = topologyDevice(
    "usb-topology:1a86:7523:2-1.2", "1a86", "7523", ""
  )
  device.stablePath = "/dev/serial/by-id/shared"

  assert.strictEqual(Store.profileForDevice(store, device).nickname, "Port A")
  assert.strictEqual(Store.hasProfileForDevice(store, device), true)
})

test("topology device never falls back to matching legacy stable path", () => {
  const store = {
    schemaVersion: 1,
    profiles: {},
    legacyProfiles: {
      "/dev/serial/by-id/shared": {
        profile: {nickname: "Legacy"},
        migrationState: "unresolved",
        migrationReason: "topology-identity",
        targetKey: ""
      }
    }
  }
  const device = topologyDevice(
    "usb-topology:1a86:7523:2-1.2", "1a86", "7523", ""
  )
  device.stablePath = "/dev/serial/by-id/shared"

  assert.deepStrictEqual(Store.profileForDevice(store, device), {})
  assert.strictEqual(Store.hasProfileForDevice(store, device), false)
})

test("new profile write targets schema store and records native origin", () => {
  const device = topologyDevice(
    "usb-topology:1a86:7523:2-1.2", "1a86", "7523", ""
  )
  const result = Store.upsertDeviceProfile(Store.emptyStore(), device, {
    nickname: "CH340 socket",
    baudRate: 115200,
    identityKey: device.identityKey,
    identityEvidence: device.identityEvidence,
    identityPortBound: true
  })

  assert.strictEqual(result.ok, true)
  assert.strictEqual(
    result.store.profiles[device.identityKey].nickname,
    "CH340 socket"
  )
  assert.strictEqual(
    result.store.profiles[device.identityKey].profileOrigin,
    "native"
  )
})

test("editing migrated profile preserves migration provenance", () => {
  const target = "usb-serial:10c4:ea60:ABC123"
  const store = {
    schemaVersion: 1,
    profiles: {
      [target]: {
        nickname: "Old",
        profileOrigin: "legacy-migrated",
        migrationSourceKey: "/dev/serial/by-id/old",
        migrationEvidence: "recorded-serial-matched-current-identity"
      }
    },
    legacyProfiles: {}
  }
  const device = portableDevice(target, "10c4", "ea60", "ABC123")
  const result = Store.upsertDeviceProfile(store, device, {nickname: "New"})

  assert.strictEqual(result.store.profiles[target].nickname, "New")
  assert.strictEqual(result.store.profiles[target].profileOrigin, "legacy-migrated")
  assert.strictEqual(result.store.profiles[target].migrationSourceKey, "/dev/serial/by-id/old")
})

test("unresolved legacy projected record updates only its preserved legacy profile", () => {
  const legacyKey = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
  const store = {
    schemaVersion: 1,
    profiles: {},
    legacyProfiles: {
      [legacyKey]: {
        profile: {nickname: "Old CH340", baudRate: 9600},
        migrationState: "unresolved",
        migrationReason: "topology-identity",
        targetKey: "",
        migrationEvidence: ""
      }
    }
  }
  const projected = {
    profileStoreKind: "legacy",
    profileStoreKey: legacyKey,
    connected: false
  }

  const result = Store.upsertDeviceProfile(store, projected, {
    nickname: "Recovered CH340",
    baudRate: 115200
  })

  assert.strictEqual(result.store.legacyProfiles[legacyKey].profile.nickname, "Recovered CH340")
  assert.strictEqual(result.store.legacyProfiles[legacyKey].migrationState, "unresolved")
  assert.deepStrictEqual(result.store.profiles, {})
})

test("record keys distinguish legacy records from physical identity profiles", () => {
  assert.strictEqual(
    Store.recordKey({identityKey: "usb-topology:1a86:7523:2-1.2"}),
    "profile:usb-topology:1a86:7523:2-1.2"
  )
  assert.strictEqual(
    Store.recordKey({profileStoreKind: "legacy", profileStoreKey: "/dev/serial/by-id/old"}),
    "legacy:/dev/serial/by-id/old"
  )
})

test("offline projection shows identity profiles and unresolved legacy records once", () => {
  const store = {
    schemaVersion: 1,
    profiles: {
      "usb-serial:10c4:ea60:ABC123": {
        nickname: "Portable",
        identityKey: "usb-serial:10c4:ea60:ABC123",
        identityEvidence: "usb-serial",
        identityPortBound: false,
        vendorId: "10c4",
        productId: "ea60",
        serial: "ABC123"
      }
    },
    legacyProfiles: {
      "/dev/serial/by-id/unresolved": {
        profile: {nickname: "Old CH340", vendorId: "1a86", productId: "7523", serial: ""},
        migrationState: "unresolved",
        migrationReason: "topology-identity",
        targetKey: "",
        migrationEvidence: ""
      },
      "/dev/serial/by-id/migrated": {
        profile: {nickname: "Old portable"},
        migrationState: "migrated",
        migrationReason: "",
        targetKey: "usb-serial:10c4:ea60:ABC123",
        migrationEvidence: "recorded-serial-matched-current-identity"
      }
    }
  }

  const projected = Store.projectDevices([], store)
  assert.strictEqual(projected.length, 2)
  assert.strictEqual(projected.filter(d => d.profileStoreKind === "profile").length, 1)
  assert.strictEqual(projected.filter(d => d.profileStoreKind === "legacy").length, 1)
  assert.strictEqual(projected.find(d => d.profileStoreKind === "legacy").migrationState, "unresolved")
})

test("connected identity profile is not duplicated as offline", () => {
  const key = "usb-serial:10c4:ea60:ABC123"
  const store = {
    schemaVersion: 1,
    profiles: {
      [key]: {
        nickname: "Portable",
        identityKey: key,
        identityEvidence: "usb-serial",
        identityPortBound: false
      }
    },
    legacyProfiles: {}
  }
  const connected = [portableDevice(key, "10c4", "ea60", "ABC123")]
  const projected = Store.projectDevices(connected, store)

  assert.strictEqual(projected.length, 1)
  assert.strictEqual(projected[0].connected, true)
  assert.strictEqual(projected[0].profileStoreKey, key)
})

test("legacy stable path does not hide unresolved offline profile", () => {
  const legacyKey = "/dev/serial/by-id/shared"
  const store = {
    schemaVersion: 1,
    profiles: {},
    legacyProfiles: {
      [legacyKey]: {
        profile: {nickname: "Old CH340"},
        migrationState: "unresolved",
        migrationReason: "topology-identity",
        targetKey: "",
        migrationEvidence: ""
      }
    }
  }
  const connected = [topologyDevice(
    "usb-topology:1a86:7523:2-1.2", "1a86", "7523", ""
  )]
  connected[0].stablePath = legacyKey

  const projected = Store.projectDevices(connected, store)
  assert.strictEqual(projected.length, 2)
  assert.strictEqual(projected.filter(d => d.connected === false).length, 1)
  assert.strictEqual(projected.find(d => d.connected === false).profileStoreKey, legacyKey)
})

test("offline identity profile preserves recorded scanner diagnostics", () => {
  const key = "usb-serial:0403:6001:AB0JQVS6"
  const store = {
    schemaVersion: 1,
    profiles: {
      [key]: {
        nickname: "gnarftz",
        identityKey: key,
        identityEvidence: "usb-serial",
        identityPortBound: false,
        identityQuality: "reported",
        identificationEvidence: "bridge",
        identificationScope: "bridge"
      }
    },
    legacyProfiles: {}
  }

  const projected = Store.projectDevices([], store)
  assert.strictEqual(projected.length, 1)
  assert.strictEqual(projected[0].identityQuality, "reported")
  assert.strictEqual(projected[0].identificationEvidence, "bridge")
  assert.strictEqual(projected[0].identificationScope, "bridge")
})
