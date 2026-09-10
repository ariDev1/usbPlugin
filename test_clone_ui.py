from pathlib import Path
import unittest
import re


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

    def test_active_workbench_uses_two_column_grid(self):
        normalized = " ".join(self.source.split())
        self.assertIn("Grid { id: workbenchGrid", normalized)
        self.assertIn("columns: root.wideMode ? 2 : 1", normalized)
        self.assertIn(
            "width: root.wideMode ? "
            "(workbenchGrid.width - workbenchGrid.columnSpacing) / 2 "
            ": workbenchGrid.width",
            normalized,
        )

    def test_workbench_card_separator_uses_navigation_index(self):
        start = self.source.find("component WorkbenchDeviceCard:")
        end = self.source.find("component WorkbenchSlot:", start)
        self.assertGreaterEqual(start, 0)
        self.assertGreater(end, start)

        block = " ".join(self.source[start:end].split())
        self.assertIn("PanelSeparator {", block)
        self.assertIn(
            "visible: deviceColumn.navigationIndex > 0",
            block,
        )
        self.assertNotIn("deviceColumn.index", block)

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

    def test_workbench_card_separator_uses_hairline(self):
        start = self.source.find("component WorkbenchDeviceCard:")
        end = self.source.find("component WorkbenchSlot:", start)
        self.assertGreaterEqual(start, 0)
        self.assertGreater(end, start)

        block = " ".join(self.source[start:end].split())
        self.assertIn("PanelSeparator {", block)
        self.assertIn("foreground: root.hairline", block)

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

    def test_controls_and_workbench_use_refined_spacing(self):
        normalized = " ".join(self.source.split())
        self.assertIn("columnSpacing: Style.space(14)", normalized)
        self.assertIn("rowSpacing: Style.space(12)", normalized)
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

    def test_full_connected_view_uses_only_workbench_slots(self):
        self.assertIn(
            "modelData: root.workbenchLeftDevice",
            self.source,
        )
        self.assertIn(
            "modelData: root.workbenchRightDevice",
            self.source,
        )
        self.assertNotIn(
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


class CloneUiWorkbenchModelContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("Panel.qml").read_text()
        cls.normalized = " ".join(cls.source.split())

    def test_workbench_device_models_resolve_by_identity(self):
        self.assertIn(
            "readonly property var workbenchLeftDevice:",
            self.source,
        )
        self.assertIn(
            "readonly property var workbenchRightDevice:",
            self.source,
        )
        self.assertIn(
            "root.deviceForIdentity(root.workbenchLeftKey)",
            self.normalized,
        )
        self.assertIn(
            "root.deviceForIdentity(root.workbenchRightKey)",
            self.normalized,
        )

    def test_rack_excludes_both_active_identities(self):
        self.assertIn("readonly property var rackDevices:", self.source)
        self.assertIn(
            "key !== root.workbenchLeftKey",
            self.normalized,
        )
        self.assertIn(
            "key !== root.workbenchRightKey",
            self.normalized,
        )

    def test_offline_list_excludes_reserved_workbench_identities(self):
        self.assertIn(
            "readonly property var offlinePanelDevices:",
            self.source,
        )
        self.assertIn(
            "root.projectedOfflineDevices.filter",
            self.normalized,
        )
        self.assertIn(
            "key !== root.workbenchLeftKey",
            self.normalized,
        )
        self.assertIn(
            "key !== root.workbenchRightKey",
            self.normalized,
        )

    def test_clone_role_badge_is_derived_without_mutation(self):
        self.assertIn(
            "function workbenchCloneRole(device)",
            self.source,
        )
        self.assertIn('return "SOURCE"', self.source)
        self.assertIn('return "TARGET"', self.source)


class CloneUiWorkbenchLayoutContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("Panel.qml").read_text()
        cls.normalized = " ".join(cls.source.split())

    def component_block(self, name, next_name):
        start = self.source.find("component " + name + ":")
        if start < 0:
            return ""
        end = self.source.find("component " + next_name + ":", start)
        return self.source[start:] if end < 0 else self.source[start:end]

    def test_active_workbench_has_exactly_two_slots(self):
        self.assertIn('text: "ACTIVE WORKBENCH"', self.source)
        self.assertIn("id: workbenchGrid", self.source)

        start = self.source.find("id: workbenchGrid")
        self.assertGreaterEqual(start, 0)
        block = self.source[start:]

        self.assertEqual(block.count("WorkbenchSlot {"), 2)
        self.assertIn('slotLabel: "LEFT"', block)
        self.assertIn('slotLabel: "RIGHT"', block)
        self.assertIn(
            "modelData: root.workbenchLeftDevice",
            block,
        )
        self.assertIn(
            "modelData: root.workbenchRightDevice",
            block,
        )

    def test_full_device_card_is_reusable_workbench_component(self):
        block = self.component_block(
            "WorkbenchDeviceCard",
            "WorkbenchSlot",
        )

        self.assertNotEqual(block, "")
        self.assertIn("required property var modelData", block)
        self.assertIn("required property int navigationIndex", block)

        for required_id in (
            "id: cloneActions",
            "id: cloneEvidence",
            "id: deviceDetails",
        ):
            self.assertIn(required_id, block)

    def test_old_full_grid_no_longer_repeats_all_connected_devices(self):
        self.assertNotIn(
            "model: root.connectedPanelDevices",
            self.source,
        )

    def test_wide_panel_target_is_in_engineering_range(self):
        match = re.search(
            r"readonly property int widePanelWidth:\s*Style\.space\((\d+)\)",
            self.source,
        )
        self.assertIsNotNone(match)
        self.assertGreaterEqual(int(match.group(1)), 920)
        self.assertLessEqual(int(match.group(1)), 960)


class CloneUiConnectedRackContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("Panel.qml").read_text()
        cls.normalized = " ".join(cls.source.split())

    def component_block(self, name, next_name):
        start = self.source.find("component " + name + ":")
        if start < 0:
            return ""
        end = self.source.find("component " + next_name + ":", start)
        return self.source[start:] if end < 0 else self.source[start:end]

    def test_connected_rack_uses_only_rack_devices(self):
        self.assertIn("id: connectedRack", self.source)
        self.assertIn("model: root.rackDevices", self.source)

    def test_connected_rack_uses_two_columns_in_wide_mode(self):
        start = self.source.find("id: connectedRack")
        self.assertGreaterEqual(start, 0)
        block = " ".join(self.source[start:start + 1400].split())
        self.assertIn(
            "columns: root.wideMode ? 2 : 1",
            block,
        )

    def test_rack_row_has_explicit_left_and_right_controls(self):
        block = self.component_block(
            "ConnectedRackRow",
            "WorkbenchDeviceCard",
        )
        self.assertNotEqual(block, "")
        self.assertIn('label: "L"', block)
        self.assertIn('label: "R"', block)
        self.assertIn(
            'root.assignWorkbenchSlot("left", modelData)',
            block,
        )
        self.assertIn(
            'root.assignWorkbenchSlot("right", modelData)',
            block,
        )

    def test_rack_row_shows_clone_role_without_changing_it(self):
        block = self.component_block(
            "ConnectedRackRow",
            "WorkbenchDeviceCard",
        )
        self.assertNotEqual(block, "")
        self.assertIn(
            "root.workbenchCloneRole(modelData)",
            block,
        )
        self.assertNotIn("cloneSourceKey =", block)
        self.assertNotIn("cloneTargetKey =", block)

    def test_rack_row_does_not_duplicate_full_device_controls(self):
        block = self.component_block(
            "ConnectedRackRow",
            "WorkbenchDeviceCard",
        )
        self.assertNotEqual(block, "")
        self.assertNotIn('label: "PROBE"', block)
        self.assertNotIn('"READ SOURCE"', block)
        self.assertNotIn("id: cloneEvidence", block)
        self.assertNotIn("id: deviceDetails", block)


class CloneUiWorkbenchNavigationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("Panel.qml").read_text()
        cls.normalized = " ".join(cls.source.split())

    def component_block(self, name, next_name):
        start = self.source.find("component " + name + ":")
        if start < 0:
            return ""
        end = self.source.find("component " + next_name + ":", start)
        return self.source[start:] if end < 0 else self.source[start:end]

    def test_navigation_model_follows_visible_presentation_order(self):
        self.assertIn(
            "readonly property var navigationDevices:",
            self.source,
        )
        self.assertIn(
            "root.workbenchNavigationDevices.concat(root.rackDevices)",
            self.normalized,
        )
        self.assertIn(
            "root.offlineVisible",
            self.normalized,
        )
        self.assertIn(
            "root.offlinePanelDevices",
            self.normalized,
        )

    def test_navigation_count_uses_navigation_model(self):
        self.assertIn(
            "readonly property int navigationDeviceCount:",
            self.source,
        )
        self.assertIn(
            "root.navigationDevices.length",
            self.normalized,
        )

    def test_navigation_lookup_uses_navigation_model(self):
        start = self.source.find("function navigationDeviceAt(index)")
        end = self.source.find("function selectByDelta(delta)", start)
        self.assertGreaterEqual(start, 0)
        self.assertGreater(end, start)

        block = self.source[start:end]
        self.assertIn(
            "return root.navigationDevices[index]",
            block,
        )
        self.assertNotIn(
            "root.connectedPanelDevices[index]",
            block,
        )

    def test_rack_navigation_starts_after_visible_workbench_devices(self):
        self.assertIn(
            "readonly property int rackNavigationOffset:",
            self.source,
        )

        block = self.component_block(
            "ConnectedRackRow",
            "WorkbenchDeviceCard",
        )
        self.assertIn(
            "readonly property int navigationIndex:",
            block,
        )
        self.assertIn(
            "root.rackNavigationOffset + index",
            block,
        )

    def test_rack_row_has_visible_keyboard_selection(self):
        block = self.component_block(
            "ConnectedRackRow",
            "WorkbenchDeviceCard",
        )
        self.assertIn(
            "root.selectedIndex === rackRow.navigationIndex",
            block,
        )

    def test_offline_navigation_starts_after_visible_connected_devices(self):
        self.assertIn(
            "readonly property int offlineNavigationOffset:",
            self.source,
        )

        block = self.component_block(
            "OfflineDeviceRow",
            "CloneActionButton",
        )
        self.assertIn(
            "root.offlineNavigationOffset + index",
            block,
        )


class CloneUiWorkbenchCloneIsolationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("Panel.qml").read_text()

    def function_block(self, name, next_name):
        start = self.source.find("function " + name)
        if start < 0:
            return ""
        end = self.source.find("function " + next_name, start)
        return self.source[start:] if end < 0 else self.source[start:end]

    def component_block(self, name, next_name):
        start = self.source.find("component " + name + ":")
        if start < 0:
            return ""
        end = self.source.find("component " + next_name + ":", start)
        return self.source[start:] if end < 0 else self.source[start:end]

    def test_manual_slot_assignment_cannot_modify_clone_state(self):
        block = self.function_block(
            "assignWorkbenchSlot(side, device)",
            "workbenchCloneRole(device)",
        )
        self.assertNotEqual(block, "")

        for forbidden in (
            "cloneSourceKey =",
            "cloneTargetKey =",
            "clearCloneReadEvidence",
            "setCloneProbeEvidence",
            "cloneReadResult =",
            "cloneProbeResults =",
        ):
            self.assertNotIn(forbidden, block)

    def test_automatic_slot_reconcile_cannot_modify_clone_state(self):
        block = self.function_block(
            "reconcileWorkbenchSlots()",
            "assignWorkbenchSlot(side, device)",
        )
        self.assertNotEqual(block, "")

        for forbidden in (
            "cloneSourceKey",
            "cloneTargetKey",
            "cloneRead",
            "cloneProbe",
        ):
            self.assertNotIn(forbidden, block)

    def test_rack_clone_role_is_display_only(self):
        block = self.component_block(
            "ConnectedRackRow",
            "WorkbenchDeviceCard",
        )
        self.assertNotEqual(block, "")
        self.assertIn(
            "root.workbenchCloneRole(modelData)",
            block,
        )

        for forbidden in (
            "toggleCloneSource",
            "toggleCloneTarget",
            "startCloneProbe",
            "startCloneSourceRead",
        ):
            self.assertNotIn(forbidden, block)

    def test_full_workbench_card_preserves_clone_controls(self):
        block = self.component_block(
            "WorkbenchDeviceCard",
            "WorkbenchSlot",
        )
        self.assertNotEqual(block, "")

        for required in (
            'label: "SOURCE"',
            'label: "TARGET"',
            '"PROBE"',
            '"READ SOURCE"',
            "PROBE RESETS BOARD",
            "READ SOURCE · RESETS BOARD",
            "TARGET WRITE LOCKED",
            "id: cloneEvidence",
        ):
            self.assertIn(required, block)


class CloneUiComponentDepthContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("Panel.qml").read_text()

    def brace_depth_before(self, marker):
        end = self.source.find(marker)
        self.assertGreaterEqual(end, 0)

        depth = 0
        quote = None
        escape = False
        block_comment = False
        i = 0

        while i < end:
            c = self.source[i]
            n = self.source[i + 1] if i + 1 < end else ""

            if block_comment:
                if c == "*" and n == "/":
                    block_comment = False
                    i += 2
                    continue
                i += 1
                continue

            if quote:
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == quote:
                    quote = None
                i += 1
                continue

            if c == "/" and n == "/":
                newline = self.source.find("\n", i)
                i = end if newline < 0 else newline + 1
                continue

            if c == "/" and n == "*":
                block_comment = True
                i += 2
                continue

            if c in ("'", '"'):
                quote = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1

            i += 1

        return depth

    def test_inline_components_are_inside_root_panel(self):
        for name in (
            "ConnectedRackRow",
            "WorkbenchDeviceCard",
            "WorkbenchSlot",
        ):
            self.assertEqual(
                self.brace_depth_before("component " + name + ":"),
                1,
                name,
            )


class CloneUiContentContainmentContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("Panel.qml").read_text()

    def object_block_for_id(self, object_id):
        marker = "id: " + object_id
        marker_index = self.source.find(marker)
        self.assertGreaterEqual(marker_index, 0)

        open_index = self.source.rfind("{", 0, marker_index)
        self.assertGreaterEqual(open_index, 0)

        depth = 0
        quote = None
        escape = False
        i = open_index

        while i < len(self.source):
            c = self.source[i]

            if quote:
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == quote:
                    quote = None
            else:
                if c in ("'", '"'):
                    quote = c
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        return self.source[open_index:i + 1]

            i += 1

        self.fail("object block did not close")

    def test_content_column_owns_all_visible_sections(self):
        block = self.object_block_for_id("content")

        for required in (
            "id: workbenchGrid",
            "id: connectedRack",
            "id: offlineSection",
            "id: defaultsFooter",
        ):
            self.assertIn(required, block)


class CloneUiKeyboardActionStateContractTests(unittest.TestCase):
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

    def test_contextual_action_state_is_runtime_only(self):
        for required in (
            'property string actionDeviceKey: ""',
            "property int actionIndex: 0",
            "property bool actionMenuOpen: false",
            "property bool actionDeviceWasConnected: false",
        ):
            self.assertIn(required, self.source)

        for forbidden in (
            "persistSettings({ actionDevice",
            "persistDeviceProfile(device, { actionDevice",
            "persistSettings({ actionMenuOpen",
        ):
            self.assertNotIn(forbidden, self.source)

    def test_selected_device_uses_existing_navigation_model(self):
        block = self.function_block(
            "selectedNavigationDevice()",
            "actionDevice()",
        )
        self.assertIn("root.navigationDeviceAt(root.selectedIndex)", block)

    def test_action_device_re_resolves_from_visible_navigation(self):
        block = self.function_block(
            "actionDevice()",
            "actionDeviceLocation(device)",
        )
        self.assertIn("root.navigationDevices", block)
        self.assertIn("root.deviceActionKey(device)", block)

    def test_action_model_contains_required_rack_operations(self):
        block = self.function_block(
            "actionsForDevice(device)",
            "selectActionByDelta(delta)",
        )
        for required in ('"open-left"', '"open-right"', '"copy-path"'):
            self.assertIn(required, block)

    def test_action_model_contains_required_workbench_operations(self):
        block = self.function_block(
            "actionsForDevice(device)",
            "selectActionByDelta(delta)",
        )
        for required in (
            '"source"', '"target"', '"probe"', '"read-source"',
            '"rename"', '"baud"', '"line-ending"', '"data-format"',
            '"logging"', '"monitor"', '"grant-access"',
        ):
            self.assertIn(required, block)

    def test_action_model_contains_offline_details(self):
        block = self.function_block(
            "actionsForDevice(device)",
            "selectActionByDelta(delta)",
        )
        self.assertIn('"details"', block)
        self.assertIn('"LESS"', block)
        self.assertIn('"DETAILS"', block)

    def test_action_model_does_not_execute_clone_backend(self):
        block = self.function_block(
            "actionsForDevice(device)",
            "selectActionByDelta(delta)",
        )
        self.assertNotIn("cloneBackendPath", block)
        self.assertNotIn("cloneProbeProc", block)
        self.assertNotIn("cloneReadProc", block)


class CloneUiKeyboardActionDispatchContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("Panel.qml").read_text()

    def function_block(self, name, next_name):
        start = self.source.find("function " + name)
        if start < 0:
            return ""
        end = self.source.find("function " + next_name, start)
        return self.source[start:] if end < 0 else self.source[start:end]

    def test_action_cursor_is_clamped(self):
        block = self.function_block(
            "selectActionByDelta(delta)",
            "selectedAction()",
        )
        self.assertIn("Math.max(", block)
        self.assertIn("Math.min(", block)

    def test_dispatch_rechecks_enabled_state(self):
        block = self.function_block(
            "activateSelectedAction()",
            "navigationItemAt(index)",
        )
        self.assertIn(
            "if (!device || !action || action.enabled !== true) return",
            block,
        )

    def test_slot_actions_delegate_to_existing_assignment_function(self):
        block = self.function_block(
            "activateSelectedAction()",
            "navigationItemAt(index)",
        )
        self.assertIn('root.assignWorkbenchSlot("left", device)', block)
        self.assertIn('root.assignWorkbenchSlot("right", device)', block)

    def test_clone_actions_delegate_to_existing_guarded_functions(self):
        block = self.function_block(
            "activateSelectedAction()",
            "navigationItemAt(index)",
        )
        for required in (
            "root.toggleCloneSource(device)",
            "root.toggleCloneTarget(device)",
            "root.startCloneProbe(device)",
            "root.startCloneSourceRead(device)",
        ):
            self.assertIn(required, block)

    def test_profile_actions_delegate_to_existing_functions(self):
        block = self.function_block(
            "activateSelectedAction()",
            "navigationItemAt(index)",
        )
        for required in (
            "root.beginRename(device)",
            "root.cycleDeviceBaud(device)",
            "root.cycleDeviceLineEnding(device)",
            "root.cycleDeviceDataFormat(device)",
            "root.toggleDeviceLogging(device)",
        ):
            self.assertIn(required, block)

    def test_no_destructive_clone_operation_is_added(self):
        for forbidden in (
            "write-flash", "erase-flash", "erase-region", "burn-efuse",
        ):
            self.assertNotIn(forbidden, self.source)


class CloneUiKeyboardRoutingContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("Panel.qml").read_text()
        start = cls.source.find("PanelKeyCatcher {")
        end = cls.source.find("ScrollView {", start)
        cls.block = " ".join(cls.source[start:end].split())

    def test_main_key_catcher_is_blocked_for_submodes(self):
        self.assertIn(
            'blocked: root.actionMenuOpen || root.renamingKey !== ""',
            self.block,
        )

    def test_enter_opens_contextual_actions(self):
        self.assertIn("root.openSelectedActions()", self.block)
        self.assertNotIn("root.copy(root.devicePath(device))", self.block)

    def test_vertical_navigation_still_uses_existing_device_cursor(self):
        self.assertIn("root.selectByDelta(dy)", self.block)

    def test_refresh_remains_r(self):
        self.assertIn('text === "r" || text === "R"', self.block)
        self.assertIn("root.refresh()", self.block)

    def test_no_direct_clone_letter_binding_is_added(self):
        for forbidden in (
            'text === "p"', 'text === "P"', 'text === "s"',
            'text === "S"', 'text === "t"', 'text === "T"',
        ):
            self.assertNotIn(forbidden, self.block)


class CloneUiKeyboardActionSurfaceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("Panel.qml").read_text()

    def component_block(self, name, next_name):
        start = self.source.find("component " + name + ":")
        if start < 0:
            return ""
        end = self.source.find("component " + next_name + ":", start)
        return self.source[start:] if end < 0 else self.source[start:end]

    def test_action_menu_is_explicit_transient_component(self):
        block = self.component_block("ActionMenu", "OfflineDeviceRow")
        self.assertNotEqual(block, "")
        self.assertIn("component ActionMenu: Popup", block)
        self.assertIn("parent: keyCatcher", block)
        self.assertIn("visible: root.actionMenuOpen", block)
        self.assertIn("focus: visible", block)
        self.assertIn("background: BorderSurface", block)
        self.assertIn("borderSpec: Border.flat(root.hairline, 1)", block)

    def test_action_menu_has_compact_bounded_geometry(self):
        block = self.component_block("ActionMenu", "OfflineDeviceRow")
        self.assertIn("Style.space(340)", block)
        self.assertIn("actionMenuSurface.anchorPoint.x", block)
        self.assertIn("actionMenuSurface.anchorPoint.y", block)
        self.assertIn(
            "height: Math.min(actionRows.implicitHeight, Style.space(320))",
            block,
        )
        self.assertIn("height: Style.space(28)", block)
        self.assertNotIn("anchors.fill: parent", block.split("contentItem:", 1)[0])

    def test_action_menu_uses_omarchy_dark_surface(self):
        block = self.component_block("ActionMenu", "OfflineDeviceRow")
        self.assertIn("background: BorderSurface", block)
        self.assertIn("color: Color.background", block)
        self.assertIn("padding: Style.space(10)", block)

    def test_disabled_actions_remain_legible(self):
        block = self.component_block("ActionMenu", "OfflineDeviceRow")
        self.assertIn(
            "opacity: actionRow.modelData.enabled === true ? 1.0 : 0.55",
            block,
        )

    def test_popup_instance_is_hosted_by_quick_item(self):
        expected = (
            "    Item {\n"
            "      id: actionMenuHost\n"
            "      anchors.fill: parent\n"
            "      z: 20\n"
            "\n"
            "      ActionMenu {\n"
            "        id: actionMenu\n"
            "      }\n"
            "    }\n"
        )
        self.assertIn(expected, self.source)

    def test_action_menu_identifies_selected_device(self):
        block = self.component_block("ActionMenu", "OfflineDeviceRow")
        self.assertIn('root.displayName(actionMenuSurface.device) + " · ACTIONS"', block)

    def test_action_cursor_and_active_state_are_separate(self):
        block = self.component_block("ActionMenu", "OfflineDeviceRow")
        self.assertIn("hasCursor: root.actionIndex === actionRow.index", block)
        self.assertIn("current: actionRow.modelData.active === true", block)

    def test_disabled_action_has_explicit_feedback(self):
        block = self.component_block("ActionMenu", "OfflineDeviceRow")
        self.assertIn('? "UNAVAILABLE"', block)
        self.assertNotIn("UNAVAILABLE IN CURRENT STATE", block)

    def test_resetting_clone_operations_are_explicit(self):
        action_start = self.source.find("function actionsForDevice(device)")
        action_end = self.source.find("function selectActionByDelta(delta)", action_start)
        self.assertGreaterEqual(action_start, 0)
        self.assertGreater(action_end, action_start)
        action_block = self.source[action_start:action_end]
        self.assertIn('note: "RESETS BOARD"', action_block)

        menu_block = self.component_block("ActionMenu", "OfflineDeviceRow")
        self.assertIn("modelData.note", menu_block)

    def test_action_menu_handles_escape_and_activation(self):
        block = self.component_block("ActionMenu", "OfflineDeviceRow")
        self.assertIn("Qt.Key_Escape", block)
        self.assertIn("root.closeActions()", block)
        self.assertIn("root.activateSelectedAction()", block)


class CloneUiKeyboardRenameContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("Panel.qml").read_text()

    def test_cancel_rename_is_explicit(self):
        self.assertIn("function cancelRename()", self.source)
        self.assertIn('root.renamingKey = ""', self.source)

    def test_both_name_fields_handle_escape(self):
        self.assertGreaterEqual(self.source.count("Keys.onEscapePressed:"), 2)

    def test_both_name_fields_take_focus_when_shown(self):
        self.assertIn("nameField.forceActiveFocus()", self.source)
        self.assertIn("offlineNameField.forceActiveFocus()", self.source)

    def test_focus_returns_to_main_catcher_after_edit(self):
        self.assertIn("keyCatcher.forceActiveFocus()", self.source)


class CloneUiKeyboardScrollContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("Panel.qml").read_text()

    def function_block(self, name, next_name):
        start = self.source.find("function " + name)
        if start < 0:
            return ""
        end = self.source.find("function " + next_name, start)
        return self.source[start:] if end < 0 else self.source[start:end]

    def test_device_selection_scrolls_into_view(self):
        block = self.function_block(
            "selectByDelta(delta)",
            "reconcileActionState()",
        )
        self.assertIn("root.scrollSelectedDeviceIntoView()", block)

    def test_visual_lookup_uses_existing_sections(self):
        block = self.function_block(
            "navigationItemAt(index)",
            "scrollItemIntoView(item)",
        )
        for required in (
            "leftWorkbenchSlot.navigationItem",
            "rightWorkbenchSlot.navigationItem",
            "connectedRackRepeater.itemAt",
            "offlineRepeater.itemAt",
        ):
            self.assertIn(required, block)

    def test_scroll_uses_scrollview_flickable(self):
        block = self.function_block(
            "scrollItemIntoView(item)",
            "scrollSelectedDeviceIntoView()",
        )
        self.assertIn("deviceScroll.contentItem", block)
        self.assertIn("flick.contentY", block)

    def test_identity_selection_uses_current_navigation_model(self):
        block = self.function_block(
            "selectDeviceIdentity(key)",
            "activateSelectedAction()",
        )
        self.assertIn("root.navigationDevices", block)
        self.assertIn("root.selectedIndex =", block)
        self.assertIn("root.scrollSelectedDeviceIntoView()", block)


class CloneUiKeyboardStaleActionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("Panel.qml").read_text()

    def function_block(self, name, next_name):
        start = self.source.find("function " + name)
        if start < 0:
            return ""
        end = self.source.find("function " + next_name, start)
        return self.source[start:] if end < 0 else self.source[start:end]

    def test_refresh_reconciles_action_state(self):
        block = self.function_block("updateDevices(raw)", "copy(value)")
        self.assertIn("reconcileActionState()", block)

    def test_connected_device_disconnect_closes_actions(self):
        block = self.function_block(
            "reconcileActionState()",
            "setOfflineFoldOpen(open)",
        )
        self.assertIn(
            "(device.connected === true) !== root.actionDeviceWasConnected",
            block,
        )
        self.assertIn("root.closeActions()", block)

    def test_panel_lifecycle_clears_transient_action_state(self):
        self.assertIn("onOpenedChanged: {", self.source)
        self.assertIn('actionDeviceKey = ""', self.source)
        self.assertIn("actionMenuOpen = false", self.source)


class CloneUiKeyboardRackCursorContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("Panel.qml").read_text()

    def test_rack_uses_shared_cursor_surface(self):
        start = self.source.find("component ConnectedRackRow:")
        end = self.source.find("component WorkbenchDeviceCard:", start)
        self.assertGreaterEqual(start, 0)
        self.assertGreater(end, start)
        block = self.source[start:end]
        self.assertIn("component ConnectedRackRow: CursorSurface", block)
        self.assertIn("root.selectedIndex === rackRow.navigationIndex", block)
        self.assertIn("onContainsMouseChanged: if (containsMouse)", block)
        self.assertIn("root.selectedIndex = rackRow.navigationIndex", block)
        self.assertNotIn("border.color: root.cursorActive", block)


if __name__ == "__main__":
    unittest.main()
