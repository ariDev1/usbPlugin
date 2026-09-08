"use strict"

var SCHEMA_VERSION = 1

function emptyStore() {
  return {
    schemaVersion: SCHEMA_VERSION,
    profiles: {},
    legacyProfiles: {}
  }
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}

function sortValue(value) {
  if (Array.isArray(value)) return value.map(sortValue)
  if (!isPlainObject(value)) return value

  var out = {}
  Object.keys(value).sort().forEach(function(key) {
    out[key] = sortValue(value[key])
  })
  return out
}

function canonicalStringify(value) {
  return JSON.stringify(sortValue(value))
}

function parseStore(raw) {
  var text = String(raw || "").trim()
  if (text === "") {
    var fresh = emptyStore()
    return {
      ok: true,
      status: "missing",
      store: fresh,
      canonical: canonicalStringify(fresh),
      error: ""
    }
  }

  var parsed
  try {
    parsed = JSON.parse(text)
  } catch (error) {
    return {ok: false, status: "invalid", store: null, canonical: "", error: "invalid-json"}
  }

  if (!isPlainObject(parsed) || parsed.schemaVersion !== SCHEMA_VERSION) {
    return {ok: false, status: "unsupported", store: null, canonical: "", error: "unsupported-schema"}
  }
  if (!isPlainObject(parsed.profiles) || !isPlainObject(parsed.legacyProfiles)) {
    return {ok: false, status: "invalid", store: null, canonical: "", error: "invalid-store-shape"}
  }

  return {
    ok: true,
    status: "current",
    store: parsed,
    canonical: canonicalStringify(parsed),
    error: ""
  }
}


function cloneValue(value) {
  return JSON.parse(JSON.stringify(value))
}

function isIdentityKey(key) {
  var value = String(key || "")
  return value.indexOf("usb-serial:") === 0 || value.indexOf("usb-topology:") === 0
}

function portableIdentity(device) {
  return !!device
    && device.identityEvidence === "usb-serial"
    && device.identityPortBound === false
    && String(device.identityKey || "").indexOf("usb-serial:") === 0
}

function exactRecordedMatch(profile, device) {
  var vendor = String(profile && profile.vendorId || "")
  var product = String(profile && profile.productId || "")
  var serial = String(profile && profile.serial || "")
  return vendor !== ""
    && product !== ""
    && serial !== ""
    && vendor === String(device && device.vendorId || "")
    && product === String(device && device.productId || "")
    && serial === String(device && device.serial || "")
}

function topologyRelated(profile, device) {
  if (!device || device.identityEvidence !== "usb-topology") return false
  var vendor = String(profile && profile.vendorId || "")
  var product = String(profile && profile.productId || "")
  var serial = String(profile && profile.serial || "")
  if (vendor === "" || product === "") return false
  if (vendor !== String(device.vendorId || "")) return false
  if (product !== String(device.productId || "")) return false
  return serial === "" || serial === String(device.serial || "")
}

function migrate(rawStore, legacyProfiles, connectedDevices) {
  var parsed = parseStore(rawStore)
  if (!parsed.ok) {
    return {
      ok: false,
      changed: false,
      store: null,
      canonical: "",
      error: parsed.error
    }
  }

  var next = cloneValue(parsed.store)
  var legacy = isPlainObject(legacyProfiles) ? legacyProfiles : {}
  var devices = Array.isArray(connectedDevices) ? connectedDevices : []

  Object.keys(legacy).sort().forEach(function(key) {
    var profile = legacy[key]
    if (!isIdentityKey(key) || !isPlainObject(profile)) return
    var storedIdentity = String(profile.identityKey || "")
    if (storedIdentity !== "" && storedIdentity !== key) return
    if (next.profiles[key] !== undefined) return

    var imported = cloneValue(profile)
    if (!imported.identityKey) imported.identityKey = key
    if (!imported.profileOrigin) imported.profileOrigin = "legacy-migrated"
    if (!imported.migrationSourceKey) imported.migrationSourceKey = key
    if (!imported.migrationEvidence) imported.migrationEvidence = "existing-explicit-identity"
    next.profiles[key] = imported
  })

  Object.keys(legacy).sort().forEach(function(key) {
    var profile = legacy[key]
    if (isIdentityKey(key) || !isPlainObject(profile)) return
    if (next.legacyProfiles[key] !== undefined) return
    next.legacyProfiles[key] = {
      profile: cloneValue(profile),
      migrationState: "unresolved",
      migrationReason: "insufficient-identity-evidence",
      targetKey: "",
      migrationEvidence: ""
    }
  })

  var candidatesByTarget = {}
  var deviceByTarget = {}

  Object.keys(next.legacyProfiles).sort().forEach(function(sourceKey) {
    var record = next.legacyProfiles[sourceKey]
    if (!isPlainObject(record) || !isPlainObject(record.profile)) return

    if (record.migrationState === "migrated"
        && record.targetKey
        && next.profiles[record.targetKey]
        && next.profiles[record.targetKey].migrationSourceKey === sourceKey) {
      return
    }

    record.migrationState = "unresolved"
    record.migrationReason = "insufficient-identity-evidence"
    record.targetKey = ""
    record.migrationEvidence = ""

    var targets = {}
    for (var i = 0; i < devices.length; i++) {
      var device = devices[i]
      if (portableIdentity(device) && exactRecordedMatch(record.profile, device)) {
        var targetKey = String(device.identityKey || "")
        if (targetKey !== "") {
          targets[targetKey] = true
          deviceByTarget[targetKey] = device
        }
      }
    }

    var targetKeys = Object.keys(targets).sort()
    if (targetKeys.length === 1) {
      var onlyTarget = targetKeys[0]
      if (!candidatesByTarget[onlyTarget]) candidatesByTarget[onlyTarget] = []
      candidatesByTarget[onlyTarget].push(sourceKey)
      return
    }

    for (var j = 0; j < devices.length; j++) {
      if (topologyRelated(record.profile, devices[j])) {
        record.migrationReason = "topology-identity"
        return
      }
    }
  })

  Object.keys(candidatesByTarget).sort().forEach(function(targetKey) {
    var sources = candidatesByTarget[targetKey].slice().sort()
    if (sources.length > 1) {
      sources.forEach(function(sourceKey) {
        var record = next.legacyProfiles[sourceKey]
        record.migrationState = "conflict"
        record.migrationReason = "multiple-legacy-sources"
        record.targetKey = targetKey
        record.migrationEvidence = ""
      })
      return
    }

    var sourceKey = sources[0]
    var record = next.legacyProfiles[sourceKey]
    if (next.profiles[targetKey] !== undefined) {
      record.migrationState = "conflict"
      record.migrationReason = "target-already-exists"
      record.targetKey = targetKey
      record.migrationEvidence = ""
      return
    }

    var device = deviceByTarget[targetKey]
    var migrated = cloneValue(record.profile)
    migrated.identityKey = targetKey
    migrated.identityEvidence = String(device.identityEvidence || "")
    migrated.identityPortBound = device.identityPortBound === true
    migrated.vendorId = String(device.vendorId || migrated.vendorId || "")
    migrated.productId = String(device.productId || migrated.productId || "")
    migrated.serial = String(device.serial || migrated.serial || "")
    migrated.profileOrigin = "legacy-migrated"
    migrated.migrationSourceKey = sourceKey
    migrated.migrationEvidence = "recorded-serial-matched-current-identity"
    next.profiles[targetKey] = migrated

    record.migrationState = "migrated"
    record.migrationReason = ""
    record.targetKey = targetKey
    record.migrationEvidence = "recorded-serial-matched-current-identity"
  })

  var canonical = canonicalStringify(next)
  return {
    ok: true,
    changed: canonical !== parsed.canonical,
    store: next,
    canonical: canonical,
    error: ""
  }
}


function recordKey(device) {
  if (!device) return ""
  if (device.profileStoreKind === "legacy") {
    var legacyKey = String(device.profileStoreKey || "")
    return legacyKey === "" ? "" : "legacy:" + legacyKey
  }
  var identity = String(device.identityKey || device.profileStoreKey || "")
  return identity === "" ? "" : "profile:" + identity
}

function profileForDevice(store, device) {
  if (!isPlainObject(store) || !device) return {}
  if (device.profileStoreKind === "legacy") {
    var legacyKey = String(device.profileStoreKey || "")
    var legacyRecord = store.legacyProfiles && store.legacyProfiles[legacyKey]
    return legacyRecord && isPlainObject(legacyRecord.profile) ? legacyRecord.profile : {}
  }
  var identityKey = String(device.identityKey || device.profileStoreKey || "")
  var profile = store.profiles && store.profiles[identityKey]
  return isPlainObject(profile) ? profile : {}
}

function hasProfileForDevice(store, device) {
  if (!isPlainObject(store) || !device) return false
  if (device.profileStoreKind === "legacy") {
    var legacyKey = String(device.profileStoreKey || "")
    return !!(store.legacyProfiles
      && isPlainObject(store.legacyProfiles[legacyKey])
      && isPlainObject(store.legacyProfiles[legacyKey].profile))
  }
  var identityKey = String(device.identityKey || device.profileStoreKey || "")
  return identityKey !== "" && !!(store.profiles && isPlainObject(store.profiles[identityKey]))
}

function upsertDeviceProfile(store, device, profileData) {
  if (!isPlainObject(store)
      || store.schemaVersion !== SCHEMA_VERSION
      || !isPlainObject(store.profiles)
      || !isPlainObject(store.legacyProfiles)
      || !device
      || !isPlainObject(profileData)) {
    return {ok: false, store: null, canonical: "", error: "invalid-input"}
  }

  var next = cloneValue(store)
  if (device.profileStoreKind === "legacy") {
    var legacyKey = String(device.profileStoreKey || "")
    var record = next.legacyProfiles[legacyKey]
    if (legacyKey === "" || !isPlainObject(record)) {
      return {ok: false, store: null, canonical: "", error: "unknown-legacy-record"}
    }
    record.profile = cloneValue(profileData)
  } else {
    var identityKey = String(device.identityKey || device.profileStoreKey || "")
    if (identityKey === "" || !isIdentityKey(identityKey)) {
      return {ok: false, store: null, canonical: "", error: "missing-identity"}
    }
    var existing = isPlainObject(next.profiles[identityKey]) ? next.profiles[identityKey] : {}
    var saved = cloneValue(profileData)
    saved.identityKey = identityKey
    if (device.identityEvidence !== undefined)
      saved.identityEvidence = String(device.identityEvidence || "")
    if (device.identityPortBound !== undefined)
      saved.identityPortBound = device.identityPortBound === true
    if (device.vendorId !== undefined)
      saved.vendorId = String(device.vendorId || "")
    if (device.productId !== undefined)
      saved.productId = String(device.productId || "")
    if (device.serial !== undefined)
      saved.serial = String(device.serial || "")
    saved.profileOrigin = String(existing.profileOrigin || saved.profileOrigin || "native")
    if (existing.migrationSourceKey && !saved.migrationSourceKey)
      saved.migrationSourceKey = existing.migrationSourceKey
    if (existing.migrationEvidence && !saved.migrationEvidence)
      saved.migrationEvidence = existing.migrationEvidence
    next.profiles[identityKey] = saved
  }

  return {
    ok: true,
    store: next,
    canonical: canonicalStringify(next),
    error: ""
  }
}

function offlineDevice(profile, key, kind, migrationState, migrationReason) {
  profile = isPlainObject(profile) ? profile : {}
  return {
    id: key,
    identityKey: kind === "profile" ? String(profile.identityKey || key) : String(profile.identityKey || ""),
    identityEvidence: String(profile.identityEvidence || ""),
    identityPortBound: profile.identityPortBound === true,
    board: profile.board || profile.nickname || "Remembered serial device",
    confidence: "remembered",
    connected: false,
    serialAvailable: false,
    mode: "offline",
    port: "",
    ports: [],
    stablePath: kind === "legacy" && key.indexOf("/dev/") === 0 ? key : "",
    vendorId: profile.vendorId || "",
    productId: profile.productId || "",
    manufacturer: profile.manufacturer || "",
    usbProduct: profile.usbProduct || "",
    serial: profile.serial || "",
    bridge: profile.bridge || "",
    driver: "",
    locked: false,
    lockPid: 0,
    readable: false,
    writable: false,
    permissions: "",
    group: "",
    profileStoreKind: kind,
    profileStoreKey: key,
    migrationState: migrationState || "",
    migrationReason: migrationReason || ""
  }
}

function offlineSortKey(device) {
  var label = String((device && (device.nickname || device.board)) || "").toLowerCase()
  return label + "\u0000" + String(device && device.profileStoreKey || "")
}

function projectDevices(connectedDevices, store) {
  var connected = Array.isArray(connectedDevices) ? connectedDevices : []
  var out = []
  var present = {}

  connected.forEach(function(device) {
    var copy = cloneValue(device)
    copy.profileStoreKind = "profile"
    copy.profileStoreKey = String(copy.identityKey || "")
    out.push(copy)
    if (copy.profileStoreKey !== "") present[copy.profileStoreKey] = true
  })

  var offline = []
  if (isPlainObject(store) && isPlainObject(store.profiles)) {
    Object.keys(store.profiles).sort().forEach(function(key) {
      if (present[key]) return
      offline.push(offlineDevice(store.profiles[key], key, "profile", "", ""))
    })
  }

  if (isPlainObject(store) && isPlainObject(store.legacyProfiles)) {
    Object.keys(store.legacyProfiles).sort().forEach(function(key) {
      var record = store.legacyProfiles[key]
      if (!isPlainObject(record) || record.migrationState === "migrated") return
      if (record.migrationState !== "unresolved" && record.migrationState !== "conflict") return
      offline.push(offlineDevice(
        record.profile,
        key,
        "legacy",
        String(record.migrationState || ""),
        String(record.migrationReason || "")
      ))
    })
  }

  offline.sort(function(a, b) {
    var ak = offlineSortKey(a)
    var bk = offlineSortKey(b)
    return ak < bk ? -1 : (ak > bk ? 1 : 0)
  })

  return out.concat(offline)
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    emptyStore: emptyStore,
    parseStore: parseStore,
    canonicalStringify: canonicalStringify,
    migrate: migrate,
    profileForDevice: profileForDevice,
    hasProfileForDevice: hasProfileForDevice,
    recordKey: recordKey,
    upsertDeviceProfile: upsertDeviceProfile,
    projectDevices: projectDevices
  }
}
