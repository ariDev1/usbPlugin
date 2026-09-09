from pathlib import Path
import unittest


class CloneUiLayoutContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("Panel.qml").read_text()

    def test_panel_has_adaptive_wide_mode(self):
        self.assertIn("readonly property bool wideMode", self.source)
        self.assertIn("root.devices.length >= 2", self.source)
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

    def test_separators_are_compact_mode_only(self):
        self.assertIn(
            "visible: !root.wideMode && deviceColumn.index > 0",
            self.source,
        )

    def test_horizontal_scroll_remains_disabled(self):
        self.assertIn(
            "ScrollBar.horizontal.policy: ScrollBar.AlwaysOff",
            self.source,
        )


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
        self.assertNotIn('"read-source"', self.source)

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


if __name__ == "__main__":
    unittest.main()
