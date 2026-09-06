from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QComboBox, QTabBar

from metabatch.gui import WheelGuardComboBox, WheelGuardTabBar


def _wheel_event(delta_y: int) -> QWheelEvent:
    return QWheelEvent(
        QPointF(5, 5),
        QPointF(5, 5),
        QPoint(0, 0),
        QPoint(0, delta_y),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )


class WheelGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_plain_combo_changes_on_wheel(self) -> None:
        combo = QComboBox()
        combo.addItems(["a", "b", "c"])
        combo.setCurrentIndex(1)
        combo.wheelEvent(_wheel_event(-120))
        self.assertEqual(combo.currentIndex(), 2)

    def test_guard_combo_ignores_wheel(self) -> None:
        combo = WheelGuardComboBox()
        combo.addItems(["a", "b", "c"])
        combo.setCurrentIndex(1)
        combo.wheelEvent(_wheel_event(-120))
        combo.wheelEvent(_wheel_event(120))
        self.assertEqual(combo.currentIndex(), 1)

    def test_guard_combo_allows_click_selection(self) -> None:
        combo = WheelGuardComboBox()
        combo.addItems(["a", "b", "c"])
        combo.setCurrentIndex(0)
        combo.setCurrentIndex(2)
        self.assertEqual(combo.currentText(), "c")

    def test_plain_tabbar_changes_on_wheel(self) -> None:
        bar = QTabBar()
        bar.addTab("A")
        bar.addTab("B")
        bar.addTab("C")
        bar.setCurrentIndex(1)
        bar.wheelEvent(_wheel_event(-120))
        self.assertEqual(bar.currentIndex(), 2)

    def test_guard_tabbar_ignores_wheel(self) -> None:
        bar = WheelGuardTabBar()
        bar.addTab("A")
        bar.addTab("B")
        bar.addTab("C")
        bar.setCurrentIndex(1)
        bar.wheelEvent(_wheel_event(-120))
        bar.wheelEvent(_wheel_event(120))
        self.assertEqual(bar.currentIndex(), 1)


if __name__ == "__main__":
    unittest.main()
