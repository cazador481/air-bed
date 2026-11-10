"""Async bleak client for Air-Pedic ANM-* mattresses."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from .protocol import (
    NAME_PREFIX,
    NOTIFY_UUID,
    WRITE_UUID,
    Cmd,
    FrameAssembler,
    Pressures,
    ProtocolError,
    Side,
    decode_pressures,
    encode,
    set_targets,
    wire_side,
)

_LOGGER = logging.getLogger(__name__)

REPLY_TIMEOUT = 5.0
# The app gives the pump 90 s after it starts before forcing a STOP.
ADJUST_TIMEOUT = 90.0
RETRY_ATTEMPTS = 5
RETRY_DELAY = 0.3


def _is_bed(device: BLEDevice, adv: AdvertisementData) -> bool:
    return (adv.local_name or device.name or "").upper().startswith(NAME_PREFIX)


async def discover(timeout: float = 15.0) -> list[BLEDevice]:
    """Return every advertising ANM-* bed seen within ``timeout``."""
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    return [device for device, adv in found.values() if _is_bed(device, adv)]


async def find_bed(name: str | None = None, timeout: float = 30.0) -> BLEDevice | None:
    """Return the first bed seen (or the one advertising ``name``) as soon as it appears."""
    if name is None:
        return await BleakScanner.find_device_by_filter(_is_bed, timeout=timeout)
    return await BleakScanner.find_device_by_name(name, timeout=timeout)


class AirPedicBed:
    """One BLE session with the bed's pump controller.

    Sides are physical sides as you lie in bed; the controller's labels match
    them. ``swap_sides`` mirrors left/right for setups where they don't.

    The controller accepts a single connection: while this is connected the
    phone app cannot reach the bed, so keep sessions short.
    """

    def __init__(self, client: BleakClient, *, swap_sides: bool = False) -> None:
        self._client = client
        self._swap = swap_sides
        self._assembler = FrameAssembler()
        self._frames: asyncio.Queue[bytes] = asyncio.Queue()
        self._lock = asyncio.Lock()

    @classmethod
    async def connect(
        cls, target: BLEDevice | str | None = None, *, swap_sides: bool = False, timeout: float = 30.0
    ) -> AirPedicBed:
        """Connect by BLEDevice, address, advertised name (``ANM-33DF2570``), or the first bed found."""
        if target is None or (isinstance(target, str) and target.upper().startswith(NAME_PREFIX)):
            device = await find_bed(target, timeout=timeout)
            if device is None:
                raise ConnectionError(f"{target or 'no ANM-* bed'} not found")
            target = device
        client = BleakClient(target, timeout=timeout)
        await client.connect()
        bed = cls(client, swap_sides=swap_sides)
        try:
            await bed.start()
        except BaseException:
            await client.disconnect()
            raise
        return bed

    async def start(self) -> None:
        """Subscribe to notifications on an already connected client."""
        await self._client.start_notify(NOTIFY_UUID, self._on_notify)

    async def close(self) -> None:
        if self._client.is_connected:
            await self._client.disconnect()

    async def __aenter__(self) -> AirPedicBed:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    @property
    def is_connected(self) -> bool:
        return self._client.is_connected

    def _on_notify(self, _char: object, data: bytearray) -> None:
        for frame in self._assembler.feed(bytes(data)):
            _LOGGER.debug("<- %s", frame.hex(" "))
            self._frames.put_nowait(frame)

    async def _send(self, frame: bytes) -> None:
        _LOGGER.debug("-> %s", frame.hex(" "))
        await self._client.write_gatt_char(WRITE_UUID, frame, response=True)

    async def _expect(self, codes: Iterable[int], timeout: float) -> bytes:
        wanted = set(codes)
        async with asyncio.timeout(timeout):
            while True:
                frame = await self._frames.get()
                if frame[2] in wanted:
                    return frame
                _LOGGER.debug("ignoring %s while waiting for %s", frame.hex(" "), wanted)

    def _drain(self) -> None:
        while not self._frames.empty():
            self._frames.get_nowait()

    async def _request(self, frame: bytes, codes: Iterable[int], timeout: float = REPLY_TIMEOUT) -> bytes:
        """Send ``frame`` and return the first reply whose code is in ``codes``.

        The controller occasionally answers RETRY instead; resend in that case.
        """
        wanted = {*codes, Cmd.RETRY}
        for _ in range(RETRY_ATTEMPTS):
            self._drain()
            await self._send(frame)
            reply = await self._expect(wanted, timeout)
            if reply[2] != Cmd.RETRY:
                return reply
            _LOGGER.debug("controller asked to retry %s", frame.hex(" "))
            await asyncio.sleep(RETRY_DELAY)
        raise ProtocolError(f"controller kept answering RETRY to {frame.hex(' ')}")

    async def port_count(self) -> int:
        """2 or 4 pump ports (4 = separate head/foot and torso per side)."""
        async with self._lock:
            reply = await self._request(encode(Cmd.CONTROLLER_KIND), {Cmd.CONTROLLER_KIND})
        return reply[1]

    async def query(self) -> Pressures:
        """Read the four firmness sensors (10..50)."""
        async with self._lock:
            reply = await self._request(encode(Cmd.QUERY), {Cmd.QUERY})
        return decode_pressures(reply, self._swap)

    async def stop(self, side: Side = Side.BOTH) -> None:
        async with self._lock:
            self._drain()
            await self._send(encode(Cmd.STOP, wire_side(side, self._swap)))

    async def set_side(
        self,
        side: Side,
        head_foot: int | None = None,
        torso: int | None = None,
        *,
        wait: bool = True,
        timeout: float = ADJUST_TIMEOUT,
    ) -> Pressures | None:
        """Pump one side to the given firmness; ``None`` keeps a zone's current value.

        With ``wait`` the call returns the sensor readings once the pump reports
        targets reached; on timeout the side is stopped and TimeoutError raised.
        """
        if head_foot is None or torso is None:
            current_hf, current_torso = (await self.query()).for_side(side)
            head_foot = current_hf if head_foot is None else head_foot
            torso = current_torso if torso is None else torso
        wire = wire_side(side, self._swap)
        targets = set_targets(wire, head_foot, torso)

        async with self._lock:
            reply = await self._request(encode(Cmd.RESERVE, wire), {Cmd.RESERVE, Cmd.PUMP_BUSY})
            if reply[2] == Cmd.PUMP_BUSY:
                raise ProtocolError("pump is busy")
            await self._request(targets, {Cmd.SET_TARGETS})  # bed echoes the targets
            if not wait:
                return None
            try:
                await self._expect({Cmd.TARGETS_REACHED}, timeout)
            except TimeoutError:
                await self._send(encode(Cmd.STOP, wire))
                raise
        return await self.query()
