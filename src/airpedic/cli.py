"""Command line control: ``airpedic status | set | stop | scan``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os

from .bed import AirPedicBed, discover
from .protocol import MAX_FIRMNESS, MIN_FIRMNESS, Pressures, Side

SIDES = {"left": Side.LEFT, "right": Side.RIGHT, "both": Side.BOTH}


def _firmness(text: str) -> int:
    value = int(text)
    if not MIN_FIRMNESS <= value <= MAX_FIRMNESS:
        raise argparse.ArgumentTypeError(f"must be {MIN_FIRMNESS}..{MAX_FIRMNESS}")
    return value


def _print(p: Pressures) -> None:
    print(f"left : head/foot {p.left_head_foot:2d}  torso {p.left_torso:2d}")
    print(f"right: head/foot {p.right_head_foot:2d}  torso {p.right_torso:2d}")


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="airpedic", description="Control an Air-Pedic ANM-* mattress over BLE.")
    ap.add_argument(
        "--device",
        default=os.environ.get("AIRPEDIC_DEVICE"),
        help="advertised name (ANM-XXXXXXXX) or BLE address; default: $AIRPEDIC_DEVICE or first ANM-* found",
    )
    ap.add_argument(
        "--no-swap",
        action="store_true",
        help="use the controller's side labels instead of the corrected physical sides",
    )
    ap.add_argument("-v", "--verbose", action="store_true", help="log raw frames")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("scan", help="list nearby beds")
    sub.add_parser("status", help="print the four firmness readings")
    s = sub.add_parser("set", help="pump one side to a firmness (10 soft .. 50 firm)")
    s.add_argument("side", choices=("left", "right"))
    s.add_argument("--head-foot", type=_firmness)
    s.add_argument("--torso", type=_firmness)
    s.add_argument("--no-wait", action="store_true", help="return once the pump starts")
    st = sub.add_parser("stop", help="stop the pump")
    st.add_argument("side", nargs="?", default="both", choices=tuple(SIDES))
    return ap


async def _run(args: argparse.Namespace) -> int:
    if args.command == "scan":
        for d in await discover():
            print(d.address, d.name)
        return 0

    async with await AirPedicBed.connect(args.device or None, swap_sides=not args.no_swap) as bed:
        if args.command == "status":
            _print(await bed.query())
        elif args.command == "set":
            if args.head_foot is None and args.torso is None:
                print("give --head-foot and/or --torso")
                return 2
            result = await bed.set_side(SIDES[args.side], args.head_foot, args.torso, wait=not args.no_wait)
            if result is not None:
                _print(result)
        elif args.command == "stop":
            await bed.stop(SIDES[args.side])
    return 0


def main() -> None:
    args = _parser().parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, format="%(asctime)s %(message)s")
    logging.getLogger("bleak").setLevel(logging.WARNING)
    raise SystemExit(asyncio.run(_run(args)))
