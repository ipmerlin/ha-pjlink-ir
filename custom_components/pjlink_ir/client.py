"""Small bounded async PJLink Class 1 client; no command retries."""

import asyncio
from contextlib import suppress
import hashlib
import re


class PJLinkError(Exception):
    """A protocol or device error (never includes credentials)."""


class ConnectionUnavailable(PJLinkError):
    """Connection could not be established before any command was sent."""


class AuthenticationError(PJLinkError):
    """Authentication failed."""


class CommandError(PJLinkError):
    """The device rejected a command."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"PJLink: {code}")


class PJLinkClient:
    """Use a fresh authenticated connection for each transaction."""

    def __init__(self, host: str, port: int = 4352, password: str = "", timeout: float = 4) -> None:
        self.host, self.port, self.password, self.timeout = host, port, password, timeout

    async def command(self, name: str, value: str = "?") -> str:
        """Send exactly once. A lost response is an unknown outcome."""
        if not re.fullmatch(r"[A-Z]{4}", name) or not re.fullmatch(r"[?0-9]+", value):
            raise ValueError("Invalid PJLink command")
        writer = None
        try:
            try:
                async with asyncio.timeout(self.timeout):
                    reader, writer = await asyncio.open_connection(self.host, self.port, limit=1024)
            except (OSError, TimeoutError) as err:
                raise ConnectionUnavailable("PJLink connection unavailable") from err
            async with asyncio.timeout(self.timeout):
                greeting = await self._line(reader)
                prefix = b""
                if greeting == "PJLINK 0":
                    pass
                elif re.fullmatch(r"PJLINK 1 [0-9a-fA-F]{8}", greeting):
                    if not self.password:
                        raise AuthenticationError("PJLink password required")
                    try:
                        secret = (greeting[9:] + self.password).encode("ascii")
                    except UnicodeEncodeError:
                        raise AuthenticationError("PJLink password must be ASCII") from None
                    prefix = hashlib.md5(secret, usedforsecurity=False).hexdigest().encode("ascii")
                elif greeting == "PJLINK ERRA":
                    raise AuthenticationError("PJLink authentication failed")
                else:
                    raise PJLinkError("Invalid PJLink greeting")
                writer.write(prefix + f"%1{name} {value}\r".encode("ascii"))
                await writer.drain()
                response = await self._line(reader)
                if response == "PJLINK ERRA":
                    raise AuthenticationError("PJLink authentication failed")
                header = f"%1{name}="
                if not response.startswith(header):
                    raise PJLinkError("Unexpected PJLink response")
                result = response[len(header) :]
                if result in ("ERR1", "ERR2", "ERR3", "ERR4"):
                    raise CommandError(result)
                if value != "?" and result != "OK":
                    raise PJLinkError("Missing PJLink acknowledgement")
                return result
        except (TimeoutError, OSError) as err:
            raise PJLinkError("PJLink response lost or timed out; command not retried") from err
        finally:
            if writer is not None:
                writer.close()
                with suppress(OSError, TimeoutError):
                    async with asyncio.timeout(1):
                        await writer.wait_closed()

    @staticmethod
    async def _line(reader: asyncio.StreamReader) -> str:
        try:
            return (await reader.readuntil(b"\r")).decode("utf-8").removesuffix("\r")
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, UnicodeError) as err:
            raise PJLinkError("Malformed PJLink response") from err

    async def power(self) -> str:
        result = await self.command("POWR")
        if result not in ("0", "1", "2", "3"):
            raise PJLinkError("Invalid PJLink power state")
        return result

    async def identify(self) -> dict[str, str]:
        """Power query authenticates; optional metadata may be unsupported."""
        await self.power()
        info = {}
        for field, command in (("name", "NAME"), ("manufacturer", "INF1"), ("model", "INF2")):
            try:
                info[field] = await self.command(command)
            except CommandError as err:
                if err.code != "ERR1":
                    raise
        return info
