import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons
import "ProfileStore.js" as ProfileStore

Panel {
  id: root
  moduleName: "dev.usb-boards"
  ipcTarget: "dev.usb-boards"
  manageIpc: false

  property string pluginVersion: ""
  property var connectedDevices: []
  property string scanError: ""
  property bool cursorActive: false
  property int selectedIndex: 0
  property string renamingKey: ""
  property string cloneSourceKey: ""
  property string cloneTargetKey: ""
  property string cloneProbeKey: ""
  property bool cloneProbeBusy: false
  property var cloneProbeResults: ({})
  property var cloneProbeErrors: ({})
  property string cloneReadKey: ""
  property bool cloneReadBusy: false
  property var cloneReadResult: null
  property string cloneReadError: ""
  property bool offlineFoldOpen: false
  property string expandedOfflineKey: ""
  property string workbenchLeftKey: ""
  property string workbenchRightKey: ""
  readonly property int compactPanelWidth: Style.space(380)
  readonly property int widePanelWidth: Style.space(940)
  readonly property int compactPanelHeight: Style.space(600)
  readonly property int widePanelHeight: Style.space(760)
  readonly property int baudRate: Number(setting("baudRate", 115200))
  readonly property string lineEnding: String(setting("lineEnding", "lf"))
  readonly property bool sessionLogging: setting("sessionLogging", true)
  readonly property var baudOptions: [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]
  readonly property var dataFormatOptions: ["8N1", "8N2", "7E1", "7O1"]
  readonly property var legacyDeviceProfiles: parseProfiles(setting("deviceProfiles", "{}"))
  readonly property string deviceProfileStoreRaw: String(setting("deviceProfileStore", ""))
  readonly property var profileStoreResult: ProfileStore.parseStore(deviceProfileStoreRaw)
  readonly property var profileStore: profileStoreResult.ok
    ? profileStoreResult.store : ProfileStore.emptyStore()
  readonly property var devices: ProfileStore.projectDevices(connectedDevices, profileStore)
  readonly property var connectedPanelDevices: devices.filter(function(device) {
    return device.connected
  })
  readonly property var projectedOfflineDevices: devices.filter(function(device) {
    return !device.connected
  })

  readonly property var workbenchLeftDevice:
    root.deviceForIdentity(root.workbenchLeftKey)

  readonly property var workbenchRightDevice:
    root.deviceForIdentity(root.workbenchRightKey)

  readonly property var rackDevices: {
    var out = root.connectedPanelDevices.filter(function(device) {
      var key = String(device.identityKey || "")
      return key !== ""
        && key !== root.workbenchLeftKey
        && key !== root.workbenchRightKey
    })

    out.sort(function(a, b) {
      var ak = String(a.identityKey || "")
      var bk = String(b.identityKey || "")
      return ak < bk ? -1 : (ak > bk ? 1 : 0)
    })

    return out
  }

  readonly property var offlinePanelDevices:
    root.projectedOfflineDevices.filter(function(device) {
      var key = String(device.identityKey || "")
      return key === ""
        || (key !== root.workbenchLeftKey
          && key !== root.workbenchRightKey)
    })

  readonly property bool offlineVisible:
    root.connectedPanelDevices.length === 0 || root.offlineFoldOpen
  readonly property int navigationDeviceCount:
    root.connectedPanelDevices.length
      + (root.offlineVisible ? root.offlinePanelDevices.length : 0)
  readonly property bool wideMode: root.navigationDeviceCount >= 2

  readonly property bool accessRequired: devices.some(function(device) {
    return device.connected && device.serialAvailable && (!device.readable || !device.writable)
  })

  readonly property color readyTone: Qt.rgba(0.48, 0.78, 0.52, 1.0)
  readonly property color warningTone: Qt.rgba(0.90, 0.68, 0.34, 1.0)
  readonly property color offlineTone: root.bar
    ? root.bar.urgent
    : Qt.rgba(0.88, 0.38, 0.34, 1.0)
  readonly property color hairline: root.bar
    ? Qt.rgba(
        root.bar.foreground.r,
        root.bar.foreground.g,
        root.bar.foreground.b,
        0.18
      )
    : Qt.rgba(1, 1, 1, 0.12)

  readonly property string manifestPath: {
    var url = Qt.resolvedUrl("manifest.json").toString()
    return url.indexOf("file://") === 0 ? decodeURIComponent(url.substring(7)) : url
  }

  readonly property string scannerPath: {
    var url = Qt.resolvedUrl("usb_boards.py").toString()
    return url.indexOf("file://") === 0 ? decodeURIComponent(url.substring(7)) : url
  }

  readonly property string monitorPath: {
    var url = Qt.resolvedUrl("serial_monitor.py").toString()
    return url.indexOf("file://") === 0 ? decodeURIComponent(url.substring(7)) : url
  }

  readonly property string cloneBackendPath: {
    var url = Qt.resolvedUrl("usb_clone.py").toString()
    return url.indexOf("file://") === 0 ? decodeURIComponent(url.substring(7)) : url
  }

  function updatePluginVersion(raw) {
    try {
      var parsed = JSON.parse(String(raw || "{}"))
      pluginVersion = parsed && parsed.version ? String(parsed.version) : ""
    } catch (error) {
      pluginVersion = ""
    }
  }

  function refresh() {
    if (!scanProc.running) scanProc.running = true
  }

  function updateDevices(raw) {
    try {
      var parsed = JSON.parse(String(raw || "[]"))
      connectedDevices = Array.isArray(parsed) ? parsed : []
      scanError = ""
      migrateProfiles(connectedDevices)
      reconcileCloneState(connectedDevices)
      reconcileWorkbenchSlots()
      if (selectedIndex >= root.navigationDeviceCount)
        selectedIndex = Math.max(0, root.navigationDeviceCount - 1)
    } catch (error) {
      scanError = "Could not read USB device information"
    }
  }

  function copy(value) {
    if (!value) return
    Quickshell.execDetached(["bash", "-c", "printf %s " + Util.shellQuote(value) + " | wl-copy"])
  }

  function parseProfiles(value) {
    try {
      var parsed = JSON.parse(String(value || "{}"))
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {}
    } catch (error) {
      return {}
    }
  }

  function migrateProfiles(scannedDevices) {
    var result = ProfileStore.migrate(
      deviceProfileStoreRaw,
      legacyDeviceProfiles,
      scannedDevices || []
    )
    if (!result.ok || !result.changed) return
    persistSettings({ deviceProfileStore: result.canonical })
  }

  function profileKey(device) {
    return ProfileStore.recordKey(device)
  }

  function profileFor(device) {
    return ProfileStore.profileForDevice(profileStore, device)
  }

  function hasProfile(device) {
    return ProfileStore.hasProfileForDevice(profileStore, device)
  }

  function effectiveBaud(device) {
    var value = Number(profileFor(device).baudRate)
    return value > 0 ? value : root.baudRate
  }

  function effectiveLineEnding(device) {
    var value = String(profileFor(device).lineEnding || "")
    return ["none", "lf", "cr", "crlf"].indexOf(value) >= 0 ? value : root.lineEnding
  }

  function effectiveDataFormat(device) {
    var value = String(profileFor(device).dataFormat || "")
    return root.dataFormatOptions.indexOf(value) >= 0 ? value : "8N1"
  }

  function effectiveLogging(device) {
    var value = profileFor(device).sessionLogging
    return value === undefined ? root.sessionLogging : value === true
  }

  function profileData(device) {
    var current = profileFor(device)
    return {
      baudRate: effectiveBaud(device),
      lineEnding: effectiveLineEnding(device),
      dataFormat: effectiveDataFormat(device),
      sessionLogging: effectiveLogging(device),
      nickname: current.nickname || "",
      identityKey: device.identityKey || current.identityKey || "",
      identityEvidence: device.identityEvidence || current.identityEvidence || "",
      identityPortBound: device.identityPortBound === true,
      identityQuality: device.identityQuality || current.identityQuality || "",
      identificationEvidence: device.identificationEvidence || current.identificationEvidence || "",
      identificationScope: device.identificationScope || current.identificationScope || "",
      board: device.board || current.board || "USB serial device",
      vendorId: device.vendorId || current.vendorId || "",
      productId: device.productId || current.productId || "",
      manufacturer: device.manufacturer || current.manufacturer || "",
      usbProduct: device.usbProduct || current.usbProduct || "",
      serial: device.serial || current.serial || "",
      bridge: device.bridge || current.bridge || ""
    }
  }

  function persistDeviceProfile(device, changes) {
    if (!profileStoreResult.ok) return
    var data = profileData(device)
    for (var name in changes) data[name] = changes[name]
    var result = ProfileStore.upsertDeviceProfile(profileStore, device, data)
    if (!result.ok || result.canonical === profileStoreResult.canonical) return
    persistSettings({ deviceProfileStore: result.canonical })
  }

  function updateDeviceProfile(device, changes) {
    persistDeviceProfile(device, changes)
  }

  function displayName(device) {
    var nickname = String(profileFor(device).nickname || "").trim()
    return nickname !== "" ? nickname : (device && device.board ? device.board : "USB serial device")
  }

  function deviceStatus(device) {
    if (!device || !device.connected) return "DISCONNECTED"
    if (!device.serialAvailable) return String(device.mode || "usb").toUpperCase() + " MODE"
    if (!device.readable || !device.writable) return "PERMISSION NEEDED"
    if (device.locked) return "PORT IN USE"
    return "READY"
  }

  function deviceStatusTone(device) {
    if (!device || !device.connected) return root.offlineTone
    if (!device.serialAvailable
        || !device.readable
        || !device.writable
        || device.locked)
      return root.warningTone
    return root.readyTone
  }

  function validWorkbenchIdentity(device) {
    if (!device) return ""

    var key = String(device.identityKey || "")
    if (key.indexOf("usb-serial:") === 0
        || key.indexOf("usb-topology:") === 0)
      return key

    return ""
  }

  function sortedConnectedWorkbenchCandidates() {
    var candidates = []

    for (var index = 0; index < root.connectedPanelDevices.length; index++) {
      var device = root.connectedPanelDevices[index]
      var rawKey = String(device.identityKey || "")
      var key = root.validWorkbenchIdentity(device)
      if (!device.connected || rawKey === "" || key === "") continue
      candidates.push(device)
    }

    candidates.sort(function(a, b) {
      var ak = String(a.identityKey || "")
      var bk = String(b.identityKey || "")
      return ak < bk ? -1 : (ak > bk ? 1 : 0)
    })

    return candidates
  }

  function deviceForIdentity(key) {
    var identity = String(key || "")
    if (identity === "") return null

    for (var index = 0; index < root.devices.length; index++) {
      var device = root.devices[index]
      if (String(device.identityKey || "") === identity)
        return device
    }

    return null
  }

  function reconcileWorkbenchSlots() {
    var candidates = root.sortedConnectedWorkbenchCandidates()

    if (root.workbenchLeftKey === "") {
      for (var leftIndex = 0; leftIndex < candidates.length; leftIndex++) {
        var leftKey = String(candidates[leftIndex].identityKey || "")
        if (leftKey !== "" && leftKey !== root.workbenchRightKey) {
          root.workbenchLeftKey = leftKey
          break
        }
      }
    }

    if (root.workbenchRightKey === "") {
      for (var rightIndex = 0; rightIndex < candidates.length; rightIndex++) {
        var rightKey = String(candidates[rightIndex].identityKey || "")
        if (rightKey !== ""
            && rightKey !== root.workbenchLeftKey
            && rightKey !== root.workbenchRightKey) {
          root.workbenchRightKey = rightKey
          break
        }
      }
    }
  }

  function assignWorkbenchSlot(side, device) {
    var key = root.validWorkbenchIdentity(device)
    if (key === "" || !device || !device.connected) return

    if (side === "left") {
      if (root.workbenchRightKey === key) return
      root.workbenchLeftKey = key
      return
    }

    if (side === "right") {
      if (root.workbenchLeftKey === key) return
      root.workbenchRightKey = key
    }
  }

  function workbenchCloneRole(device) {
    var key = String(device && device.identityKey || "")
    if (key === "") return ""
    if (key === root.cloneSourceKey) return "SOURCE"
    if (key === root.cloneTargetKey) return "TARGET"
    return ""
  }

  function cloneIdentityKey(device) {
    if (!device || !device.connected) return ""
    return String(device.identityKey || "")
  }

  function isCloneSelected(device) {
    var key = root.cloneIdentityKey(device)
    return key !== "" && (key === root.cloneSourceKey || key === root.cloneTargetKey)
  }

  function canSelectCloneSource(device) {
    var key = root.cloneIdentityKey(device)
    return !root.cloneReadBusy && key !== "" && key !== root.cloneTargetKey
  }

  function canSelectCloneTarget(device) {
    var key = root.cloneIdentityKey(device)
    return key !== "" && key !== root.cloneSourceKey
  }

  function toggleCloneSource(device) {
    var key = root.cloneIdentityKey(device)
    if (key === "" || !root.canSelectCloneSource(device)) return
    var nextKey = root.cloneSourceKey === key ? "" : key
    if (nextKey !== root.cloneSourceKey) root.clearCloneReadEvidence()
    root.cloneSourceKey = nextKey
  }

  function toggleCloneTarget(device) {
    var key = root.cloneIdentityKey(device)
    if (key === "" || !root.canSelectCloneTarget(device)) return
    root.cloneTargetKey = root.cloneTargetKey === key ? "" : key
  }

  function cloneProbeEligible(device) {
    if (!root.isCloneSelected(device)) return false
    return !root.cloneReadBusy
      && device.connected
      && device.serialAvailable
      && device.readable
      && device.writable
      && !device.locked
  }

  function cloneProbeResultFor(device) {
    var key = String(device && device.identityKey || "")
    return key !== "" && root.cloneProbeResults[key] ? root.cloneProbeResults[key] : null
  }

  function cloneProbeErrorFor(device) {
    var key = String(device && device.identityKey || "")
    return key !== "" ? String(root.cloneProbeErrors[key] || "") : ""
  }

  function clearCloneReadEvidence() {
    root.cloneReadResult = null
    root.cloneReadError = ""
  }

  function cloneSourceReadEligible(device) {
    var key = root.cloneIdentityKey(device)
    if (key === "" || key !== root.cloneSourceKey) return false
    return !root.cloneReadBusy
      && !root.cloneProbeBusy
      && device.connected
      && device.serialAvailable
      && device.readable
      && device.writable
      && !device.locked
  }

  function startCloneSourceRead(device) {
    var key = root.cloneIdentityKey(device)
    if (key === "" || !root.cloneSourceReadEligible(device)) return
    root.clearCloneReadEvidence()
    root.cloneReadKey = key
    root.cloneReadBusy = true
    cloneReadProc.command = ["python3", root.cloneBackendPath, "read-source", "--identity-key", key]
    cloneReadProc.running = true
  }

  function validCloneSha256(value) {
    return /^[0-9a-f]{64}$/.test(String(value || ""))
  }

  function finishCloneSourceRead(raw) {
    var key = root.cloneReadKey
    if (key === "") return

    if (root.cloneSourceKey !== key) {
      root.cloneReadKey = ""
      root.cloneReadBusy = false
      root.clearCloneReadEvidence()
      return
    }

    try {
      var parsed = JSON.parse(String(raw || ""))
      if (!parsed || parsed.operation !== "read-source") throw new Error("invalid operation")
      if (parsed.status === "pass") {
        var size = Number(parsed.imageSize || 0)
        var sha256 = String(parsed.sha256 || "").toLowerCase()
        if (String(parsed.identityKey || "") !== key
            || size <= 0
            || Math.floor(size) !== size
            || !root.validCloneSha256(sha256))
          throw new Error("invalid read evidence")
        root.cloneReadResult = { identityKey: key, imageSize: size, sha256: sha256 }
        root.cloneReadError = ""
      } else {
        root.cloneReadResult = null
        root.cloneReadError = String(parsed.reason || "read-source-failed")
      }
    } catch (error) {
      root.cloneReadResult = null
      root.cloneReadError = "invalid-read-result"
    }

    root.cloneReadKey = ""
    root.cloneReadBusy = false
  }

  function cloneReadSizeLabel(result) {
    if (!result) return ""
    var size = Number(result.imageSize || 0)
    if (size > 0 && size % (1024 * 1024) === 0)
      return String(size / (1024 * 1024)) + " MiB"
    return size > 0 ? String(size) + " B" : ""
  }

  function setCloneProbeEvidence(key, probe, errorText) {
    var results = {}
    var errors = {}
    var name
    for (name in root.cloneProbeResults) {
      if (name !== key) results[name] = root.cloneProbeResults[name]
    }
    for (name in root.cloneProbeErrors) {
      if (name !== key) errors[name] = root.cloneProbeErrors[name]
    }
    if (probe) results[key] = probe
    if (errorText) errors[key] = String(errorText)
    root.cloneProbeResults = results
    root.cloneProbeErrors = errors
  }

  function reconcileCloneState(scannedDevices) {
    var connected = {}
    var list = scannedDevices || []
    for (var index = 0; index < list.length; index++) {
      var device = list[index]
      var key = device && device.connected ? String(device.identityKey || "") : ""
      if (key !== "") connected[key] = true
    }

    if (root.cloneSourceKey !== "" && !connected[root.cloneSourceKey]) {
      root.cloneSourceKey = ""
      root.clearCloneReadEvidence()
    }
    if (root.cloneTargetKey !== "" && !connected[root.cloneTargetKey])
      root.cloneTargetKey = ""

    var results = {}
    var errors = {}
    var name
    for (name in root.cloneProbeResults) {
      if (connected[name]) results[name] = root.cloneProbeResults[name]
    }
    for (name in root.cloneProbeErrors) {
      if (connected[name]) errors[name] = root.cloneProbeErrors[name]
    }
    root.cloneProbeResults = results
    root.cloneProbeErrors = errors

    if (root.cloneProbeKey !== "" && !connected[root.cloneProbeKey]) {
      if (cloneProbeProc.running) cloneProbeProc.running = false
      root.cloneProbeKey = ""
      root.cloneProbeBusy = false
    }
  }

  function startCloneProbe(device) {
    var key = root.cloneIdentityKey(device)
    if (key === "" || root.cloneProbeBusy || !root.cloneProbeEligible(device)) return
    root.setCloneProbeEvidence(key, null, "")
    root.cloneProbeKey = key
    root.cloneProbeBusy = true
    cloneProbeProc.command = ["python3", root.cloneBackendPath, "probe", "--identity-key", key]
    cloneProbeProc.running = true
  }

  function finishCloneProbe(raw) {
    var key = root.cloneProbeKey
    if (key === "") return
    try {
      var parsed = JSON.parse(String(raw || ""))
      if (!parsed || parsed.operation !== "probe") throw new Error("invalid operation")
      if (parsed.status === "pass") {
        if (String(parsed.identityKey || "") !== key || !parsed.probe || parsed.probe.ok !== true)
          throw new Error("identity mismatch")
        root.setCloneProbeEvidence(key, parsed.probe, "")
      } else {
        root.setCloneProbeEvidence(key, null, String(parsed.reason || "probe-failed"))
      }
    } catch (error) {
      root.setCloneProbeEvidence(key, null, "invalid-probe-result")
    }
    root.cloneProbeKey = ""
    root.cloneProbeBusy = false
  }

  function cloneProbeDeviceLabel(probe) {
    if (!probe) return ""
    var model = String(probe.chipModel || "UNKNOWN ESPRESSIF DEVICE")
    var revision = String(probe.chipRevision || "")
    return revision === "" ? model : model + " · " + revision
  }

  function cloneProbeFlashLabel(probe) {
    if (!probe) return ""
    var size = Number(probe.flashSize || 0)
    var sizeLabel = size > 0 && size % (1024 * 1024) === 0
      ? String(size / (1024 * 1024)) + " MiB"
      : (size > 0 ? String(size) + " B" : "FLASH SIZE UNKNOWN")
    var voltage = String(probe.flashVoltage || "")
    return voltage === "" ? sizeLabel : sizeLabel + " · " + voltage
  }

  function setDeviceBaud(device, baud) {
    var key = profileKey(device)
    if (!key || root.baudOptions.indexOf(Number(baud)) < 0) return
    updateDeviceProfile(device, { baudRate: Number(baud) })
  }

  function beginRename(device) {
    renamingKey = profileKey(device)
  }

  function saveNickname(device, nickname) {
    var name = String(nickname || "").trim()
    persistDeviceProfile(device, { nickname: name })
    renamingKey = ""
  }

  function cycleDeviceBaud(device) {
    var current = root.effectiveBaud(device)
    var index = root.baudOptions.indexOf(current)
    var next = root.baudOptions[(index + 1) % root.baudOptions.length]
    root.setDeviceBaud(device, next)
  }

  function cycleDeviceLineEnding(device) {
    var options = ["none", "lf", "cr", "crlf"]
    var index = options.indexOf(root.effectiveLineEnding(device))
    updateDeviceProfile(device, { lineEnding: options[(index + 1) % options.length] })
  }

  function cycleDeviceDataFormat(device) {
    var index = root.dataFormatOptions.indexOf(root.effectiveDataFormat(device))
    updateDeviceProfile(device, { dataFormat: root.dataFormatOptions[(index + 1) % root.dataFormatOptions.length] })
  }

  function toggleDeviceLogging(device) {
    updateDeviceProfile(device, { sessionLogging: !root.effectiveLogging(device) })
  }

  function persistSettings(values) {
    var entry = { id: root.moduleName }
    for (var existing in root.settings) if (existing !== "id") entry[existing] = root.settings[existing]
    for (var key in values) entry[key] = values[key]
    root.settings = entry
    if (root.bar && root.bar.shell && typeof root.bar.shell.updateEntryInline === "function")
      root.bar.shell.updateEntryInline(root.moduleName, entry)
  }

  function rememberProfile(device) {
    if (!device || hasProfile(device)) return
    persistDeviceProfile(device, {})
  }

  function openMonitor(device) {
    if (!device || !device.connected || !device.serialAvailable || !device.readable || !device.writable) return
    root.rememberProfile(device)
    var path = devicePath(device)
    var baud = root.effectiveBaud(device)
    var ending = root.effectiveLineEnding(device)
    var dataFormat = root.effectiveDataFormat(device)
    var command = Util.shellQuote(root.monitorPath)
      + " " + Util.shellQuote(path)
      + " --baud " + String(baud)
      + " --line-ending " + Util.shellQuote(ending)
      + " --format " + Util.shellQuote(dataFormat)
    if (root.effectiveLogging(device))
      command += " --log-dir \"${XDG_STATE_HOME:-$HOME/.local/state}/omarchy/usb-boards/sessions\""
    var heldCommand = command
      + "; status=$?; printf '\\nMonitor exited with status %s. Press Enter to close.\\n' \"$status\"; read -r"
    Quickshell.execDetached(["omarchy-launch-terminal", "bash", "-lc", heldCommand])
    root.close()
  }

  function grantAccess(device) {
    if (!device || !device.group) return
    var command = "printf 'Serial access requires adding %s to the %s group.\\n' \"$USER\" "
      + Util.shellQuote(device.group)
      + "; read -r -p 'Continue? [y/N] ' answer; case \"$answer\" in [yY]|[yY][eE][sS]) "
      + "sudo usermod -aG " + Util.shellQuote(device.group)
      + " \"$USER\" && printf '\\nAccess granted. Log out and back in before opening the monitor.\\n'"
      + " || printf '\\nCould not grant access.\\n' ;; *) printf '\\nNo changes made.\\n' ;; esac; read -r"
    Quickshell.execDetached(["omarchy-launch-terminal", "bash", "-lc", command])
    root.close()
  }

  function devicePath(device) {
    return device && device.stablePath ? device.stablePath : (device ? device.port : "")
  }

  function identityLabel(device) {
    if (!device) return "NOT RECORDED"
    if (device.identityEvidence === "usb-serial" && device.identityPortBound === false)
      return "PORTABLE"
    if (device.identityEvidence === "usb-topology" && device.identityPortBound === true)
      return "PORT-BOUND"
    return "NOT RECORDED"
  }

  function identityReasonLabel(device) {
    if (!device) return "NOT STORED"
    if (device.identityQuality === "reported") return "REPORTED USB SERIAL"
    if (device.identityQuality === "known-default") return "DEFAULT USB SERIAL"
    if (device.identityQuality === "missing") return "NO USB SERIAL"
    return "NOT STORED"
  }

  function identificationScopeLabel(device) {
    var value = String(device && device.identificationScope || "")
    return value === "" ? "NOT STORED" : value.toUpperCase()
  }

  function identificationEvidenceLabel(device) {
    var value = String(device && device.identificationEvidence || "")
    if (value === "vid-pid") return "VID/PID"
    if (value === "") return "NOT STORED"
    return value.toUpperCase()
  }

  function confidenceLabel(device) {
    if (!device) return ""
    if (!device.connected) {
      if (device.migrationState === "conflict") return "PROFILE CONFLICT"
      if (device.migrationState === "unresolved") return "PROFILE UNRESOLVED"
      return "REMEMBERED DEVICE"
    }
    if (device.confidence === "exact") return "USB-IDENTIFIED"
    if (device.confidence === "probable") return "PROBABLE BOARD"
    if (device.confidence === "bridge-only") return "BOARD UNKNOWN"
    return "USB SERIAL DEVICE"
  }

  function navigationDeviceAt(index) {
    if (index < 0 || index >= root.navigationDeviceCount) return null

    if (index < root.connectedPanelDevices.length)
      return root.connectedPanelDevices[index]

    var offlineIndex = index - root.connectedPanelDevices.length
    if (!root.offlineVisible
        || offlineIndex < 0
        || offlineIndex >= root.offlinePanelDevices.length)
      return null

    return root.offlinePanelDevices[offlineIndex]
  }

  function selectByDelta(delta) {
    if (root.navigationDeviceCount === 0) return
    selectedIndex = Math.max(
      0,
      Math.min(root.navigationDeviceCount - 1, selectedIndex + delta)
    )
  }

  function setOfflineFoldOpen(open) {
    root.offlineFoldOpen = open === true

    if (!root.offlineFoldOpen && root.connectedPanelDevices.length > 0)
      root.expandedOfflineKey = ""

    if (root.navigationDeviceCount === 0) {
      root.selectedIndex = 0
    } else if (root.selectedIndex >= root.navigationDeviceCount) {
      root.selectedIndex = root.navigationDeviceCount - 1
    }
  }

  function toggleOfflineDetails(device) {
    var key = root.profileKey(device)
    if (key === "") return
    root.expandedOfflineKey = root.expandedOfflineKey === key ? "" : key
  }

  IpcHandler {
    target: "dev.usb-boards"
    function open() { root.open() }
    function close() { root.close() }
    function show() { root.open() }
    function hide() { root.close() }
    function toggle() { root.toggle() }
    function refresh() { root.refresh() }
    function state(): string { return JSON.stringify(root.devices) }
  }

  Component.onCompleted: refresh()
  onOpenedChanged: if (opened) { refresh(); cursorActive = false }

  FileView {
    id: manifestFile
    path: root.manifestPath
    watchChanges: true
    printErrors: false
    onLoaded: root.updatePluginVersion(text())
    onLoadFailed: function(error) { root.pluginVersion = "" }
    onFileChanged: reload()
  }

  Process {
    id: scanProc
    command: ["python3", root.scannerPath]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.updateDevices(text)
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (String(text || "").trim() !== "") root.scanError = String(text).trim()
    }
  }

  Process {
    id: cloneProbeProc
    command: []
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.finishCloneProbe(text)
    }
    stderr: StdioCollector {
      waitForEnd: true
    }
  }

  Process {
    id: cloneReadProc
    command: []
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.finishCloneSourceRead(text)
    }
    stderr: StdioCollector {
      waitForEnd: true
    }
  }

  Timer {
    interval: root.opened ? 1000 : 2500
    repeat: true
    running: true
    onTriggered: root.refresh()
  }

  implicitWidth: devices.length > 0 ? button.implicitWidth : 0
  implicitHeight: devices.length > 0 ? button.implicitHeight : 0
  visible: devices.length > 0

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰕓" + (root.connectedDevices.length > 1 ? " " + root.connectedDevices.length : "")
    onPressed: function(b) { root.toggle() }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(
      root.wideMode ? root.widePanelWidth : root.compactPanelWidth
    )
    contentHeight: panel.fittedContentHeight(
      content.implicitHeight,
      root.wideMode ? root.widePanelHeight : root.compactPanelHeight
    )

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onMoveRequested: function(dx, dy) {
        if (!root.cursorActive) { root.cursorActive = true; return }
        if (dy !== 0) root.selectByDelta(dy)
      }
      onActivateRequested: {
        if (!root.cursorActive) return
        var device = root.navigationDeviceAt(root.selectedIndex)
        if (device) root.copy(root.devicePath(device))
      }
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(text) { if (text === "r" || text === "R") root.refresh() }

      ScrollView {
        id: deviceScroll
        anchors.fill: parent
        contentWidth: availableWidth
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

        Column {
          id: content
          width: parent.width
          spacing: Style.space(12)

          Item {
            width: parent.width
            implicitHeight: Math.max(heroIcon.implicitHeight, heroText.implicitHeight)

            Text {
              id: heroIcon
              text: "󰕓"
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.display
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
            }

            Column {
              id: heroText
              anchors.left: heroIcon.right
              anchors.leftMargin: Style.space(14)
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)

              Text {
                text: root.connectedDevices.length + " connected"
                  + (root.offlinePanelDevices.length > 0
                    ? " · " + root.offlinePanelDevices.length + " offline" : "")
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.title
                font.bold: true
              }
              Text {
                text: root.accessRequired ? "PERMISSION REQUIRED"
                  : (root.connectedDevices.length > 0 ? "DEVICES READY" : "SAVED DEVICES OFFLINE")
                color: root.accessRequired
                  ? root.warningTone
                  : (root.connectedDevices.length > 0
                    ? root.readyTone : root.offlineTone)
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
                font.letterSpacing: 1.2
              }
            }
          }

          Text {
            visible: root.scanError !== ""
            text: root.scanError
            color: root.bar.urgent
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.body
            wrapMode: Text.Wrap
            width: parent.width
          }

          Text {
            text: "ACTIVE WORKBENCH"
            color: root.bar.foreground
            opacity: 0.58
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
            font.letterSpacing: 1.2
          }

          Grid {
            id: workbenchGrid
            width: parent.width
            columns: root.wideMode ? 2 : 1
            columnSpacing: Style.space(14)
            rowSpacing: Style.space(12)

            WorkbenchSlot {
              slotLabel: "LEFT"
              slotKey: root.workbenchLeftKey
              modelData: root.workbenchLeftDevice
              navigationIndex: 0
              width: root.wideMode
                ? (workbenchGrid.width - workbenchGrid.columnSpacing) / 2
                : workbenchGrid.width
            }

            WorkbenchSlot {
              slotLabel: "RIGHT"
              slotKey: root.workbenchRightKey
              modelData: root.workbenchRightDevice
              navigationIndex: root.workbenchLeftDevice !== null ? 1 : 0
              width: root.wideMode
                ? (workbenchGrid.width - workbenchGrid.columnSpacing) / 2
                : workbenchGrid.width
            }
          }
          }

          Column {
            id: offlineSection
            visible: root.offlinePanelDevices.length > 0
            width: parent.width
            spacing: Style.space(6)

            PanelSeparator {
              width: parent.width
              foreground: root.hairline
            }

            Item {
              id: offlineHeader
              width: parent.width
              implicitHeight: Math.max(
                offlineHeaderText.implicitHeight,
                offlineFoldButton.visible ? offlineFoldButton.implicitHeight : 0
              )

              Text {
                id: offlineHeaderText
                text: "REMEMBERED OFFLINE DEVICES · "
                  + root.offlinePanelDevices.length
                color: root.bar.foreground
                opacity: 0.58
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
                font.letterSpacing: 1.0
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
              }

              CloneActionButton {
                id: offlineFoldButton
                visible: root.connectedPanelDevices.length > 0
                label: root.offlineFoldOpen ? "HIDE" : "SHOW"
                active: root.offlineFoldOpen
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                tooltipText: root.offlineFoldOpen
                  ? "Hide remembered offline devices"
                  : "Show remembered offline devices"
                onActivated: root.setOfflineFoldOpen(!root.offlineFoldOpen)
              }
            }

            Column {
              visible: root.offlineVisible
              width: parent.width
              spacing: Style.space(4)

              Repeater {
                model: root.offlinePanelDevices

                OfflineDeviceRow {
                  width: parent.width
                }
              }
            }
          }

          Item {
            width: parent.width
            implicitHeight: defaultsFooter.implicitHeight
              + (versionFooter.visible ? versionFooter.implicitHeight + Style.space(2) : 0)

            Text {
              id: defaultsFooter
              text: "Defaults · " + root.baudRate + " baud · " + root.lineEnding
                + " · logs " + (root.sessionLogging ? "on" : "off") + " · R refreshes"
              color: Qt.darker(root.bar.foreground, 1.4)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              width: parent.width
              horizontalAlignment: Text.AlignHCenter
            }

            Text {
              id: versionFooter
              visible: root.pluginVersion !== ""
              text: "v" + root.pluginVersion
              color: root.bar.foreground
              opacity: 0.28
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              anchors.top: defaultsFooter.bottom
              anchors.topMargin: Style.space(2)
              anchors.right: parent.right
            }
          }
        }
      }
    }
  }

  component WorkbenchDeviceCard: Column {
    id: deviceColumn
    required property var modelData
    required property int navigationIndex
    width: parent ? parent.width : 0
    spacing: Style.space(8)

    PanelSeparator {
      visible: deviceColumn.navigationIndex > 0
        && (!root.wideMode || deviceColumn.navigationIndex >= 2)
      foreground: root.hairline
    }

  CursorSurface {
    id: deviceRow
    width: parent.width
    implicitHeight: boardInfo.implicitHeight + Style.space(16)
    hasCursor: root.cursorActive && root.selectedIndex === deviceColumn.navigationIndex
    foreground: root.bar.foreground
    outline: false
    radius: 0

    Column {
      id: boardInfo
      z: 1
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.margins: Style.space(10)
      spacing: Style.space(3)

      Item {
        width: parent.width
        implicitHeight: nameField.visible ? nameField.implicitHeight : deviceName.implicitHeight

        Text {
          id: deviceName
          visible: !nameField.visible
          text: root.displayName(deviceColumn.modelData)
          color: root.bar.foreground
          opacity: deviceColumn.modelData.connected ? 1.0 : 0.45
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.subtitle
          font.bold: true
          elide: Text.ElideRight
          width: parent.width
        }

        TextField {
          id: nameField
          visible: root.renamingKey === root.profileKey(deviceColumn.modelData)
          text: root.displayName(deviceColumn.modelData)
          placeholderText: "Device name"
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.bodySmall
          foreground: root.bar.foreground
          horizontalPadding: Style.space(6)
          verticalPadding: Style.space(3)
          width: parent.width
          onAccepted: root.saveNickname(deviceColumn.modelData, text)
        }
      }
      Text {
        text: root.deviceStatus(deviceColumn.modelData) + " · " + root.confidenceLabel(deviceColumn.modelData)
        color: root.deviceStatusTone(deviceColumn.modelData)
        opacity: deviceColumn.modelData.connected
          && deviceColumn.modelData.readable
          && deviceColumn.modelData.writable ? 0.78 : 1.0
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        font.letterSpacing: 1.0
      }

      Row {
        id: cloneActions
        visible: deviceColumn.modelData.connected
        spacing: Style.space(5)

        CloneActionButton {
          label: "SOURCE"
          active: root.cloneSourceKey === root.cloneIdentityKey(deviceColumn.modelData)
          enabled: root.canSelectCloneSource(deviceColumn.modelData)
          tooltipText: active ? "Clear SOURCE role" : "Select this connected device as SOURCE"
          onActivated: root.toggleCloneSource(deviceColumn.modelData)
        }

        CloneActionButton {
          label: "TARGET"
          active: root.cloneTargetKey === root.cloneIdentityKey(deviceColumn.modelData)
          enabled: root.canSelectCloneTarget(deviceColumn.modelData)
          tooltipText: active ? "Clear TARGET role" : "Select this connected device as TARGET"
          onActivated: root.toggleCloneTarget(deviceColumn.modelData)
        }

        CloneActionButton {
          label: root.cloneProbeBusy
            && root.cloneProbeKey === root.cloneIdentityKey(deviceColumn.modelData)
            ? "PROBING" : "PROBE"
          enabled: !root.cloneProbeBusy && root.cloneProbeEligible(deviceColumn.modelData)
          tooltipText: root.isCloneSelected(deviceColumn.modelData)
            ? "Probe selected device · board resets"
            : "Select SOURCE or TARGET first"
          onActivated: root.startCloneProbe(deviceColumn.modelData)
        }

        CloneActionButton {
          label: root.cloneReadBusy
            && root.cloneReadKey === root.cloneIdentityKey(deviceColumn.modelData)
            ? "READING" : "READ SOURCE"
          enabled: root.cloneSourceReadEligible(deviceColumn.modelData)
          tooltipText: root.cloneSourceKey === root.cloneIdentityKey(deviceColumn.modelData)
            ? "Read complete SOURCE flash · board resets"
            : "Select SOURCE first"
          onActivated: root.startCloneSourceRead(deviceColumn.modelData)
        }
      }

      Text {
        visible: cloneActions.visible
          && root.isCloneSelected(deviceColumn.modelData)
        text: "PROBE RESETS BOARD"
        color: root.bar.urgent
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        font.letterSpacing: 1.0
      }

      Text {
        visible: cloneActions.visible
          && root.cloneSourceKey === root.cloneIdentityKey(deviceColumn.modelData)
        text: "READ SOURCE · RESETS BOARD"
        color: root.bar.urgent
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        font.letterSpacing: 1.0
      }

      Column {
        id: cloneEvidence
        width: parent.width
        spacing: Style.space(1)
        readonly property var evidence: root.cloneProbeResultFor(deviceColumn.modelData)
        readonly property string probeError: root.cloneProbeErrorFor(deviceColumn.modelData)
        readonly property var readResult: root.cloneReadResult
          && root.cloneReadResult.identityKey === String(deviceColumn.modelData.identityKey || "")
          ? root.cloneReadResult : null
        readonly property string readError: root.cloneSourceKey === String(deviceColumn.modelData.identityKey || "")
          ? root.cloneReadError : ""
        readonly property string identityKey: String(deviceColumn.modelData.identityKey || "")
        visible: evidence !== null
          || probeError !== ""
          || readResult !== null
          || readError !== ""
          || root.cloneSourceKey === identityKey
          || root.cloneTargetKey === identityKey
          || (root.cloneProbeBusy && root.cloneProbeKey === identityKey)
          || (root.cloneReadBusy && root.cloneReadKey === identityKey)

        Text {
          visible: root.cloneProbeBusy && root.cloneProbeKey === cloneEvidence.identityKey
          text: "ACTIVE PROBE · RUNNING"
          color: root.bar.foreground
          opacity: 0.65
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }

        Text {
          visible: cloneEvidence.probeError !== ""
          text: "ACTIVE PROBE FAILED · " + cloneEvidence.probeError
          color: root.bar.urgent
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
          elide: Text.ElideRight
          width: parent.width
        }

        Text {
          visible: cloneEvidence.evidence !== null
          text: "ACTIVE PROBE · " + root.cloneProbeDeviceLabel(cloneEvidence.evidence)
          color: root.bar.foreground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.bodySmall
          font.bold: true
          elide: Text.ElideRight
          width: parent.width
        }

        Text {
          visible: cloneEvidence.evidence !== null
          text: root.cloneProbeFlashLabel(cloneEvidence.evidence)
          color: root.bar.foreground
          opacity: 0.65
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
        }

        Text {
          visible: cloneEvidence.evidence !== null
            && root.cloneSourceKey === cloneEvidence.identityKey
          text: "SOURCE PROBE PASS"
          color: root.bar.foreground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
          font.letterSpacing: 1.0
        }

        Text {
          visible: root.cloneReadBusy && root.cloneReadKey === cloneEvidence.identityKey
          text: "SOURCE READ · RUNNING"
          color: root.bar.foreground
          opacity: 0.65
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }

        Item {
          id: sourceReadProgress
          visible: root.cloneReadBusy && root.cloneReadKey === cloneEvidence.identityKey
          width: parent.width
          height: Style.space(2)
          clip: true

          Rectangle {
            anchors.fill: parent
            color: root.bar.foreground
            opacity: 0.10
          }

          Rectangle {
            id: sourceReadProgressSegment
            width: Math.max(Style.space(42), sourceReadProgress.width * 0.22)
            height: parent.height
            color: root.bar.foreground
            opacity: 0.55

            NumberAnimation on x {
              running: sourceReadProgress.visible
              loops: Animation.Infinite
              from: -sourceReadProgressSegment.width
              to: sourceReadProgress.width
              duration: 1100
              easing.type: Easing.Linear
            }
          }
        }

        Text {
          visible: cloneEvidence.readError !== ""
          text: "SOURCE READ FAILED · " + cloneEvidence.readError
          color: root.bar.urgent
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
          elide: Text.ElideRight
          width: parent.width
        }

        Text {
          visible: cloneEvidence.readResult !== null
          text: "SOURCE READ PASS · " + root.cloneReadSizeLabel(cloneEvidence.readResult)
          color: root.bar.foreground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
          font.letterSpacing: 1.0
        }

        Text {
          visible: cloneEvidence.readResult !== null
          text: "SHA-256 " + (cloneEvidence.readResult ? cloneEvidence.readResult.sha256 : "")
          color: root.bar.foreground
          opacity: 0.75
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          width: parent.width
          wrapMode: Text.WrapAnywhere
        }

        Text {
          visible: root.cloneTargetKey === cloneEvidence.identityKey
          text: "TARGET WRITE LOCKED"
          color: root.bar.foreground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
          font.letterSpacing: 1.0
        }
      }

      Row {
        id: deviceActions
        spacing: Style.space(5)
        opacity: deviceColumn.modelData.connected ? 1.0 : 0.45

        PanelActionButton {
          iconText: root.renamingKey === root.profileKey(deviceColumn.modelData) ? "󰄬" : "󰏫"
          foreground: root.bar.foreground
          fontFamily: root.bar.fontFamily
          fontSize: Style.font.bodySmall
          size: Style.space(24)
          bordered: true
          radius: 0
          tooltipText: root.renamingKey === root.profileKey(deviceColumn.modelData)
            ? "Save device name" : "Set a friendly name for this device"
          onClicked: {
            if (root.renamingKey === root.profileKey(deviceColumn.modelData)) {
              root.saveNickname(deviceColumn.modelData, nameField.text)
            } else {
              root.beginRename(deviceColumn.modelData)
              Qt.callLater(function() {
                nameField.forceActiveFocus()
                nameField.selectAll()
              })
            }
          }
        }

        PanelActionButton {
          iconText: "󰆏"
          visible: root.devicePath(deviceColumn.modelData) !== ""
          foreground: root.bar.foreground
          fontFamily: root.bar.fontFamily
          fontSize: Style.font.bodySmall
          size: Style.space(24)
          bordered: true
          radius: 0
          tooltipText: "Copy stable device path"
          onClicked: root.copy(root.devicePath(deviceColumn.modelData))
        }

        PanelActionButton {
          iconText: deviceColumn.modelData.readable && deviceColumn.modelData.writable ? "󰆍" : "󰌾"
          visible: deviceColumn.modelData.connected && deviceColumn.modelData.serialAvailable
          foreground: root.bar.foreground
          fontFamily: root.bar.fontFamily
          fontSize: Style.font.bodySmall
          size: Style.space(24)
          bordered: true
          radius: 0
          tooltipText: deviceColumn.modelData.readable && deviceColumn.modelData.writable
            ? "Open serial monitor at " + root.effectiveBaud(deviceColumn.modelData) + " baud"
            : "Add your user to the " + deviceColumn.modelData.group + " group"
          onClicked: {
            if (deviceColumn.modelData.readable && deviceColumn.modelData.writable)
              root.openMonitor(deviceColumn.modelData)
            else
              root.grantAccess(deviceColumn.modelData)
          }
        }
      }
      GridLayout {
        id: deviceDetails
        width: parent.width
        opacity: deviceColumn.modelData.connected ? 1.0 : 0.45
        columns: 4
        columnSpacing: Style.space(12)
        rowSpacing: Style.space(2)

        CompactLabel { text: "PORT" }
        CompactValue { text: deviceColumn.modelData.port || "Not connected" }
        CompactLabel { text: "USB ID" }
        CompactValue {
          text: deviceColumn.modelData.vendorId
            ? deviceColumn.modelData.vendorId + ":" + deviceColumn.modelData.productId : "Not recorded"
        }

        CompactLabel { text: "SERIAL" }
        CompactValue { text: deviceColumn.modelData.serial || "Not reported" }
        CompactLabel { text: "INTERFACE" }
        CompactValue {
          text: deviceColumn.modelData.bridge || deviceColumn.modelData.driver
            || String(deviceColumn.modelData.mode || "USB").toUpperCase()
        }

        GridLayout {
          id: identityEvidenceDetails
          Layout.columnSpan: 4
          Layout.fillWidth: true
          columns: 2
          columnSpacing: Style.space(12)
          rowSpacing: Style.space(2)

          CompactLabel { text: "IDENTITY" }
          CompactValue { text: root.identityLabel(deviceColumn.modelData) }

          CompactLabel { text: "BASIS" }
          CompactValue { text: root.identityReasonLabel(deviceColumn.modelData) }

          CompactLabel { text: "BOARD SCOPE" }
          CompactValue { text: root.identificationScopeLabel(deviceColumn.modelData) }

          CompactLabel { text: "EVIDENCE" }
          CompactValue { text: root.identificationEvidenceLabel(deviceColumn.modelData) }
        }

        CompactLabel { text: "LOCK" }
        CompactValue {
          text: !deviceColumn.modelData.serialAvailable ? "Not applicable"
            : deviceColumn.modelData.locked
            ? "In use" + (deviceColumn.modelData.lockPid ? " (PID " + deviceColumn.modelData.lockPid + ")" : "")
            : "Available"
          urgent: deviceColumn.modelData.locked
        }
        CompactLabel { text: "ACCESS" }
        CompactValue {
          text: !deviceColumn.modelData.connected ? "Offline"
            : !deviceColumn.modelData.serialAvailable ? "No serial port"
            : deviceColumn.modelData.readable && deviceColumn.modelData.writable
            ? "Read/write"
            : "Join " + (deviceColumn.modelData.group || "device group")
              + " (" + deviceColumn.modelData.permissions + ")"
          urgent: !(deviceColumn.modelData.readable && deviceColumn.modelData.writable)
        }

        CompactLabel { text: "PATH" }
        CompactValue {
          text: deviceColumn.modelData.stablePath || "Not available"
          Layout.columnSpan: 3
        }

        CompactLabel { text: "SERIAL" }
        Row {
          visible: deviceColumn.modelData.serialAvailable || !deviceColumn.modelData.connected
          Layout.columnSpan: 3
          spacing: Style.space(5)

          ProfilePill {
            id: baudSelector
            label: String(root.effectiveBaud(deviceColumn.modelData))
            active: root.hasProfile(deviceColumn.modelData)
            tooltipText: active ? "Saved baud rate · click to change" : "Default baud rate · click to change"
            onActivated: root.cycleDeviceBaud(deviceColumn.modelData)
          }
          ProfilePill {
            label: root.effectiveLineEnding(deviceColumn.modelData).toUpperCase()
            active: root.hasProfile(deviceColumn.modelData)
            tooltipText: "Line ending · click to cycle"
            onActivated: root.cycleDeviceLineEnding(deviceColumn.modelData)
          }
          ProfilePill {
            label: root.effectiveDataFormat(deviceColumn.modelData)
            active: root.hasProfile(deviceColumn.modelData)
            tooltipText: "Serial format · click to cycle"
            onActivated: root.cycleDeviceDataFormat(deviceColumn.modelData)
          }
          ProfilePill {
            label: root.effectiveLogging(deviceColumn.modelData) ? "LOG" : "NO LOG"
            active: root.effectiveLogging(deviceColumn.modelData)
            tooltipText: "Session logging · click to toggle"
            onActivated: root.toggleDeviceLogging(deviceColumn.modelData)
          }
        }
      }
    }

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onContainsMouseChanged: if (containsMouse) {
        root.cursorActive = true
        root.selectedIndex = deviceColumn.navigationIndex
      }
      onClicked: root.copy(root.devicePath(deviceColumn.modelData))
    }

  }

  component WorkbenchSlot: Column {
    id: workbenchSlot

    required property string slotLabel
    required property string slotKey
    required property var modelData
    required property int navigationIndex

    width: parent ? parent.width : 0
    spacing: Style.space(5)

    Text {
      text: workbenchSlot.slotLabel
      color: root.bar.foreground
      opacity: 0.45
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
      font.letterSpacing: 1.2
    }

    Loader {
      id: workbenchCardLoader
      width: parent.width
      active: workbenchSlot.modelData !== null

      sourceComponent: Component {
        WorkbenchDeviceCard {
          modelData: workbenchSlot.modelData
          navigationIndex: workbenchSlot.navigationIndex
          width: workbenchSlot.width
        }
      }
    }

    Column {
      visible: !workbenchCardLoader.active
      width: parent.width
      spacing: Style.space(3)

      Text {
        text: workbenchSlot.slotKey === ""
          ? "EMPTY SLOT"
          : "RESERVED DEVICE"
        color: root.bar.foreground
        opacity: 0.65
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.subtitle
        font.bold: true
      }

      Text {
        visible: workbenchSlot.slotKey !== ""
        text: workbenchSlot.slotKey
        color: root.bar.foreground
        opacity: 0.45
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideMiddle
        width: parent.width
      }
    }
  }

  component OfflineDeviceRow: CursorSurface {
    required property var modelData
    required property int index

    readonly property int navigationIndex:
      root.connectedPanelDevices.length + index
    readonly property bool detailsOpen:
      root.expandedOfflineKey === root.profileKey(modelData)

    width: parent ? parent.width : 0
    implicitHeight: offlineBody.implicitHeight + Style.space(12)
    hasCursor: root.cursorActive && root.selectedIndex === navigationIndex
    foreground: root.bar.foreground
    outline: false
    radius: 0
    opacity: 0.72

    Column {
      id: offlineBody
      z: 1
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.margins: Style.space(6)
      spacing: Style.space(3)

      Item {
        width: parent.width
        implicitHeight: Math.max(
          offlineName.visible
            ? offlineName.implicitHeight
            : offlineNameField.implicitHeight,
          offlineDetailsHint.implicitHeight
        )

        Text {
          id: offlineName
          visible: !offlineNameField.visible
          text: root.displayName(modelData)
          color: root.bar.foreground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.subtitle
          font.bold: true
          elide: Text.ElideRight
          anchors.left: parent.left
          anchors.right: offlineDetailsHint.left
          anchors.rightMargin: Style.space(10)
          anchors.verticalCenter: parent.verticalCenter
        }

        TextField {
          id: offlineNameField
          visible: root.renamingKey === root.profileKey(modelData)
          text: root.displayName(modelData)
          placeholderText: "Device name"
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.bodySmall
          foreground: root.bar.foreground
          horizontalPadding: Style.space(6)
          verticalPadding: Style.space(3)
          anchors.left: parent.left
          anchors.right: offlineDetailsHint.left
          anchors.rightMargin: Style.space(10)
          onAccepted: root.saveNickname(modelData, text)
        }

        Text {
          id: offlineDetailsHint
          text: detailsOpen ? "LESS" : "DETAILS"
          color: root.bar.foreground
          opacity: 0.55
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
        }
      }

      Text {
        text: root.deviceStatus(modelData) + " · " + root.confidenceLabel(modelData)
        color: root.offlineTone
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        font.letterSpacing: 1.0
      }

      Column {
        visible: detailsOpen
        width: parent.width
        spacing: Style.space(2)

        DetailLine {
          label: "USB ID"
          value: modelData.vendorId
            ? modelData.vendorId + ":" + modelData.productId
            : "Not recorded"
        }

        DetailLine {
          label: "SERIAL"
          value: modelData.serial || "Not reported"
        }

        DetailLine {
          label: "INTERFACE"
          value: modelData.bridge || modelData.driver
            || String(modelData.mode || "USB").toUpperCase()
        }

        DetailLine {
          label: "IDENTITY"
          value: root.identityLabel(modelData)
        }

        DetailLine {
          label: "BASIS"
          value: root.identityReasonLabel(modelData)
        }

        DetailLine {
          label: "PATH"
          value: modelData.stablePath || "Not available"
        }

        Row {
          spacing: Style.space(5)

          PanelActionButton {
            iconText: root.renamingKey === root.profileKey(modelData)
              ? "󰄬" : "󰏫"
            foreground: root.bar.foreground
            fontFamily: root.bar.fontFamily
            fontSize: Style.font.bodySmall
            size: Style.space(24)
            bordered: true
            radius: 0
            tooltipText: root.renamingKey === root.profileKey(modelData)
              ? "Save device name"
              : "Set a friendly name for this device"
            onClicked: {
              if (root.renamingKey === root.profileKey(modelData)) {
                root.saveNickname(modelData, offlineNameField.text)
              } else {
                root.beginRename(modelData)
                Qt.callLater(function() {
                  offlineNameField.forceActiveFocus()
                  offlineNameField.selectAll()
                })
              }
            }
          }

          ProfilePill {
            label: String(root.effectiveBaud(modelData))
            active: root.hasProfile(modelData)
            tooltipText: "Saved baud rate · click to change"
            onActivated: root.cycleDeviceBaud(modelData)
          }

          ProfilePill {
            label: root.effectiveLineEnding(modelData).toUpperCase()
            active: root.hasProfile(modelData)
            tooltipText: "Line ending · click to cycle"
            onActivated: root.cycleDeviceLineEnding(modelData)
          }

          ProfilePill {
            label: root.effectiveDataFormat(modelData)
            active: root.hasProfile(modelData)
            tooltipText: "Serial format · click to cycle"
            onActivated: root.cycleDeviceDataFormat(modelData)
          }

          ProfilePill {
            label: root.effectiveLogging(modelData) ? "LOG" : "NO LOG"
            active: root.effectiveLogging(modelData)
            tooltipText: "Session logging · click to toggle"
            onActivated: root.toggleDeviceLogging(modelData)
          }
        }
      }
    }

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onContainsMouseChanged: if (containsMouse) {
        root.cursorActive = true
        root.selectedIndex = navigationIndex
      }
      onClicked: root.toggleOfflineDetails(modelData)
    }
  }

  component CloneActionButton: Rectangle {
    property string label: ""
    property bool active: false
    property string tooltipText: ""
    signal activated()

    width: Math.max(Style.space(72), cloneActionText.implicitWidth + Style.space(18))
    height: Style.space(24)
    radius: 0
    color: active ? Qt.rgba(1, 1, 1, 0.10) : "transparent"
    border.width: 1
    border.color: active ? root.bar.foreground : root.hairline
    opacity: enabled ? 1.0 : 0.35

    Text {
      id: cloneActionText
      anchors.centerIn: parent
      text: parent.label
      color: root.bar.foreground
      opacity: parent.active ? 1.0 : 0.78
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: parent.active
    }

    MouseArea {
      id: cloneActionMouse
      anchors.fill: parent
      enabled: parent.enabled
      cursorShape: parent.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
      hoverEnabled: true
      onClicked: parent.activated()
    }

    ToolTip.visible: cloneActionMouse.containsMouse && tooltipText !== ""
    ToolTip.text: tooltipText
    ToolTip.delay: 500
  }

  component ProfilePill: Rectangle {
    property string label: ""
    property bool active: false
    property string tooltipText: ""
    signal activated()

    width: Math.max(Style.space(58), profileText.implicitWidth + Style.space(20))
    height: Style.space(24)
    radius: 0
    color: active ? Qt.rgba(1, 1, 1, 0.10) : "transparent"
    border.width: 1
    border.color: active ? root.bar.foreground : root.hairline

    Text {
      id: profileText
      anchors.centerIn: parent
      text: parent.label
      color: root.bar.foreground
      opacity: parent.active ? 1.0 : 0.78
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: parent.active
    }

    MouseArea {
      id: profileMouse
      anchors.fill: parent
      cursorShape: Qt.PointingHandCursor
      hoverEnabled: true
      onClicked: parent.activated()
    }

    ToolTip.visible: profileMouse.containsMouse
    ToolTip.text: tooltipText
    ToolTip.delay: 500
  }

  component CompactLabel: Text {
    color: root.bar.foreground
    opacity: 0.45
    font.family: root.bar.fontFamily
    font.pixelSize: Style.font.bodySmall
    Layout.alignment: Qt.AlignVCenter
  }

  component CompactValue: Text {
    property bool urgent: false
    color: urgent ? root.bar.urgent : root.bar.foreground
    opacity: urgent ? 1.0 : 0.92
    font.family: root.bar.fontFamily
    font.pixelSize: Style.font.bodySmall
    horizontalAlignment: Text.AlignRight
    elide: Text.ElideMiddle
    Layout.fillWidth: true
    Layout.minimumWidth: 0
    Layout.alignment: Qt.AlignVCenter
  }

  component DetailLine: Item {
    required property string label
    required property string value
    property bool urgent: false
    width: parent.width
    implicitHeight: Math.max(detailLabel.implicitHeight, detailValue.implicitHeight)

    Text {
      id: detailLabel
      text: parent.label
      color: root.bar.foreground
      opacity: 0.45
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.bodySmall
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(82)
    }
    Text {
      id: detailValue
      text: parent.value
      color: parent.urgent ? root.bar.urgent : root.bar.foreground
      opacity: parent.urgent ? 1.0 : 0.92
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.bodySmall
      anchors.left: detailLabel.right
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      elide: Text.ElideMiddle
      horizontalAlignment: Text.AlignRight
    }
  }
}
