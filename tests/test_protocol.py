"""Frames below were captured from a live ANM-33DF2570 on 2026-11-08."""

import pytest

from airpedic.protocol import (
    Cmd,
    FrameAssembler,
    ProtocolError,
    Side,
    decode_pressures,
    encode,
    set_targets,
    wire_side,
)

QUERY_REPLY = bytes.fromhex("55 04 83 32 32 2e 2a 01 99 aa")  # R torso 50, R hf 50, L torso 46, L hf 42


@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        (encode(Cmd.QUERY), "55 04 83 00 00 00 00 01 dd aa"),
        (encode(Cmd.CONTROLLER_KIND), "55 04 92 00 00 00 00 01 ec aa"),
        (encode(Cmd.RESERVE, Side.LEFT), "55 04 69 00 00 00 00 03 c5 aa"),
        (set_targets(Side.LEFT, head_foot=42, torso=45), "55 04 03 2d 2a 00 00 03 b6 aa"),
    ],
)
def test_encode_matches_frames_the_bed_accepted(frame, expected):
    assert frame == bytes.fromhex(expected)


def test_decode_controller_sides():
    p = decode_pressures(QUERY_REPLY)
    assert (p.left_head_foot, p.left_torso, p.right_head_foot, p.right_torso) == (42, 46, 50, 50)


def test_swap_mirrors_decode_and_commands_consistently():
    p = decode_pressures(QUERY_REPLY, swap_sides=True)
    assert p.for_side(Side.RIGHT) == (42, 46)
    assert p.for_side(Side.LEFT) == (50, 50)
    # Commanding physical RIGHT must address the zone it reads from (controller LEFT).
    assert wire_side(Side.RIGHT, swap_sides=True) is Side.LEFT
    assert wire_side(Side.BOTH, swap_sides=True) is Side.BOTH


@pytest.mark.parametrize("value", [9, 51])
def test_set_targets_rejects_out_of_range(value):
    with pytest.raises(ValueError):
        set_targets(Side.LEFT, head_foot=value, torso=30)


def test_decode_rejects_bad_checksum():
    with pytest.raises(ProtocolError):
        decode_pressures(QUERY_REPLY[:8] + b"\x00\xaa")


def test_assembler_handles_split_and_garbage():
    asm = FrameAssembler()
    reached = bytes.fromhex("55 04 85 00 00 00 00 01 df aa")
    assert asm.feed(b"\x00\x13" + QUERY_REPLY[:4]) == []
    assert asm.feed(QUERY_REPLY[4:] + reached[:3]) == [QUERY_REPLY]
    assert asm.feed(reached[3:]) == [reached]
