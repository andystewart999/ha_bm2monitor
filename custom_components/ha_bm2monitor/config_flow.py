"""Config flow for BMx BLE integration."""

from __future__ import annotations

from typing import Any

from .bmx_ble import BMxBluetoothDeviceData as DeviceData
import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from bluetooth_data_tools import short_address
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_SCAN_INTERVAL, CONF_ADDRESS
from homeassistant.core import callback

from .const import (
    DOMAIN,
    SCAN_MODES,
    CONF_SCAN_MODE,
    DEFAULT_SCAN_MODE,
    DEFAULT_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    BATTERY_TYPES,
    CONF_BATTERY_TYPE,
    DEFAULT_BATTERY_TYPE,
    BM_NAMES
)

import logging
_LOGGER = logging.getLogger(__name__)


class BMxConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the BMx monitor"""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> BMxOptionsFlow:
        """Get the options flow for this handler."""
        return BMxOptionsFlow()

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_device: DeviceData | None = None
        self._discovered_devices: dict[str, str] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle the bluetooth discovery step."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        device = DeviceData()
        
        if not discovery_info.name in BM_NAMES:
            _LOGGER.error("bm2 - device not supported - " + str(discovery_info.address))
            return self.async_abort(reason="not_supported")

        self._discovery_info = discovery_info
        self._discovered_device = device
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm discovery."""

        assert self._discovered_device is not None
        device = self._discovered_device
        assert self._discovery_info is not None
        discovery_info = self._discovery_info
        title = "BM2 battery monitor (" + short_address(discovery_info.address) + ")"
        
        # In this scenario (an auto-discovered device) there aren't any questions to ask, so ideally just go ahead and add it
        # When I went straight into async_create_entry though, for some reason it broke device removal!  So we get an informational 'OK to add' confnfirmation
        if user_input is not None:
            return self.async_create_entry(title=title, data={})

        self._set_confirm_only()
        placeholders = {"name": title}
        self.context["title_placeholders"] = placeholders
        return self.async_show_form(
            step_id="bluetooth_confirm", description_placeholders=placeholders
        )


    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user step to pick discovered device."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=self._discovered_devices[address], data={}
            )

        current_addresses = self._async_current_ids(include_ignore=False)
        for discovery_info in async_discovered_service_info(self.hass, False):
            _LOGGER.error("in config_flow/async_step_user: %s", str(discovery_info.name))
            address = discovery_info.address
            if address in current_addresses or address in self._discovered_devices:
                continue
            device = DeviceData()

            if discovery_info.name in BM_NAMES:
                self._discovered_devices[address] = (
                    "BM2 battery monitor (" + short_address(discovery_info.address) + ")"
                )

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In(self._discovered_devices)}
            )

        return self.async_show_form(
            step_id="user", data_schema=data_schema
        )

class BMxOptionsFlow(OptionsFlow):
    """Handles the options flow."""

    async def async_step_init(self, user_input=None) -> FlowResult:
        """Handle options flow."""
        if user_input is not None:
            #options = self.config_entry.options | user_input
            return self.async_create_entry(title="", data=user_input)

        # Populate the schema with default values or whatever's been set already
        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_MODE,
                    default=self.config_entry.options.get(CONF_SCAN_MODE, DEFAULT_SCAN_MODE),
                ): vol.In(SCAN_MODES),
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): (vol.All(vol.Coerce(int), vol.Clamp(min=MIN_SCAN_INTERVAL))),
                vol.Required(
                    CONF_BATTERY_TYPE,
                    default=self.config_entry.options.get(CONF_BATTERY_TYPE, DEFAULT_BATTERY_TYPE),
                ): vol.In(BATTERY_TYPES),
            }
        )

        return self.async_show_form(step_id="init", data_schema=data_schema)
        
