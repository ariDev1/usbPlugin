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


if __name__ == "__main__":
    unittest.main()
