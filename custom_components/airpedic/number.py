"""Four firmness controls: left/right x head-foot/torso (10 soft .. 50 firm)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AirPedicConfigEntry
from .entity import AirPedicEntity
from .lib.protocol import MAX_FIRMNESS, MIN_FIRMNESS, Pressures, Side


@dataclass(frozen=True, kw_only=True)
class ZoneDescription(NumberEntityDescription):
    side: Side
    zone: str  # "head_foot" or "torso": the set_side keyword and Pressures field suffix

    @property
    def read(self) -> Callable[[Pressures], int]:
        attr = f"{self.side.name.lower()}_{self.zone}"
        return lambda p: getattr(p, attr)


ZONES = tuple(
    ZoneDescription(key=f"{side.name.lower()}_{zone}", side=side, zone=zone, icon="mdi:bed")
    for side in (Side.LEFT, Side.RIGHT)
    for zone in ("head_foot", "torso")
)


async def async_setup_entry(
    hass: HomeAssistant, entry: AirPedicConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(ZoneNumber(entry.runtime_data, d) for d in ZONES)


class ZoneNumber(AirPedicEntity, NumberEntity):
    entity_description: ZoneDescription
    _attr_native_min_value = MIN_FIRMNESS
    _attr_native_max_value = MAX_FIRMNESS
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator, description: ZoneDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int | None:
        data = self.coordinator.data
        return None if data is None else self.entity_description.read(data)

    async def async_set_native_value(self, value: float) -> None:
        d = self.entity_description
        await self.coordinator.async_set(d.side, **{d.zone: int(value)})
