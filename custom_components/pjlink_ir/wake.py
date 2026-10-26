"""Transport-independent wake state machine, also tested without Home Assistant."""

import asyncio

from .client import ConnectionUnavailable, PJLinkError


class WakeController:
    """Serialize operations and send at most one IR command per wake attempt."""

    def __init__(self, client, send_ir, timeout=90, interval=2):
        self.client = client
        self.send_ir = send_ir
        self.timeout = timeout
        self.interval = interval
        self.lock = asyncio.Lock()
        self.ir_guard_until = 0.0

    async def turn_on(self):
        async with self.lock:
            try:
                power = await self.client.power()
            except ConnectionUnavailable:
                loop = asyncio.get_running_loop()
                # Also guard later calls after a timed-out/ambiguous IR attempt.
                if loop.time() < self.ir_guard_until:
                    raise PJLinkError("Previous IR wake is still uncertain; wait before retrying")
                self.ir_guard_until = loop.time() + self.timeout
                await self.send_ir()
                try:
                    async with asyncio.timeout(self.timeout):
                        while True:
                            await asyncio.sleep(self.interval)
                            try:
                                power = await self.client.power()
                            except ConnectionUnavailable:
                                continue
                            # Never send a network Power On after IR: report actual state.
                            if power in ("1", "3"):
                                self.ir_guard_until = 0.0
                                return
                except TimeoutError as err:
                    # Keep a short cooldown even after the wait has expired.
                    self.ir_guard_until = loop.time() + 30
                    raise PJLinkError("IR sent; projector did not confirm power on in time") from err
            else:
                if power in ("1", "3"):
                    return
                if power == "2":
                    raise PJLinkError("Projector is cooling; wait before switching on")
                await self.client.command("POWR", "1")
