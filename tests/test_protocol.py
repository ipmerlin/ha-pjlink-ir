"""Real loopback TCP tests; never connect to physical hardware."""

import asyncio
import hashlib
import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("pjlink_test")
package.__path__ = [str(ROOT / "custom_components" / "pjlink_ir")]
sys.modules.setdefault("pjlink_test", package)
client_module = importlib.import_module("pjlink_test.client")
wake_module = importlib.import_module("pjlink_test.wake")
PJLinkClient = client_module.PJLinkClient
PJLinkError = client_module.PJLinkError
ConnectionUnavailable = client_module.ConnectionUnavailable
AuthenticationError = client_module.AuthenticationError
CommandError = client_module.CommandError
WakeController = wake_module.WakeController


class TCPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.reply = b"%1POWR=1\r"
        self.replies = {}
        self.greeting = b"PJLINK 0\r"
        self.handlers = set()

        async def handle(reader, writer):
            task = asyncio.current_task()
            self.handlers.add(task)
            try:
                writer.write(self.greeting)
                await writer.drain()
                request = await reader.readuntil(b"\r")
                self.requests.append(request)
                name = request.split(b"%1", 1)[1][:4].decode("ascii")
                reply = self.replies.get(name, self.reply)
                if reply is None:
                    await reader.read()
                else:
                    writer.write(reply)
                    await writer.drain()
            except (asyncio.IncompleteReadError, ConnectionError):
                pass
            finally:
                writer.close()
                await writer.wait_closed()
                self.handlers.discard(task)

        self.server = await asyncio.start_server(handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.client = PJLinkClient("127.0.0.1", self.port, timeout=0.1)

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
        if self.handlers:
            await asyncio.gather(*self.handlers)

    async def test_plain_power(self):
        self.assertEqual(await self.client.power(), "1")
        self.assertEqual(self.requests, [b"%1POWR ?\r"])

    async def test_lamp_and_error_queries_over_tcp(self):
        self.replies = {"LAMP": b"%1LAMP=4567 1\r", "ERST": b"%1ERST=001000\r"}
        self.assertEqual(await self.client.command("LAMP"), "4567 1")
        self.assertEqual(await self.client.command("ERST"), "001000")
        self.assertEqual(self.requests, [b"%1LAMP ?\r", b"%1ERST ?\r"])

    async def test_identify_end_to_end(self):
        self.replies = {
            "POWR": b"%1POWR=1\r",
            "NAME": b"%1NAME=Cinema\r",
            "INF1": b"%1INF1=Panasonic\r",
            "INF2": b"%1INF2=PT-Test\r",
        }
        self.assertEqual(
            await self.client.identify(), {"name": "Cinema", "manufacturer": "Panasonic", "model": "PT-Test"}
        )
        self.assertEqual(self.requests, [b"%1POWR ?\r", b"%1NAME ?\r", b"%1INF1 ?\r", b"%1INF2 ?\r"])

    async def test_authenticated_identify_end_to_end(self):
        self.greeting = b"PJLINK 1 498e4a67\r"
        self.client.password = "JBMIAProjectorLink"
        self.replies = {
            "POWR": b"%1POWR=0\r",
            "NAME": b"%1NAME=Cinema\r",
            "INF1": b"%1INF1=Panasonic\r",
            "INF2": b"%1INF2=PT-Test\r",
        }
        self.assertEqual((await self.client.identify())["model"], "PT-Test")
        digest = hashlib.md5(b"498e4a67JBMIAProjectorLink", usedforsecurity=False).hexdigest().encode()
        self.assertEqual(
            self.requests, [digest + f"%1{name} ?\r".encode() for name in ("POWR", "NAME", "INF1", "INF2")]
        )

    async def test_unsupported_identity_fields_end_to_end(self):
        self.replies = {
            "POWR": b"%1POWR=1\r",
            "NAME": b"%1NAME=ERR1\r",
            "INF1": b"%1INF1=Panasonic\r",
            "INF2": b"%1INF2=ERR1\r",
        }
        self.assertEqual(await self.client.identify(), {"manufacturer": "Panasonic"})

    async def test_invalid_command_names_rejected(self):
        for name in ("INF1\rPOWR", "INF", "INF12", "inf1", "1NF1", "INF "):
            with self.subTest(name=name), self.assertRaises(ValueError):
                await self.client.command(name)
        self.assertEqual(self.requests, [])

    async def test_authentication(self):
        self.greeting = b"PJLINK 1 498e4a67\r"
        self.client.password = "JBMIAProjectorLink"
        self.assertEqual(await self.client.power(), "1")
        digest = hashlib.md5(b"498e4a67JBMIAProjectorLink", usedforsecurity=False).hexdigest().encode()
        self.assertEqual(self.requests, [digest + b"%1POWR ?\r"])

    async def test_wrong_password(self):
        self.reply = b"PJLINK ERRA\r"
        with self.assertRaises(AuthenticationError):
            await self.client.power()

    async def test_password_required(self):
        self.greeting = b"PJLINK 1 498e4a67\r"
        with self.assertRaises(AuthenticationError):
            await self.client.power()
        self.assertEqual(self.requests, [])

    async def test_wrong_header(self):
        self.reply = b"%1INPT=1\r"
        with self.assertRaises(PJLinkError):
            await self.client.power()

    async def test_bad_power(self):
        self.reply = b"%1POWR=9\r"
        with self.assertRaises(PJLinkError):
            await self.client.power()

    async def test_error_codes(self):
        for code in ("ERR1", "ERR2", "ERR3", "ERR4"):
            self.reply = f"%1POWR={code}\r".encode()
            with self.assertRaises(CommandError) as ctx:
                await self.client.power()
            self.assertEqual(ctx.exception.code, code)

    async def test_ack_required(self):
        with self.assertRaises(PJLinkError):
            await self.client.command("POWR", "1")
        self.assertEqual(len(self.requests), 1)

    async def test_ack_ok(self):
        self.reply = b"%1POWR=OK\r"
        self.assertEqual(await self.client.command("POWR", "0"), "OK")

    async def test_oversized_line(self):
        self.reply = b"x" * 1500 + b"\r"
        with self.assertRaises(PJLinkError):
            await self.client.power()

    async def test_incomplete_reply(self):
        self.reply = b"%1POWR="
        with self.assertRaises(PJLinkError):
            await self.client.power()

    async def test_invalid_utf8(self):
        self.reply = b"%1POWR=\xff\r"
        with self.assertRaises(PJLinkError):
            await self.client.power()

    async def test_lost_response_never_retried(self):
        self.reply = None
        with self.assertRaises(PJLinkError) as ctx:
            await self.client.command("POWR", "1")
        self.assertNotIsInstance(ctx.exception, ConnectionUnavailable)
        self.assertEqual(len(self.requests), 1)

    async def test_bad_greeting_is_not_sleep(self):
        self.greeting = b"HTTP/1.1 200 OK\r"
        with self.assertRaises(PJLinkError) as ctx:
            await self.client.power()
        self.assertNotIsInstance(ctx.exception, ConnectionUnavailable)

    async def test_input_injection_rejected(self):
        with self.assertRaises(ValueError):
            await self.client.command("POWR", "1\r%1POWR 0")
        self.assertEqual(self.requests, [])

    async def test_refused_connection_is_sleep_candidate(self):
        self.server.close()
        await self.server.wait_closed()
        with self.assertRaises(ConnectionUnavailable):
            await self.client.power()


class WakeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = types.SimpleNamespace(power=AsyncMock(), command=AsyncMock())
        self.ir = AsyncMock()
        self.wake = WakeController(self.client, self.ir, timeout=1, interval=0.001)

    async def test_awake_no_ir_no_network_command(self):
        for state in ("1", "3"):
            self.client.power.return_value = state
            await self.wake.turn_on()
        self.ir.assert_not_awaited()
        self.client.command.assert_not_awaited()

    async def test_network_standby(self):
        self.client.power.return_value = "0"
        await self.wake.turn_on()
        self.client.command.assert_awaited_once_with("POWR", "1")
        self.ir.assert_not_awaited()

    async def test_cooling_no_power_command(self):
        self.client.power.return_value = "2"
        with self.assertRaises(PJLinkError):
            await self.wake.turn_on()
        self.ir.assert_not_awaited()
        self.client.command.assert_not_awaited()

    async def test_sleep_ir_once_wait_for_actual_power(self):
        self.client.power.side_effect = [ConnectionUnavailable(), ConnectionUnavailable(), "0", "3"]
        await self.wake.turn_on()
        self.ir.assert_awaited_once()
        self.client.command.assert_not_awaited()

    async def test_auth_error_never_uses_ir(self):
        self.client.power.side_effect = AuthenticationError()
        with self.assertRaises(AuthenticationError):
            await self.wake.turn_on()
        self.ir.assert_not_awaited()

    async def test_protocol_error_never_uses_ir(self):
        self.client.power.side_effect = PJLinkError()
        with self.assertRaises(PJLinkError):
            await self.wake.turn_on()
        self.ir.assert_not_awaited()

    async def test_timeout_and_later_call_do_not_repeat_ir(self):
        self.wake.timeout = 0.03
        self.client.power.side_effect = ConnectionUnavailable()
        with self.assertRaises(PJLinkError):
            await self.wake.turn_on()
        with self.assertRaises(PJLinkError):
            await self.wake.turn_on()
        self.ir.assert_awaited_once()

    async def test_ir_failure_no_network_command(self):
        self.client.power.side_effect = ConnectionUnavailable()
        self.ir.side_effect = RuntimeError("remote failed")
        with self.assertRaises(RuntimeError):
            await self.wake.turn_on()
        self.client.command.assert_not_awaited()

    async def test_simultaneous_calls_do_not_duplicate_ir(self):
        self.client.power.side_effect = [ConnectionUnavailable(), "1", "1"]
        await asyncio.gather(self.wake.turn_on(), self.wake.turn_on())
        self.ir.assert_awaited_once()

    async def test_cancellation_does_not_repeat_ir(self):
        self.client.power.side_effect = ConnectionUnavailable()
        self.wake.timeout = 10
        self.wake.interval = 10
        task = asyncio.create_task(self.wake.turn_on())
        await asyncio.sleep(0.001)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        with self.assertRaises(PJLinkError):
            await self.wake.turn_on()
        self.ir.assert_awaited_once()


class IdentificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_name_separate_from_user_name(self):
        client = PJLinkClient("unused")
        client.command = AsyncMock(side_effect=["1", "Cinema", "Panasonic", "PT-AE8000"])
        self.assertEqual(await client.identify(), {"name": "Cinema", "manufacturer": "Panasonic", "model": "PT-AE8000"})

    async def test_optional_unsupported_metadata(self):
        client = PJLinkClient("unused")
        client.command = AsyncMock(side_effect=["1", CommandError("ERR1"), "Panasonic", CommandError("ERR1")])
        self.assertEqual(await client.identify(), {"manufacturer": "Panasonic"})
