from pathlib import Path
import unittest


class CloneUiLayoutContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("Panel.qml").read_text()

    def test_panel_has_adaptive_wide_mode(self):
        self.assertIn("readonly property bool wideMode", self.source)
        self.assertIn(
            "root.navigationDeviceCount >= 2",
            self.source,
        )
        self.assertIn("compactPanelWidth", self.source)
        self.assertIn("widePanelWidth", self.source)
        self.assertIn("compactPanelHeight", self.source)
        self.assertIn("widePanelHeight", self.source)

    def test_panel_dimensions_follow_wide_mode(self):
        self.assertIn(
            "root.wideMode ? root.widePanelWidth : root.compactPanelWidth",
            self.source,
        )
        self.assertIn(
            "root.wideMode ? root.widePanelHeight : root.compactPanelHeight",
            self.source,
        )

    def test_multi_device_area_uses_two_column_grid(self):
        normalized = " ".join(self.source.split())
        self.assertIn("Grid { id: deviceGrid", normalized)
        self.assertIn("columns: root.wideMode ? 2 : 1", normalized)
        self.assertIn(
            "width: root.wideMode ? "
            "(deviceGrid.width - deviceGrid.columnSpacing) / 2 "
            ": deviceGrid.width",
            normalized,
        )

    def test_separators_preserve_device_row_boundaries(self):
        normalized = " ".join(self.source.split())
        self.assertIn(
            "visible: deviceColumn.index > 0 "
            "&& (!root.wideMode || deviceColumn.index >= 2)",
            normalized,
        )

    def test_horizontal_scroll_remains_disabled(self):
        self.assertIn(
            "ScrollBar.horizontal.policy: ScrollBar.AlwaysOff",
            self.source,
        )

    def test_scroll_content_uses_full_available_width(self):
        normalized = " ".join(self.source.split())
        self.assertIn("id: deviceScroll", normalized)
        self.assertIn("contentWidth: availableWidth", normalized)


class CloneUiRoleProbeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("Panel.qml").read_text()

    def test_clone_role_state_is_runtime_only(self):
        self.assertIn('property string cloneSourceKey: ""', self.source)
        self.assertIn('property string cloneTargetKey: ""', self.source)
        self.assertIn('property var cloneProbeResults: ({})', self.source)
        self.assertNotIn('persistSettings({ cloneSourceKey', self.source)
        self.assertNotIn('persistDeviceProfile(device, { cloneSourceKey', self.source)

    def test_clone_roles_require_connected_identity(self):
        self.assertIn("function cloneIdentityKey(device)", self.source)
        self.assertIn('if (!device || !device.connected) return ""', self.source)
        self.assertIn('return String(device.identityKey || "")', self.source)

    def test_source_and_target_are_mutually_exclusive(self):
        self.assertIn("function canSelectCloneSource(device)", self.source)
        self.assertIn("function canSelectCloneTarget(device)", self.source)
        self.assertIn("key !== root.cloneTargetKey", self.source)
        self.assertIn("key !== root.cloneSourceKey", self.source)

    def test_probe_uses_backend_identity_key_only(self):
        self.assertIn("readonly property string cloneBackendPath", self.source)
        self.assertIn(
            '["python3", root.cloneBackendPath, "probe", "--identity-key", key]',
            self.source,
        )
        self.assertNotIn('"esptool"', self.source)
        self.assertNotIn('"espefuse"', self.source)

    def test_probe_requires_selected_connected_role(self):
        self.assertIn("function cloneProbeEligible(device)", self.source)
        self.assertIn("if (!root.isCloneSelected(device)) return false", self.source)
        self.assertIn("device.connected", self.source)

    def test_probe_reset_warning_is_explicit(self):
        self.assertIn("PROBE RESETS BOARD", self.source)

    def test_target_write_remains_locked(self):
        self.assertIn("TARGET WRITE LOCKED", self.source)
        for forbidden in ("write-flash", "erase-flash", "erase-region", "burn-efuse"):
            self.assertNotIn(forbidden, self.source)

    def test_active_probe_evidence_is_separate_from_passive_evidence(self):
        self.assertIn('if (device.confidence === "bridge-only") return "BOARD UNKNOWN"', self.source)
        self.assertIn("id: cloneEvidence", self.source)
        self.assertIn("ACTIVE PROBE", self.source)

    def test_disconnect_invalidates_roles_and_probe_evidence(self):
        self.assertIn("function reconcileCloneState(scannedDevices)", self.source)
        self.assertIn('if (root.cloneSourceKey !== "" && !connected[root.cloneSourceKey])', self.source)
        self.assertIn('if (root.cloneTargetKey !== "" && !connected[root.cloneTargetKey])', self.source)
        self.assertIn("root.cloneProbeResults = results", self.source)


class CloneUiSourceReadContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("Panel.qml").read_text()

    def function_block(self, name, next_name):
        start = self.source.find("function " + name)
        if start < 0:
            return ""
        end = self.source.find("function " + next_name, start)
        return self.source[start:] if end < 0 else self.source[start:end]

    def test_source_read_state_is_runtime_only(self):
        self.assertIn('property string cloneReadKey: ""', self.source)
        self.assertIn('property bool cloneReadBusy: false', self.source)
        self.assertIn('property var cloneReadResult: null', self.source)
        self.assertIn('property string cloneReadError: ""', self.source)
        self.assertNotIn('persistSettings({ cloneRead', self.source)
        self.assertNotIn('persistDeviceProfile(device, { cloneRead', self.source)

    def test_source_read_requires_current_connected_source(self):
        block = self.function_block(
            "cloneSourceReadEligible(device)",
            "startCloneSourceRead(device)",
        )
        self.assertIn('key !== root.cloneSourceKey', block)
        self.assertIn('device.connected', block)
        self.assertIn('device.serialAvailable', block)
        self.assertIn('device.readable', block)
        self.assertIn('device.writable', block)
        self.assertIn('!device.locked', block)
        self.assertNotIn('cloneProbeResultFor', block)

    def test_source_read_uses_backend_identity_key_only(self):
        self.assertIn(
            '["python3", root.cloneBackendPath, "read-source", "--identity-key", key]',
            self.source,
        )
        self.assertNotIn('"esptool"', self.source)
        self.assertNotIn('"espefuse"', self.source)

    def test_probe_and_source_read_cannot_run_together(self):
        read_block = self.function_block(
            "cloneSourceReadEligible(device)",
            "startCloneSourceRead(device)",
        )
        probe_block = self.function_block(
            "cloneProbeEligible(device)",
            "cloneProbeResultFor(device)",
        )
        self.assertIn('!root.cloneProbeBusy', read_block)
        self.assertIn('!root.cloneReadBusy', probe_block)

    def test_source_read_reset_warning_is_explicit(self):
        self.assertIn('READ SOURCE · RESETS BOARD', self.source)
        self.assertIn('label: root.cloneReadBusy', self.source)
        self.assertIn('"READ SOURCE"', self.source)

    def test_source_read_result_is_strictly_validated(self):
        self.assertIn('function validCloneSha256(value)', self.source)
        self.assertIn('parsed.operation !== "read-source"', self.source)
        self.assertIn('String(parsed.identityKey || "") !== key', self.source)
        self.assertIn('Math.floor(size) !== size', self.source)
        self.assertIn('!root.validCloneSha256(sha256)', self.source)

    def test_source_read_ui_shows_size_and_full_sha256_only(self):
        self.assertIn('SOURCE READ PASS · ', self.source)
        self.assertIn('SHA-256 ', self.source)
        self.assertIn('root.cloneReadSizeLabel(cloneEvidence.readResult)', self.source)
        self.assertIn('cloneEvidence.readResult.sha256', self.source)
        for forbidden in ('parsed.imagePath', 'parsed.rawPath', 'parsed.transactionDir'):
            self.assertNotIn(forbidden, self.source)

    def test_source_read_has_dedicated_process_and_finish_handler(self):
        self.assertIn('id: cloneReadProc', self.source)
        self.assertIn('onStreamFinished: root.finishCloneSourceRead(text)', self.source)
        self.assertIn('function finishCloneSourceRead(raw)', self.source)

    def test_source_change_or_disconnect_invalidates_read_evidence(self):
        toggle_block = self.function_block(
            "toggleCloneSource(device)",
            "toggleCloneTarget(device)",
        )
        self.assertIn('root.clearCloneReadEvidence()', toggle_block)
        self.assertIn('root.clearCloneReadEvidence()', self.source)
        self.assertIn('if (root.cloneSourceKey !== "" && !connected[root.cloneSourceKey]) {', self.source)


class CloneUiSourceReadProgressContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("Panel.qml").read_text()

    def test_running_source_read_has_indeterminate_activity_indicator(self):
        start = self.source.find("id: sourceReadProgress")
        self.assertGreaterEqual(start, 0)
        end = self.source.find("visible: cloneEvidence.readError", start)
        self.assertGreater(end, start)
        block = self.source[start:end]
        self.assertIn(
            "visible: root.cloneReadBusy && root.cloneReadKey === cloneEvidence.identityKey",
            block,
        )
        self.assertIn("NumberAnimation on x", block)
        self.assertIn("loops: Animation.Infinite", block)
        self.assertNotIn("value:", block)
        self.assertNotIn("%", block)


class CloneUiVisualHierarchyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("Panel.qml").read_text()

    def test_visual_state_tokens_are_explicit(self):
        self.assertIn("readonly property color readyTone:", self.source)
        self.assertIn("readonly property color warningTone:", self.source)
        self.assertIn("readonly property color offlineTone:", self.source)
        self.assertIn("readonly property color hairline:", self.source)

    def test_device_status_uses_semantic_tone_function(self):
        self.assertIn("function deviceStatusTone(device)", self.source)
        self.assertIn(
            "color: root.deviceStatusTone(deviceColumn.modelData)",
            self.source,
        )

    def test_wide_grid_has_subtle_lower_row_separators(self):
        normalized = " ".join(self.source.split())
        self.assertIn(
            "visible: deviceColumn.index > 0 "
            "&& (!root.wideMode || deviceColumn.index >= 2)",
            normalized,
        )
        self.assertIn("foreground: root.hairline", normalized)

    def test_probe_reset_warning_is_contextual(self):
        normalized = " ".join(self.source.split())
        self.assertIn(
            "visible: cloneActions.visible "
            "&& root.isCloneSelected(deviceColumn.modelData)",
            normalized,
        )

    def test_offline_metadata_is_deemphasized(self):
        normalized = " ".join(self.source.split())
        self.assertGreaterEqual(
            normalized.count(
                "opacity: deviceColumn.modelData.connected ? 1.0 : 0.45"
            ),
            2,
        )

    def test_metadata_labels_are_quieter_than_values(self):
        label_start = self.source.find("component CompactLabel: Text")
        value_start = self.source.find("component CompactValue: Text")
        detail_start = self.source.find("component DetailLine: Item")
        self.assertGreaterEqual(label_start, 0)
        self.assertGreater(value_start, label_start)
        self.assertGreater(detail_start, value_start)

        label_block = self.source[label_start:value_start]
        value_block = self.source[value_start:detail_start]
        self.assertIn("opacity: 0.45", label_block)
        self.assertIn("opacity: urgent ? 1.0 : 0.92", value_block)

    def test_controls_and_grid_use_refined_spacing(self):
        normalized = " ".join(self.source.split())
        self.assertIn("rowSpacing: Style.space(14)", normalized)
        self.assertIn(
            "border.color: active ? root.bar.foreground : root.hairline",
            normalized,
        )


class CloneUiOfflineFoldContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("Panel.qml").read_text()
        cls.normalized = " ".join(cls.source.split())

    def function_block(self, name, next_name):
        start = self.source.find("function " + name)
        if start < 0:
            return ""
        end = self.source.find("function " + next_name, start)
        return self.source[start:] if end < 0 else self.source[start:end]

    def test_devices_are_partitioned_for_presentation(self):
        self.assertIn(
            "readonly property var connectedPanelDevices:",
            self.source,
        )
        self.assertIn(
            "readonly property var offlinePanelDevices:",
            self.source,
        )
        self.assertIn(
            "device.connected",
            self.normalized,
        )
        self.assertIn(
            "!device.connected",
            self.normalized,
        )

    def test_offline_fold_state_is_runtime_only(self):
        self.assertIn(
            "property bool offlineFoldOpen: false",
            self.source,
        )
        self.assertIn(
            'property string expandedOfflineKey: ""',
            self.source,
        )
        self.assertNotIn(
            "persistSettings({ offlineFoldOpen",
            self.source,
        )
        self.assertNotIn(
            "persistDeviceProfile(device, { offlineFoldOpen",
            self.source,
        )

    def test_offline_section_auto_opens_without_connected_devices(self):
        self.assertIn(
            "readonly property bool offlineVisible:",
            self.source,
        )
        self.assertIn(
            "root.connectedPanelDevices.length === 0 || root.offlineFoldOpen",
            self.normalized,
        )

    def test_wide_mode_uses_visible_navigation_count(self):
        self.assertIn(
            "readonly property int navigationDeviceCount:",
            self.source,
        )
        self.assertIn(
            "readonly property bool wideMode: root.navigationDeviceCount >= 2",
            self.source,
        )

    def test_connected_grid_contains_connected_devices_only(self):
        self.assertIn(
            "model: root.connectedPanelDevices",
            self.source,
        )

    def test_offline_section_has_count_and_fold_control(self):
        self.assertIn(
            "id: offlineSection",
            self.source,
        )
        self.assertIn(
            "REMEMBERED OFFLINE DEVICES",
            self.source,
        )
        self.assertIn(
            "root.offlinePanelDevices.length",
            self.source,
        )
        self.assertIn(
            "root.setOfflineFoldOpen(",
            self.source,
        )

    def test_offline_rows_use_compact_accordion_component(self):
        self.assertIn(
            "component OfflineDeviceRow:",
            self.source,
        )
        self.assertIn(
            "function toggleOfflineDetails(device)",
            self.source,
        )
        self.assertIn(
            "root.expandedOfflineKey",
            self.source,
        )

    def test_keyboard_navigation_excludes_hidden_offline_devices(self):
        block = self.function_block(
            "selectByDelta(delta)",
            "setOfflineFoldOpen(open)",
        )
        self.assertIn(
            "root.navigationDeviceCount",
            block,
        )
        self.assertNotIn(
            "devices.length - 1",
            block,
        )

    def test_collapsing_offline_section_clears_hidden_state(self):
        block = self.function_block(
            "setOfflineFoldOpen(open)",
            "toggleOfflineDetails(device)",
        )
        self.assertIn(
            'root.expandedOfflineKey = ""',
            block,
        )
        self.assertIn(
            "root.navigationDeviceCount",
            block,
        )
        self.assertIn(
            "root.selectedIndex",
            block,
        )


class CloneUiWorkbenchStateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("Panel.qml").read_text()

    def function_block(self, name, next_name):
        start = self.source.find("function " + name)
        if start < 0:
            return ""
        end = self.source.find("function " + next_name, start)
        return self.source[start:] if end < 0 else self.source[start:end]

    def test_workbench_slots_are_runtime_only(self):
        self.assertIn('property string workbenchLeftKey: ""', self.source)
        self.assertIn('property string workbenchRightKey: ""', self.source)
        self.assertNotIn("persistSettings({ workbenchLeftKey", self.source)
        self.assertNotIn("persistSettings({ workbenchRightKey", self.source)
        self.assertNotIn(
            "persistDeviceProfile(device, { workbenchLeftKey",
            self.source,
        )
        self.assertNotIn(
            "persistDeviceProfile(device, { workbenchRightKey",
            self.source,
        )

    def test_workbench_identity_accepts_only_scanner_identity_keys(self):
        block = self.function_block(
            "validWorkbenchIdentity(device)",
            "sortedConnectedWorkbenchCandidates()",
        )
        self.assertIn('key.indexOf("usb-serial:") === 0', block)
        self.assertIn('key.indexOf("usb-topology:") === 0', block)

    def test_workbench_candidates_use_connected_identity_only(self):
        block = self.function_block(
            "sortedConnectedWorkbenchCandidates()",
            "deviceForIdentity(key)",
        )
        self.assertIn("device.connected", block)
        self.assertIn('String(device.identityKey || "")', block)
        self.assertIn("candidates.sort", block)
        self.assertIn("identityKey", block)

    def test_reconcile_fills_empty_slots_without_replacing_reserved_slots(self):
        block = self.function_block(
            "reconcileWorkbenchSlots()",
            "assignWorkbenchSlot(side, device)",
        )
        self.assertIn('if (root.workbenchLeftKey === "")', block)
        self.assertIn('if (root.workbenchRightKey === "")', block)
        self.assertNotIn('root.workbenchLeftKey = ""', block)
        self.assertNotIn('root.workbenchRightKey = ""', block)

    def test_one_identity_cannot_occupy_both_slots(self):
        block = self.function_block(
            "assignWorkbenchSlot(side, device)",
            "cloneIdentityKey(device)",
        )
        self.assertIn("root.workbenchRightKey === key", block)
        self.assertIn("root.workbenchLeftKey === key", block)

    def test_slot_assignment_does_not_change_clone_roles(self):
        block = self.function_block(
            "assignWorkbenchSlot(side, device)",
            "cloneIdentityKey(device)",
        )
        self.assertNotEqual(block, "")
        self.assertNotIn("cloneSourceKey =", block)
        self.assertNotIn("cloneTargetKey =", block)

    def test_device_refresh_reconciles_workbench_slots(self):
        block = self.function_block(
            "updateDevices(raw)",
            "copy(value)",
        )
        self.assertIn("reconcileWorkbenchSlots()", block)


if __name__ == "__main__":
    unittest.main()
