"""Air-Pedic (American National Manufacturing "ANM-*") BLE mattress protocol.

Reverse engineered from the Android app ``com.reliefmart.airpedicbed`` 1.2.238
(classes ``d.a.a.b.l`` / ``d.a.a.b.s`` / ``BTService``) and verified live.

Transport: a SZ RF-Star BLE-UART module.
  * write commands to characteristic FFE9 (service FFE5)
  * responses arrive as notifications on FFE4 (service FFE0)

Every message in both directions is a 10-byte frame::

    0x55 PORTS CMD A B 0x00 0x00 SIDE SUM 0xAA

``SUM`` is the low byte of the sum of bytes 0..7. ``PORTS`` is 4 for the
four-zone pump (left/right x head-foot/torso), 2 for a two-zone pump.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

SERVICE_UUID = "0000ffe5-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000ffe9-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000ffe4-0000-1000-8000-00805f9b34fb"

NAME_PREFIX = "ANM"
FRAME_LEN = 10
START = 0x55
END = 0xAA

MIN_FIRMNESS = 10
MAX_FIRMNESS = 50


class Side(IntEnum):
    BOTH = 0x01
    RIGHT = 0x02
    LEFT = 0x03


class Cmd(IntEnum):
    """Command / response codes (byte 2 of a frame)."""

    INFLATE = 0x01
    DEFLATE = 0x02
    SET_TARGETS = 0x03
    STOP = 0x04
    RESERVE = 0x69  # claim a side before SET_TARGETS; echoed back as ack
    RETRY = 0x79  # sporadic reply (~1 in 15 requests): controller busy, resend. Not handled by the app.
    QUERY = 0x83  # read all four pressure sensors
    TARGETS_REACHED = 0x85
    PUMP_BUSY = 0x88
    ADJUSTING = 0x99  # pump accepted targets and is running
    CONTROLLER_KIND = 0x92  # reply byte 1 = number of pump ports


class ProtocolError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Pressures:
    """Firmness readings, 10 (soft) .. 50 (firm)."""

    left_head_foot: int
    left_torso: int
    right_head_foot: int
    right_torso: int

    def for_side(self, side: Side) -> tuple[int, int]:
        """Return ``(head_foot, torso)`` for one side."""
        if side is Side.LEFT:
            return self.left_head_foot, self.left_torso
        if side is Side.RIGHT:
            return self.right_head_foot, self.right_torso
        raise ValueError("side must be LEFT or RIGHT")


def checksum(data: bytes | bytearray) -> int:
    return sum(data[:8]) & 0xFF


def encode(cmd: int, side: Side = Side.BOTH, a: int = 0, b: int = 0, ports: int = 4) -> bytes:
    """Build a command frame.

    For SET_TARGETS on a 4-port pump: ``a`` = torso, ``b`` = head/foot.
    On a 2-port pump the app sends ``a`` = 0 and the single value in ``b``.
    """
    frame = bytearray((START, ports, cmd & 0xFF, a & 0xFF, b & 0xFF, 0, 0, side, 0, END))
    frame[8] = checksum(frame)
    return bytes(frame)


def set_targets(side: Side, head_foot: int, torso: int) -> bytes:
    if side not in (Side.LEFT, Side.RIGHT):
        raise ValueError("targets are set per side (LEFT or RIGHT)")
    for value in (head_foot, torso):
        if not MIN_FIRMNESS <= value <= MAX_FIRMNESS:
            raise ValueError(f"firmness must be {MIN_FIRMNESS}..{MAX_FIRMNESS}, got {value}")
    return encode(Cmd.SET_TARGETS, side, torso, head_foot)


def validate(frame: bytes) -> bytes:
    if len(frame) != FRAME_LEN or frame[0] != START or frame[9] != END:
        raise ProtocolError(f"bad frame {frame.hex(' ')}")
    if frame[8] != checksum(frame):
        raise ProtocolError(f"bad checksum {frame.hex(' ')}")
    return frame


def wire_side(side: Side, swap_sides: bool) -> Side:
    """Map a physical side to the controller's side byte.

    The controller's (and the app's) LEFT/RIGHT can be the mirror image of the
    sides as you lie in bed; ``swap_sides`` corrects that.
    """
    if swap_sides and side is not Side.BOTH:
        return Side.RIGHT if side is Side.LEFT else Side.LEFT
    return side


def decode_pressures(frame: bytes, swap_sides: bool = False) -> Pressures:
    """Decode a QUERY (0x83) reply: ``55 04 83 Rt Rhf Lt Lhf ...`` (controller sides)."""
    validate(frame)
    if frame[2] != Cmd.QUERY:
        raise ProtocolError(f"not a query reply: {frame.hex(' ')}")
    right_torso, right_hf, left_torso, left_hf = frame[3], frame[4], frame[5], frame[6]
    if swap_sides:
        right_torso, right_hf, left_torso, left_hf = left_torso, left_hf, right_torso, right_hf
    return Pressures(
        right_torso=right_torso,
        right_head_foot=right_hf,
        left_torso=left_torso,
        left_head_foot=left_hf,
    )


class FrameAssembler:
    """Reassembles 10-byte frames from arbitrarily split notifications."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        self._buf += data
        frames: list[bytes] = []
        while True:
            start = self._buf.find(START)
            if start < 0:
                self._buf.clear()
                return frames
            del self._buf[:start]
            if len(self._buf) < FRAME_LEN:
                return frames
            candidate = bytes(self._buf[:FRAME_LEN])
            try:
                frames.append(validate(candidate))
                del self._buf[:FRAME_LEN]
            except ProtocolError:
                del self._buf[:1]  # resync on the next 0x55
