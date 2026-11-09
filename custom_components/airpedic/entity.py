from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AirPedicCoordinator


class AirPedicEntity(CoordinatorEntity[AirPedicCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: AirPedicCoordinator, key: str) -> None:
        super().__init__(coordinator)
        address = coordinator.address
        self._attr_unique_id = f"{address}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            connections={(CONNECTION_BLUETOOTH, address)},
            name=coordinator.config_entry.title,
            manufacturer="American National Manufacturing",
            model="Air-Pedic 4-zone pump",
        )
