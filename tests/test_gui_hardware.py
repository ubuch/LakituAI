"""Tests for GPU VRAM detection and the low-VRAM warning."""

import unittest
from unittest import mock

from lakituai.gui import hardware


class VramWarningTests(unittest.TestCase):
    """Tests for vram_warning_message threshold logic."""

    def test_no_warning_above_threshold(self):
        self.assertIsNone(hardware.vram_warning_message(8.0))
        self.assertIsNone(hardware.vram_warning_message(6.0))
        self.assertIsNone(hardware.vram_warning_message(12.5))

    def test_warning_below_threshold(self):
        msg = hardware.vram_warning_message(4.0)
        self.assertIsNotNone(msg)
        self.assertIn("Low VRAM", msg)
        self.assertIn("4.0 GB", msg)

    def test_warning_at_threshold_boundary(self):
        msg = hardware.vram_warning_message(5.9)
        self.assertIsNotNone(msg)

    def test_no_warning_when_undetectable(self):
        self.assertIsNone(hardware.vram_warning_message(None))


class VramDetectionTests(unittest.TestCase):
    """Tests for get_total_vram_gb fallback behavior."""

    @mock.patch("lakituai.gui.hardware._from_nvidia_smi", return_value=8.0)
    @mock.patch("lakituai.gui.hardware._from_vulkan")
    @mock.patch("lakituai.gui.hardware._from_torch")
    def test_prefers_nvidia_smi(self, torch_call, vulkan_call, smi_call):
        self.assertEqual(hardware.get_total_vram_gb(), 8.0)
        vulkan_call.assert_not_called()
        torch_call.assert_not_called()

    @mock.patch("lakituai.gui.hardware._from_nvidia_smi", return_value=None)
    @mock.patch("lakituai.gui.hardware._from_vulkan", return_value=6.5)
    @mock.patch("lakituai.gui.hardware._from_torch")
    def test_uses_vulkan_fallback(self, torch_call, vulkan_call, smi_call):
        self.assertEqual(hardware.get_total_vram_gb(), 6.5)
        torch_call.assert_not_called()

    @mock.patch("lakituai.gui.hardware._from_nvidia_smi", return_value=None)
    @mock.patch("lakituai.gui.hardware._from_vulkan", return_value=None)
    @mock.patch("lakituai.gui.hardware._from_torch", return_value=4.0)
    def test_falls_back_to_torch(self, torch_call, vulkan_call, smi_call):
        self.assertEqual(hardware.get_total_vram_gb(), 4.0)

    @mock.patch("lakituai.gui.hardware._from_nvidia_smi", return_value=None)
    @mock.patch("lakituai.gui.hardware._from_vulkan", return_value=None)
    @mock.patch("lakituai.gui.hardware._from_torch", return_value=None)
    def test_none_when_no_detection(self, torch_call, vulkan_call, smi_call):
        self.assertIsNone(hardware.get_total_vram_gb())


if __name__ == "__main__":
    unittest.main()
