"""Lamp and error replies are validated before becoming HA states."""

import importlib
import unittest

from test_protocol import PJLinkError

protocol = importlib.import_module("pjlink_test.protocol")


class TelemetryParsingTests(unittest.TestCase):
    def test_lamp_operating_hours_and_lit_state(self):
        self.assertEqual(protocol.parse_lamps("1234 1"), [{"hours": 1234, "on": True}])

    def test_zero_hours_is_a_real_reading(self):
        self.assertEqual(protocol.parse_lamps("0 0"), [{"hours": 0, "on": False}])

    def test_multiple_lamps_keep_individual_counters(self):
        self.assertEqual(
            protocol.parse_lamps("1000 1 720 0"), [{"hours": 1000, "on": True}, {"hours": 720, "on": False}]
        )

    def test_eight_lamps_supported(self):
        self.assertEqual(len(protocol.parse_lamps(" ".join(["99999 1"] * 8))), 8)

    def test_malformed_lamps_rejected(self):
        for value in ("", "1234", "1234 1 30", "-5 1", "1.5 1", "NaN 1", "100000 1", "10 2", "hello 0", "１２ 1"):
            with self.subTest(value=value), self.assertRaises(PJLinkError):
                protocol.parse_lamps(value)

    def test_more_than_eight_lamps_rejected(self):
        with self.assertRaises(PJLinkError):
            protocol.parse_lamps(" ".join(["1 1"] * 9))

    def test_all_ok(self):
        self.assertEqual(protocol.parse_errors("000000"), dict.fromkeys(protocol.ERROR_FIELDS, "ok"))

    def test_warning_and_error_are_distinct(self):
        self.assertEqual(
            protocol.parse_errors("102010"),
            {"fan": "warning", "lamp": "ok", "temperature": "error", "cover": "ok", "filter": "warning", "other": "ok"},
        )

    def test_all_errors(self):
        self.assertEqual(protocol.parse_errors("222222"), dict.fromkeys(protocol.ERROR_FIELDS, "error"))

    def test_malformed_errors_rejected(self):
        for value in ("", "00000", "0000000", "000003", "0 0 0 0 0 0", "abcdef", "00000\n", "０00000"):
            with self.subTest(value=value), self.assertRaises(PJLinkError):
                protocol.parse_errors(value)
