from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AirPedicConfigEntry
from .entity import AirPedicEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: AirPedicConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([StopButton(entry.runtime_data)])


class StopButton(AirPedicEntity, ButtonEntity):
    _attr_icon = "mdi:stop"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "stop")

    async def async_press(self) -> None:
        await self.coordinator.async_stop()
