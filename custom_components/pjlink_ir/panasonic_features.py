"""Documented FW300 fields; no Home Assistant or network dependencies."""

import math
import re

from .client import PJLinkError

SELECTS = {
    "picture_mode": ("QPM", "VPM", {"dynamic": "DYN", "standard": "STD", "natural": "NAT", "cinema": "CIN", "blackboard": "BBD"}),
    "color_temperature": ("QTE", "OTE", {"low": "0", "default": "1", "high": "2"}),
    "aspect": ("QS1", "VS1", {"auto": "0", "4_3": "1", "16_9": "2", "h_fit": "3", "v_fit": "4", "hv_fit": "5", "through": "6"}),
}
NUMBERS = {
    "volume": ("QAV", "AVL", 0, 63),
    "brightness": ("QVB", "VBR", -32, 32),
    "contrast": ("QVR", "VCN", -32, 32),
}
SENSORS = {
    "intake_temperature": "QTM:0",
    "exhaust_temperature": "QTM:1",
    "filter_hours": "QFI:0",
    "filter_rewinds": "QFI:1",
    "filter_since_rewind": "QFI:4",
    "filter_remaining": "QFI:5",
}
BUTTONS = {"auto_setup": "OAS", "zoom_in": "DZU", "zoom_out": "DZD", "side_by_side": "ODW"}
QUERIES = {**SENSORS, **{key: value[0] for key, value in NUMBERS.items()},
           **{key: value[0] for key, value in SELECTS.items()}, "freeze": "QFZ"}


def integer(value, minimum, maximum):
    if not re.fullmatch(r"[+-]?\d{1,6}", value):
        raise PJLinkError("Invalid Panasonic numeric response")
    result = int(value)
    if not minimum <= result <= maximum:
        raise PJLinkError("Panasonic numeric response out of range")
    return result


def parse_field(key, value):
    if key in SELECTS:
        for mode, code in SELECTS[key][2].items():
            if value == code:
                return mode
        raise PJLinkError("Invalid Panasonic selection response")
    if key in NUMBERS:
        return integer(value, *NUMBERS[key][2:])
    if key == "freeze":
        return bool(integer(value, 0, 1))
    if key.endswith("temperature"):
        # FW300 specifies signed Celsius / Fahrenheit, e.g. 0020/0068.
        if not re.fullmatch(r"[+-]?\d{3,4}/[+-]?\d{3,4}", value):
            raise PJLinkError("Invalid Panasonic temperature response")
        celsius, fahrenheit = (int(part) for part in value.split("/"))
        if not -50 <= celsius <= 200 or abs(fahrenheit - (celsius * 1.8 + 32)) > 2:
            raise PJLinkError("Inconsistent Panasonic temperature response")
        return celsius
    if key in SENSORS:
        return integer(value, 0, 999999)
    raise ValueError("Unknown Panasonic field")


def control_command(key, value=None):
    """Allow listed controls and validated values only; never accept arbitrary commands."""
    if key in SELECTS:
        codes = SELECTS[key][2]
        if value not in codes:
            raise ValueError("Invalid Panasonic option")
        return f"{SELECTS[key][1]}:{codes[value]}"
    if key in NUMBERS:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Invalid Panasonic number")
        minimum, maximum = NUMBERS[key][2:]
        if value != int(value) or not minimum <= value <= maximum:
            raise ValueError("Panasonic number out of range")
        number = int(value)
        parameter = f"{number:03d}" if number >= 0 else f"-{abs(number):02d}"
        return f"{NUMBERS[key][1]}:{parameter}"
    if key == "freeze" and type(value) is bool:
        return f"OFZ:{int(value)}"
    if key in BUTTONS and value is None:
        return BUTTONS[key]
    raise ValueError("Unknown Panasonic control")
