"""Documented Panasonic response samples and validation boundaries."""

import importlib
from pathlib import Path
import sys
import types
import unittest

package = types.ModuleType("panasonic_features_test")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components" / "pjlink_ir")]
sys.modules.setdefault("panasonic_features_test", package)
features = importlib.import_module("panasonic_features_test.panasonic_features")


class FeatureParsingTests(unittest.TestCase):
    def test_documented_temperature_samples(self):
        self.assertEqual(features.parse_field("intake_temperature", "0020/0068"), 20)
        self.assertEqual(features.parse_field("exhaust_temperature", "-010/0014"), -10)

    def test_temperature_does_not_accept_mac_or_bad_units(self):
        for value in ("AB0102030405", "20", "0020/0200", "0201/0394", "NaN/NaN", "20C", "", "0000/0000"):
            with self.subTest(value=value), self.assertRaises(features.PJLinkError):
                features.parse_field("intake_temperature", value)

    def test_filter_hours_and_count_include_zero(self):
        for key in features.SENSORS:
            if "temperature" not in key:
                self.assertEqual(features.parse_field(key, "0000"), 0)
                self.assertEqual(features.parse_field(key, "1500"), 1500)

    def test_filter_garbage_never_becomes_zero(self):
        for value in ("-001", "ERR1", "missing", "1 2", "1000000", ""):
            with self.subTest(value=value), self.assertRaises(features.PJLinkError):
                features.parse_field("filter_remaining", value)

    def test_control_numeric_ranges_and_wire_format(self):
        self.assertEqual(features.control_command("volume", 0), "AVL:000")
        self.assertEqual(features.control_command("volume", 63), "AVL:063")
        self.assertEqual(features.control_command("brightness", -32), "VBR:-32")
        self.assertEqual(features.control_command("contrast", 32.0), "VCN:032")
        for value in (-1, 64, 10.5, float("nan"), float("inf"), True, "1\rPON"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                features.control_command("volume", value)

    def test_query_validation_matches_control_range(self):
        self.assertEqual(features.parse_field("brightness", "+00"), 0)
        self.assertEqual(features.parse_field("contrast", "-32"), -32)
        self.assertEqual(features.parse_field("volume", "063"), 63)
        for key, value in (("volume", "064"), ("contrast", "-33"), ("brightness", "999")):
            with self.assertRaises(features.PJLinkError):
                features.parse_field(key, value)

    def test_selections_and_freeze(self):
        for key, (_query, command, values) in features.SELECTS.items():
            for mode, code in values.items():
                self.assertEqual(features.parse_field(key, code), mode)
                self.assertEqual(features.control_command(key, mode), f"{command}:{code}")
        self.assertIs(features.parse_field("freeze", "0"), False)
        self.assertIs(features.parse_field("freeze", "1"), True)
        self.assertEqual(features.control_command("freeze", False), "OFZ:0")
        self.assertEqual(features.control_command("freeze", True), "OFZ:1")

    def test_reject_unknown_commands_options_and_states(self):
        for key, value in (("arbitrary", None), ("picture_mode", "DYN\rPON"), ("freeze", 1)):
            with self.assertRaises(ValueError):
                features.control_command(key, value)
        for key, value in (("picture_mode", "BAD"), ("color_temperature", "3"), ("aspect", "7"), ("freeze", "2")):
            with self.assertRaises(features.PJLinkError):
                features.parse_field(key, value)
