"""Config flow: Bluetooth discovery of ANM-* beds plus a manual picker."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak, async_discovered_service_info
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback

from .const import CONF_SWAP_SIDES, DEFAULT_SWAP_SIDES, DOMAIN
from .lib.protocol import NAME_PREFIX


# Proxies scan passively, and the bed only sends its ANM-* name in scan
# responses, so also match its passive advertisement (see manifest.json).
PASSIVE_SERVICE_UUID = "0000ffb0-0000-1000-8000-00805f9b34fb"
PASSIVE_MANUFACTURER_ID = 0


def _is_bed(info: BluetoothServiceInfoBleak) -> bool:
    if (info.name or "").upper().startswith(NAME_PREFIX):
        return True
    return PASSIVE_MANUFACTURER_ID in info.manufacturer_data and PASSIVE_SERVICE_UUID in info.service_uuids


def _title(info: BluetoothServiceInfoBleak) -> str:
    name = info.name or ""
    return name if name.upper().startswith(NAME_PREFIX) else f"Air-Pedic {info.address}"


class AirPedicConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovered: BluetoothServiceInfoBleak | None = None
        self._candidates: dict[str, str] = {}  # address -> advertised name

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return AirPedicOptionsFlow()

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> ConfigFlowResult:
        if not _is_bed(discovery_info):
            return self.async_abort(reason="not_supported")
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovered = discovery_info
        self.context["title_placeholders"] = {"name": _title(discovery_info)}
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._discovered is not None
        title = _title(self._discovered)
        if user_input is not None:
            return self.async_create_entry(title=title, data={CONF_ADDRESS: self._discovered.address})
        self._set_confirm_only()
        return self.async_show_form(step_id="confirm", description_placeholders={"name": title})

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=self._candidates[address], data={CONF_ADDRESS: address})

        configured = self._async_current_ids(include_ignore=False)
        self._candidates = {
            info.address: _title(info)
            for info in async_discovered_service_info(self.hass, connectable=True)
            if _is_bed(info) and info.address not in configured
        }
        if not self._candidates:
            return self.async_abort(reason="no_devices_found")
        labels = {address: f"{title} ({address})" for address, title in self._candidates.items()}
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(labels)})
        )


class AirPedicOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_SWAP_SIDES, DEFAULT_SWAP_SIDES)
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema({vol.Required(CONF_SWAP_SIDES, default=current): bool})
        )
