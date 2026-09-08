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
  readonly property bool wideMode: root.devices.length >= 2
  readonly property int compactPanelWidth: Style.space(380)
  readonly property int widePanelWidth: Style.space(760)
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
  readonly property bool accessRequired: devices.some(function(device) {
    return device.connected && device.serialAvailable && (!device.readable || !device.writable)
  })

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
      if (selectedIndex >= devices.length) selectedIndex = Math.max(0, devices.length - 1)
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

  function selectByDelta(delta) {
    if (devices.length === 0) return
    selectedIndex = Math.max(0, Math.min(devices.length - 1, selectedIndex + delta))
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
        if (root.cursorActive && root.selectedIndex < root.devices.length)
          root.copy(root.devicePath(root.devices[root.selectedIndex]))
      }
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(text) { if (text === "r" || text === "R") root.refresh() }

      ScrollView {
        anchors.fill: parent
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
                  + (root.devices.length > root.connectedDevices.length
                    ? " · " + (root.devices.length - root.connectedDevices.length) + " offline" : "")
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.title
                font.bold: true
              }
              Text {
                text: root.accessRequired ? "PERMISSION REQUIRED"
                  : (root.connectedDevices.length > 0 ? "DEVICES READY" : "SAVED DEVICES OFFLINE")
                color: root.accessRequired ? root.bar.urgent : Qt.darker(root.bar.foreground, 1.4)
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

          Grid {
            id: deviceGrid
            width: parent.width
            columns: root.wideMode ? 2 : 1
            columnSpacing: Style.space(12)
            rowSpacing: Style.space(12)

            Repeater {
              model: root.devices

              Column {
                id: deviceColumn
                required property var modelData
                required property int index
                width: root.wideMode
                  ? (deviceGrid.width - deviceGrid.columnSpacing) / 2
                  : deviceGrid.width
                spacing: Style.space(8)

                PanelSeparator {
                  visible: !root.wideMode && deviceColumn.index > 0
                foreground: root.bar.foreground
              }

              CursorSurface {
                id: deviceRow
                width: parent.width
                implicitHeight: boardInfo.implicitHeight + Style.space(16)
                hasCursor: root.cursorActive && root.selectedIndex === deviceColumn.index
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
                    color: deviceColumn.modelData.readable && deviceColumn.modelData.writable
                      ? root.bar.foreground : root.bar.urgent
                    opacity: deviceColumn.modelData.readable && deviceColumn.modelData.writable ? 0.6 : 1.0
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.caption
                    font.bold: true
                    font.letterSpacing: 1.0
                  }
                  Row {
                    id: deviceActions
                    spacing: Style.space(5)

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
                    root.selectedIndex = deviceColumn.index
                  }
                  onClicked: root.copy(root.devicePath(deviceColumn.modelData))
                }

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
    border.color: active ? root.bar.foreground : Qt.darker(root.bar.foreground, 1.35)

    Text {
      id: profileText
      anchors.centerIn: parent
      text: parent.label
      color: root.bar.foreground
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
    opacity: 0.6
    font.family: root.bar.fontFamily
    font.pixelSize: Style.font.bodySmall
    Layout.alignment: Qt.AlignVCenter
  }

  component CompactValue: Text {
    property bool urgent: false
    color: urgent ? root.bar.urgent : root.bar.foreground
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
      opacity: 0.6
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
