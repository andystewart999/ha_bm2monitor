"""Config flow for Integration 101 Template integration."""

from __future__ import annotations

import logging
from typing import Any

from bleak.exc import BleakError, BleakCharacteristicNotFoundError

from bluetooth_data_tools import human_readable_name, short_address
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow
)
from homeassistant.const import (
#    CONF_HOST,
#    CONF_USERNAME,
#    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_ADDRESS
)

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak, async_discovered_service_info
from homeassistant.data_entry_flow import FlowResult

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .api import API #, APIConnectionError, APIAuthError 
from .const import (
    DOMAIN,
    DEFAULT_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    BATTERY_TYPES,
    CONF_BATTERY_TYPE,
    DEFAULT_BATTERY_TYPE,
    CONF_PERSISTENT_CONNECTION,
    DEFAULT_PERSISTENT_CONNECTION
)

_LOGGER = logging.getLogger(__name__)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.
       Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    # TODO validate the data can be used to set up a connection.

    # If your PyPI package is not built with async, pass your methods
    # to the executor:
    # await hass.async_add_executor_job(
    #     your_validate_func, data[CONF_USERNAME], data[CONF_PASSWORD]
    # )

    # Error handling is managed via async_step_user
    api = API(hass, data[CONF_ADDRESS], DEFAULT_BATTERY_TYPE, DEFAULT_PERSISTENT_CONNECTION)
    await api.read_gatt()  

        
    # Check _gotdata
    if not api.gotdata:
        return None

    return {
        "title": f"BM2 battery monitor ({short_address(data[CONF_ADDRESS])})",
        "address": data[CONF_ADDRESS]
    }

class ExampleConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Example Integration."""

    VERSION = 1
    _input_data: dict[str, Any]

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ExampleOptionsFlowHandler:
        """Get the options flow for this handler."""
        return ExampleOptionsFlowHandler()

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> FlowResult:
         """ Handle the bluetooth discovery step - the discovery filter should only pick up BM2 battery monitors """
        #  _LOGGER.error("New discovery info: %s", discovery_info)
        #  _LOGGER.error("New discovery info: mfr_id = %s", discovery_info.manufacturer_id)
        #  _LOGGER.error("New discovery info: service_uuid = %s", discovery_info.service_uuids)
        #  _LOGGER.error("New discovery info: mfr_data = %s", discovery_info.manufacturer_data)
        #  _LOGGER.error("New discovery info: mfr_data.type = %s", type(discovery_info.manufacturer_data))

         await self.async_set_unique_id(discovery_info.address)
         self._abort_if_unique_id_configured()
 
         self._discovery_info = discovery_info
         self.context["title_placeholders"] = {"name": "BM2 battery monitor (" + short_address(discovery_info.address) + ")"}

         return await self.async_step_user()


    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        # Called when you initiate adding an integration via the UI
        errors: dict[str, str] = {}

        if user_input is not None:
            # The form has been filled in and submitted, so process the data provided.
            try:
                # Validate that the setup data is valid and if not handle errors.
                # The errors["base"] values match the values in your strings.json and translation files.
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                _LOGGER.error("In config_flow/async_step_user/CannotConnect")
                errors["base"] = "cannot_connect"
            # except InvalidAuth:
            #     _LOGGER.error("In config_flow/async_step_user/InvalidAuth")
            #     errors["base"] = "invalid_auth"
            except InvalidGATT:
                _LOGGER.error("In config_flow/async_step_user/InvalidGATT")
                errors["base"] = "invalid_gatt"
            except BleakCharacteristicNotFoundError as exc:
                _LOGGER.error("In config_flow/async_step_user/BleakCharacteristicNotFoundError")
                errors["base"] = "invalid_gatt"
            except BleakError as exc:
                _LOGGER.error("In config_flow/async_step_user/BleakError - exc = " + str(exc))
                errors["base"] = "generic_bleak"
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.exception("In config_flow/async_step_user/Exception - " + str(err))
                errors["base"] = "unknown"

            if "base" not in errors:
                # Validation was successful, so create a unique id for this instance of your integration
                # and create the config entry.

                discovery_info = self._discovered_devices[info.get("address")]
                await self.async_set_unique_id(discovery_info.address)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

        """ Show the form, but first populate the listbox with discovered Bluetooth devices,
            or the specific Bluetooth device that was discovered via the manifest lookup """
        if discovery := self._discovery_info:
            self._discovered_devices[discovery.address] = discovery
        else:
            current_addresses = self._async_current_ids()
            for discovery in async_discovered_service_info(self.hass):
                # if (
                #     discovery.address in current_addresses
                #     or discovery.address in self._discovered_devices
                # ):
                if (
                    discovery.address in current_addresses
                    or discovery.address in self._discovered_devices
                ):
                    continue

                # Filter a bit to only show connectable devices
                if discovery.connectable == True:
                    self._discovered_devices[discovery.address] = discovery

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        # TODO adjust the data schema to the data that you need

        STEP_USER_DATA_SCHEMA = vol.Schema(
            {
#                vol.Required(CONF_HOST, description={"suggested_value": "10.10.10.1"}): str,
#                vol.Required(CONF_USERNAME, description={"suggested_value": "test"}): str,
#                vol.Required(CONF_PASSWORD, description={"suggested_value": "1234"}): str,
                vol.Required(CONF_ADDRESS, description={}): vol.In(
                    {
                        service_info.address: (f"{service_info.name} - ({service_info.address})")
                        for service_info in self._discovered_devices.values()
                    }),
#                vol.Required(CONF_BATTERY_TYPE, default=DEFAULT_BATTERY_TYPE): vol.In(BATTERY_TYPES)
            }
        )

        # Show initial form.
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class ExampleOptionsFlowHandler(OptionsFlow):
    """Handles the options flow."""

    def __init__(self) -> None:
        """Initialize options flow."""
        #self.config_entry = config_entry
        #self.options = dict(config_entry.options)

    async def async_step_init(self, user_input=None) -> FlowResult:
        """Handle options flow."""
        if user_input is not None:
            #options = self.config_entry.options | user_input

            return self.async_create_entry(title="", data=user_input)

        # Populate the schema with default values or whatever's been set already
        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): (vol.All(vol.Coerce(int), vol.Clamp(min=MIN_SCAN_INTERVAL))),
                vol.Required(
                    CONF_BATTERY_TYPE,
                    default=self.config_entry.options.get(CONF_BATTERY_TYPE, DEFAULT_BATTERY_TYPE),
                ): vol.In(BATTERY_TYPES),
                vol.Required(
                    CONF_PERSISTENT_CONNECTION,
                    default=self.config_entry.options.get(CONF_PERSISTENT_CONNECTION, DEFAULT_PERSISTENT_CONNECTION),
                ): bool,
            }
        )

        return self.async_show_form(step_id="init", data_schema=data_schema)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""

# class InvalidAuth(HomeAssistantError):
#     """Error to indicate there is invalid auth."""

class InvalidGATT(HomeAssistantError):
    """Error to indicate there is an issue reading the BM2 characteristic."""
