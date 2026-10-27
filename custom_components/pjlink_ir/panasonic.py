"""Bounded Panasonic NTCONTROL transactions for FW300 Daylight View only."""

import asyncio
from contextlib import suppress
import hashlib
import re

from .client import AuthenticationError, PJLinkError

MODES = {"off": "+00000", "auto": "+00001", "on": "+00002"}


def supports_daylight(settings):
    """Limit automatic discovery to the documented model family."""
    model = settings.get("model", "").upper().removeprefix("PT-")
    return settings.get("manufacturer", "").lower() == "panasonic" and model in (
        "FW300NT", "FW300NTU", "FW300NTE", "FW300NTEA", "FW300", "FW300U", "FW300E",
    )


class PanasonicClient:
    """Fresh connection and challenge per command; no retries or arbitrary commands."""

    def __init__(self, host, port=1024, username="admin1", password="", timeout=4):
        self.host, self.port = host, port
        self.username, self.password, self.timeout = username, password, timeout

    async def daylight(self, mode=None):
        if mode is not None and mode not in MODES:
            raise ValueError("Invalid Daylight View mode")
        command = "QVX:DLVI0" if mode is None else f"VXX:DLVI0={MODES[mode]}"
        writer = None
        try:
            async with asyncio.timeout(self.timeout):
                reader, writer = await asyncio.open_connection(self.host, self.port, limit=1024)
                greeting = await self._line(reader)
                prefix = b""
                if greeting == "NTCONTROL 0":
                    pass
                elif re.fullmatch(r"NTCONTROL 1 [0-9a-fA-F]{8}", greeting):
                    if not self.password:
                        raise AuthenticationError("Panasonic web-control password required; configure integration options")
                    try:
                        secret = f"{self.username}:{self.password}:{greeting[-8:]}".encode("ascii")
                    except UnicodeEncodeError:
                        raise AuthenticationError("Panasonic credentials must be ASCII") from None
                    prefix = hashlib.md5(secret, usedforsecurity=False).hexdigest().encode("ascii")
                else:
                    raise PJLinkError("Invalid Panasonic greeting")
                writer.write(prefix + f"00{command}\r".encode("ascii"))
                await writer.drain()
                response = await self._line(reader)
                # Panasonic errors can be returned without the normal 00 header.
                result = response[2:] if response.startswith("00") else response
                if result == "ERRA":
                    raise AuthenticationError("Panasonic web-control authentication failed")
                if result in ("ERR1", "ERR2", "ERR3", "ERR4", "ERR5", "ER401", "ER402"):
                    raise PJLinkError(f"Panasonic: {result}")
                if not response.startswith("00"):
                    raise PJLinkError("Unexpected Panasonic response header")
                if mode is None:
                    for key, value in MODES.items():
                        if result == value:
                            return key
                    raise PJLinkError("Invalid Panasonic Daylight View state")
                if result != command:
                    raise PJLinkError("Missing Panasonic acknowledgement")
                return mode
        except (TimeoutError, OSError) as err:
            raise PJLinkError("Panasonic connection or response unavailable; command not retried") from err
        finally:
            if writer is not None:
                writer.close()
                with suppress(OSError, TimeoutError):
                    async with asyncio.timeout(1):
                        await writer.wait_closed()

    @staticmethod
    async def _line(reader):
        try:
            return (await reader.readuntil(b"\r")).decode("ascii").removesuffix("\r")
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, UnicodeError) as err:
            raise PJLinkError("Malformed Panasonic response") from err
