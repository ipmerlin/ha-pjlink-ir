"""Real TCP loopback coverage of Panasonic wire format and failure boundaries."""

import asyncio
import hashlib
import importlib
from pathlib import Path
import sys
import types
import unittest

package = types.ModuleType("panasonic_test")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components" / "pjlink_ir")]
sys.modules.setdefault("panasonic_test", package)
module = importlib.import_module("panasonic_test.panasonic")


class PanasonicTCPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.greeting = b"NTCONTROL 0\r"
        self.reply = b"00+00001\r"
        self.requests = []
        self.installation = b"0"
        self.handlers = set()

        async def handle(reader, writer):
            task = asyncio.current_task()
            self.handlers.add(task)
            try:
                writer.write(self.greeting)
                await writer.drain()
                request = await reader.readuntil(b"\r")
                self.requests.append(request)
                if request.endswith(b"00QSP\r"):
                    writer.write(b"00" + self.installation + b"\r")
                    await writer.drain()
                    return
                if self.reply is None:
                    await reader.read()
                else:
                    writer.write(self.reply)
                    await writer.drain()
            except (asyncio.IncompleteReadError, ConnectionError):
                pass
            finally:
                writer.close()
                await writer.wait_closed()
                self.handlers.discard(task)

        self.server = await asyncio.start_server(handle, "127.0.0.1", 0)
        self.client = module.PanasonicClient("127.0.0.1", self.server.sockets[0].getsockname()[1], timeout=0.2)
        self.client.interval = 0

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
        if self.handlers:
            await asyncio.gather(*self.handlers)

    async def test_query_and_three_modes(self):
        for mode, value in module.MODES.items():
            self.reply = f"00DLVI0={value}\r".encode()
            self.assertEqual(await self.client.daylight(), mode)
            self.reply = f"00VXX:DLVI0={value}\r".encode()
            self.assertEqual(await self.client.daylight(mode), mode)
        self.assertEqual(self.requests, [
            b"00QSP\r", b"00QVX:DLVI0\r", b"00VXX:DLVI0=+00000\r",
            b"00QSP\r", b"00QVX:DLVI0\r", b"00VXX:DLVI0=+00001\r",
            b"00QSP\r", b"00QVX:DLVI0\r", b"00VXX:DLVI0=+00002\r",
        ])

    async def test_rear_projection_has_no_auto_and_different_on_value(self):
        self.installation = b"3"
        self.reply = b"00DLVI0=+00001\r"
        self.assertEqual(await self.client.daylight(), "on")
        self.assertTrue(self.client.rear)
        with self.assertRaises(module.PJLinkError):
            await self.client.daylight("auto")
        self.reply = b"00VXX:DLVI0=+00001\r"
        self.assertEqual(await self.client.daylight("on"), "on")
        self.assertEqual(self.requests[-1], b"00VXX:DLVI0=+00001\r")

    async def test_bad_projection_method_does_not_guess_mapping(self):
        self.installation = b"9"
        with self.assertRaises(module.PJLinkError):
            await self.client.daylight()
        self.assertEqual(self.requests, [b"00QSP\r"])

    async def test_protect_mode_hash_and_fresh_challenge(self):
        self.client.username, self.client.password = "admin1", "test-password"
        for nonce in ("498e4a67", "1234abcd"):
            self.greeting = f"NTCONTROL 1 {nonce}\r".encode()
            self.assertEqual(await self.client.daylight(), "auto")
            digest = hashlib.md5(f"admin1:test-password:{nonce}".encode(), usedforsecurity=False).hexdigest().encode()
            self.assertEqual(self.requests[-1], digest + b"00QVX:DLVI0\r")

    async def test_no_password_no_command(self):
        self.greeting = b"NTCONTROL 1 498e4a67\r"
        with self.assertRaises(module.AuthenticationError):
            await self.client.daylight()
        self.assertEqual(self.requests, [])

    async def test_invalid_greetings_never_send(self):
        for greeting in (b"HTTP/1.0 200\r", b"NTCONTROL 2 12345678\r", b"NTCONTROL 1 secret\r"):
            self.greeting = greeting
            with self.assertRaises(module.PJLinkError):
                await self.client.daylight()
        self.assertEqual(self.requests, [])

    async def test_rejections_and_malformed_data(self):
        for response in (b"ERRA\r", b"00ERRA\r", b"ERR1\r", b"ER401\r", b"00ERR3\r",
                         b"+00001\r", b"00+00009\r", b"00\xff\r", b"x" * 1500 + b"\r", b"00"):
            self.reply = response
            with self.assertRaises(module.PJLinkError):
                await self.client.daylight()

    async def test_lost_ack_not_retried(self):
        self.reply = None
        with self.assertRaises(module.PJLinkError):
            await self.client.daylight("on")
        self.assertEqual(self.requests, [b"00VXX:DLVI0=+00002\r"])

    async def test_wrong_ack_is_not_success(self):
        with self.assertRaises(module.PJLinkError):
            await self.client.daylight("on")

    async def test_invalid_mode_before_connection(self):
        with self.assertRaises(ValueError):
            await self.client.daylight("on\rPON")
        self.assertEqual(self.requests, [])

    def test_only_documented_models(self):
        self.assertTrue(module.supports_daylight({"manufacturer": "Panasonic", "model": "FW300NT"}))
        self.assertTrue(module.supports_daylight({"manufacturer": "Panasonic", "model": "PT-FW300NTE"}))
        self.assertFalse(module.supports_daylight({"manufacturer": "Other", "model": "FW300NT"}))
        self.assertFalse(module.supports_daylight({"manufacturer": "Panasonic", "model": "FW430"}))
