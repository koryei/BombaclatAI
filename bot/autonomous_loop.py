"""Background tasks that give the bot its unprompted behavior.

Both loops are self-healing: any exception inside a single iteration is
caught and logged, and the loop keeps running on its normal schedule rather
than dying silently and leaving the bot inert.
"""

import asyncio
import logging

import config

logger = logging.getLogger(__name__)


class AutonomousLoop:
    def __init__(self, brain):
        self.brain = brain
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(config.AUTONOMOUS_LOOP_INTERVAL_SECONDS)
            try:
                await self.brain.autonomous_tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Autonomous loop iteration failed")


class PresenceLoop:
    def __init__(self, brain):
        self.brain = brain
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        while True:
            try:
                await self.brain.evolve_presence()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Presence loop iteration failed")
            await asyncio.sleep(self.brain.presence_cycle_delay_seconds())
