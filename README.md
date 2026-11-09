# airpedic

Local Bluetooth LE control of an Air-Pedic air mattress (American National
Manufacturing pump, advertises as `ANM-XXXXXXXX`) from Python and Home Assistant.
No cloud access, and the phone app isn't needed.

The pump has four zones: left/right × head-foot/torso. Firmness runs from 10 (soft) to 50 (firm).

## Python / CLI

```sh
uv sync
uv run airpedic scan                                  # find beds
uv run airpedic status
uv run airpedic set left --head-foot 35 --torso 40    # waits until the pump reports done
uv run airpedic set right --torso 30 --no-wait        # pump finishes on its own
uv run airpedic stop                                  # stop both sides
```

`--device ANM-33DF2570` (or `$AIRPEDIC_DEVICE`) picks a bed. Without it, the CLI uses the first bed it finds.
`-v` logs raw frames.

```python
from airpedic import AirPedicBed, Side

async with await AirPedicBed.connect("ANM-33DF2570") as bed:
    print(await bed.query())
    await bed.set_side(Side.LEFT, head_foot=35)   # torso left unchanged
```

### Left vs right

The controller (and the phone app) label the sides mirrored relative to the bed
as you lie in it. Sides here are physical, with the controller labels swapped by
default. If they come out backwards, use `--no-swap` / `swap_sides=False`, or
untick *Swap left/right* in the HA integration options.

## Home Assistant

Copy the integration, following the `lib` symlink:

```sh
cp -rL custom_components/airpedic /config/custom_components/
```

Restart HA. The bed is auto-discovered over Bluetooth, or you can add it under
*Settings → Devices & services → Add integration → Air-Pedic Mattress*.
The integration needs a Bluetooth adapter in range of the bed, or an
[ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html)
placed near it.

Entities: `number.*_{left,right}_{head_foot,torso}` (sliders, 10–50) and `button.*_stop_pump`.
The integration connects only for each read or command. It reads the sensors
every 5 minutes, and again 30 s and 95 s after a change. A set returns as soon
as the pump has accepted the new targets.

## One connection at a time

The bed's BLE module accepts a single connection. While the phone app is open it
holds that connection and auto-reconnects, so HA and the CLI can't connect.
Swipe the app closed when you want them in control.

## Protocol

Transport is a SZ RF-Star BLE-UART module. Commands are written to `FFE9`
(service `FFE5`). Replies arrive as notifications on `FFE4` (service `FFE0`).
Every message in both directions is a 10-byte frame:

```
55 PORTS CMD A B 00 00 SIDE SUM AA      SUM = (byte0 + … + byte7) & 0xFF
```

`PORTS` = 4 for this pump. `SIDE`: 01 both, 02 right, 03 left (controller labels).

| CMD | Request | Reply |
| --- | --- | --- |
| `83` query | side 01 | `55 04 83 Rtorso Rhf Ltorso Lhf 01 SUM AA` |
| `92` controller kind | side 01 | byte 1 = port count |
| `69` reserve side | side 02/03 | echo `69` |
| `03` set targets | `A` = torso, `B` = head/foot | echo, then `99` (pumping) …, then `85` (targets reached) |
| `04` stop | side | — |
| — | — | `88` pump busy; `79` controller busy, resend (seen about 1 in 15 requests) |

To change firmness: send reserve → wait for the `69` echo → send set targets.
The pump completes even after BLE disconnects. The phone app sends a stop if it
gets no `85` within 90 s.

This was reverse engineered from the Android app `com.reliefmart.airpedicbed` 1.2.238
(`BTService`, `d.a.a.b.l`) and checked against a live bed. The app also contains
a second protocol (service `57e34968-…`) for `RAS-*` beds, which this project
does not implement.

## Tests

```sh
uv run pytest
```
