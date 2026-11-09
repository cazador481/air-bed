"""Air-Pedic mattress (ANM-* BLE pump controller) integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant

from .coordinator import AirPedicCoordinator

PLATFORMS = [Platform.BUTTON, Platform.NUMBER]

type AirPedicConfigEntry = ConfigEntry[AirPedicCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: AirPedicConfigEntry) -> bool:
    coordinator = AirPedicCoordinator(hass, entry, entry.data[CONF_ADDRESS])
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload(hass: HomeAssistant, entry: AirPedicConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: AirPedicConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
