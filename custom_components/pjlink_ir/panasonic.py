"""Bounded Panasonic NTCONTROL transactions for documented FW300 controls."""

import asyncio
from contextlib import suppress
import hashlib
import re
import time

from .client import AuthenticationError, PJLinkError
from .panasonic_features import QUERIES, control_command, parse_field

MODES = {"off": "+00000", "auto": "+00001", "on": "+00002"}


class PanasonicCommandError(PJLinkError):
    """A device rejection; another optional query can still work."""

    def __init__(self, command, code):
        self.command, self.code = command, code
        super().__init__(f"Panasonic {command}: {code}")


class PanasonicConnectionError(PJLinkError):
    """Stop this optional polling cycle when the transport is unavailable."""


def supports_daylight(settings):
    """Limit automatic discovery to the documented model family."""
    model = settings.get("model", "").upper().removeprefix("PT-")
    return settings.get("manufacturer", "").lower() == "panasonic" and model in (
        "FW300NT", "FW300NTU", "FW300NTE", "FW300NTEA", "FW300", "FW300U", "FW300E",
    )


class PanasonicClient:
    """Fresh connection and challenge per command; no retries or arbitrary commands."""

    def __init__(self, host, port=1024, username="admin1", password="", timeout=10):
        self.host, self.port = host, port
        self.username, self.password, self.timeout = username, password, timeout
        self.rear = False
        self.interval = 0.5
        self._next_command = 0

    async def read(self, key):
        if key not in QUERIES:
            raise ValueError("Unknown Panasonic query")
        try:
            return parse_field(key, await self._transaction(QUERIES[key]))
        except (PanasonicCommandError, PanasonicConnectionError, AuthenticationError):
            raise
        except PJLinkError as err:
            raise PJLinkError(f"Panasonic {QUERIES[key]}: {err}") from err

    async def control(self, key, value=None):
        command = control_command(key, value)
        result = await self._transaction(command)
        # No blind repeats, including non-idempotent zoom buttons.
        if result != command:
            raise PJLinkError(f"Panasonic {command.split(':')[0]}: missing acknowledgement")

    async def daylight(self, mode=None):
        if mode is not None and mode not in MODES:
            raise ValueError("Invalid Daylight View mode")
        if mode is None:
            installation = await self._transaction("QSP")
            if installation not in ("0", "1", "2", "3"):
                raise PJLinkError("Panasonic QSP: invalid projection method")
            self.rear = installation in ("1", "3")
            result = await self._transaction("QVX:DLVI0")
            # The detailed FW300 control specification includes the parameter name.
            result = result.removeprefix("DLVI0=")
            modes = {"off": "+00000", "on": "+00001"} if self.rear else MODES
            for key, value in modes.items():
                if result == value:
                    return key
            raise PJLinkError("Panasonic QVX:DLVI0: invalid Daylight View state")
        if self.rear and mode == "auto":
            raise PJLinkError("Daylight View Auto is unavailable for rear projection")
        value = "+00001" if self.rear and mode == "on" else MODES[mode]
        command = f"VXX:DLVI0={value}"
        if await self._transaction(command) != command:
            raise PJLinkError("Missing Panasonic acknowledgement")
        return mode

    async def _transaction(self, command):
        await asyncio.sleep(max(0, self._next_command - time.monotonic()))
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
                    raise PanasonicConnectionError("Invalid Panasonic greeting")
                writer.write(prefix + f"00{command}\r".encode("ascii"))
                await writer.drain()
                response = await self._line(reader)
                # Panasonic errors can be returned without the normal 00 header.
                result = response[2:] if response.startswith("00") else response
                if result == "ERRA":
                    raise AuthenticationError("Panasonic web-control authentication failed")
                if result in ("ERR1", "ERR2", "ERR3", "ERR4", "ERR5", "ER401", "ER402"):
                    raise PanasonicCommandError(command, result)
                if not response.startswith("00"):
                    raise PJLinkError("Unexpected Panasonic response header")
                return result
        except (TimeoutError, OSError) as err:
            raise PanasonicConnectionError(f"Panasonic {command.split(':')[0]} connection or response unavailable; command not retried") from err
        finally:
            self._next_command = time.monotonic() + self.interval
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
