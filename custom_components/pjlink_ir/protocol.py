"""Validated PJLink Class 1 telemetry values."""

import re

from .client import PJLinkError

ERROR_FIELDS = ("fan", "lamp", "temperature", "cover", "filter", "other")
ERROR_STATES = ("ok", "warning", "error")
POWER_PHASES = {"0": "standby", "1": "on", "2": "cooling", "3": "warming"}


def parse_lamps(value):
    """LAMP returns 1–8 pairs of cumulative hours and actual lit state."""
    parts = value.split()
    if not parts or len(parts) % 2 or len(parts) > 16:
        raise PJLinkError("Invalid PJLink lamp status")
    lamps = []
    for hours, state in zip(parts[::2], parts[1::2], strict=True):
        if not re.fullmatch(r"[0-9]{1,5}", hours) or state not in ("0", "1"):
            raise PJLinkError("Invalid PJLink lamp status")
        lamps.append({"hours": int(hours), "on": state == "1"})
    return lamps


def parse_errors(value):
    """ERST has six independent severity digits: 0 OK, 1 warning, 2 error."""
    if not re.fullmatch(r"[012]{6}", value):
        raise PJLinkError("Invalid PJLink error status")
    return dict(zip(ERROR_FIELDS, (ERROR_STATES[int(digit)] for digit in value), strict=True))
