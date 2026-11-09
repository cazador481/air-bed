"""Connect-per-operation coordinator for the bed's single BLE connection."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime
from typing import TypeVar

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_SWAP_SIDES, DEFAULT_SWAP_SIDES, DOMAIN, SCAN_INTERVAL
from .lib.bed import AirPedicBed
from .lib.protocol import Pressures, Side

_LOGGER = logging.getLogger(__name__)
T = TypeVar("T")
SETTLE_REFRESH_DELAYS = (30, 95)


class AirPedicCoordinator(DataUpdateCoordinator[Pressures]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, address: str) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=SCAN_INTERVAL)
        self.address = address
        self._lock = asyncio.Lock()
        self._settle_unsubs: list[CALLBACK_TYPE] = []
        entry.async_on_unload(self.cancel_settle_refreshes)

    @property
    def swap_sides(self) -> bool:
        return self.config_entry.options.get(CONF_SWAP_SIDES, DEFAULT_SWAP_SIDES)

    async def _session(self, op: Callable[[AirPedicBed], Awaitable[T]]) -> T:
        """Connect, run ``op``, disconnect; so the phone app is not locked out."""
        async with self._lock:
            device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
            if device is None:
                raise UpdateFailed(f"{self.address} is not reachable by any Bluetooth adapter/proxy")
            client = await establish_connection(BleakClientWithServiceCache, device, device.name or self.address)
            bed = AirPedicBed(client, swap_sides=self.swap_sides)
            try:
                await bed.start()
                return await op(bed)
            finally:
                await bed.close()

    async def _async_update_data(self) -> Pressures:
        try:
            return await self._session(lambda bed: bed.query())
        except UpdateFailed:
            raise
        except Exception as err:
            raise UpdateFailed(str(err)) from err

    async def _command(self, op: Callable[[AirPedicBed], Awaitable[T]]) -> T:
        try:
            return await self._session(op)
        except HomeAssistantError:
            raise
        except Exception as err:
            raise HomeAssistantError(f"Air-Pedic command failed: {err}") from err

    async def async_set(self, side: Side, *, head_foot: int | None = None, torso: int | None = None) -> None:
        """Send new targets and return; the pump finishes on its own after we disconnect."""
        await self._command(lambda bed: bed.set_side(side, head_foot, torso, wait=False))
        if self.data is not None:
            prefix = side.name.lower()
            changes = {f"{prefix}_head_foot": head_foot, f"{prefix}_torso": torso}
            self.async_set_updated_data(replace(self.data, **{k: v for k, v in changes.items() if v is not None}))
        # Re-read real sensors once a typical adjustment (10-30 s) and the 90 s maximum are over.
        self.cancel_settle_refreshes()
        self._settle_unsubs = [async_call_later(self.hass, d, self._refresh_later) for d in SETTLE_REFRESH_DELAYS]

    @callback
    def cancel_settle_refreshes(self) -> None:
        for unsub in self._settle_unsubs:
            unsub()
        self._settle_unsubs.clear()

    async def _refresh_later(self, _now: datetime) -> None:
        await self.async_request_refresh()

    async def async_stop(self) -> None:
        await self._command(lambda bed: bed.stop(Side.BOTH))
        self.cancel_settle_refreshes()
        await self.async_request_refresh()
