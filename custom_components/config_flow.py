"""Config flow for the BM2 battery monitor integration.

Device validation is deliberately protocol-based rather than name-based.

A device is accepted when either:
1. a recognised Legacy or Enhanced BM2 advertisement is observed, or
2. an active connection exposes FFF4 and produces a valid decryptable BM2
   notification.

Known Bluetooth names are still useful for discovery, but are not themselves
treated as proof that the selected device is a BM2.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from bluetooth_data_tools import short_address
import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_discovered_service_info,
    async_process_advertisements,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS, CONF_SCAN_INTERVAL
from homeassistant.core import callback

from .bmx_ble import (
    BM2Generation,
    BMxBluetoothDeviceData as DeviceData,
)
from .const import (
    BATTERY_TYPES,
    BM_NAMES,
    CONF_BATTERY_TYPE,
    CONF_CUSTOM_BATTERY_CHEMISTRY,
    CONF_CUSTOM_CHARGING_VOLTAGE,
    CONF_CUSTOM_CRITICAL_VOLTAGE,
    CONF_CUSTOM_FIFTY_PERCENT_VOLTAGE,
    CONF_CUSTOM_FLOATING_VOLTAGE,
    CONF_CUSTOM_HUNDRED_PERCENT_VOLTAGE,
    CONF_CUSTOM_LOW_VOLTAGE,
    CONF_CUSTOM_NUMPY_PERCENT,
    CONF_CUSTOM_NUMPY_VOLTS,
    CONF_SCAN_MODE,
    DEFAULT_BATTERY_TYPE,
    DEFAULT_CUSTOM_BATTERY_CHEMISTRY,
    DEFAULT_CUSTOM_CHARGING_VOLTAGE,
    DEFAULT_CUSTOM_CRITICAL_VOLTAGE,
    DEFAULT_CUSTOM_FIFTY_PERCENT_VOLTAGE,
    DEFAULT_CUSTOM_FLOATING_VOLTAGE,
    DEFAULT_CUSTOM_HUNDRED_PERCENT_VOLTAGE,
    DEFAULT_CUSTOM_LOW_VOLTAGE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCAN_MODE,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    SCAN_MODES,
)

_LOGGER = logging.getLogger(__name__)

# Some BM2s alternate advertisement packet types.  If the first/cached packet
# is inconclusive, briefly listen for another advertisement from the same
# address before attempting an active connection.
ADDITIONAL_ADVERTISEMENT_TIMEOUT = 10


@dataclass
class DiscoveredDevice:
    """A Bluetooth device offered by the manual config flow."""

    title: str
    discovery_info: BluetoothServiceInfoBleak


class BMxConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for a BM2 battery monitor."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> BMxOptionsFlow:
        """Get the options flow for this handler."""
        return BMxOptionsFlow()

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, DiscoveredDevice] = {}

    @staticmethod
    def _bm2_title(address: str) -> str:
        """Return the standard BM2 config-entry title."""
        return f"BM2 battery monitor ({short_address(address)})"

    @staticmethod
    def _manual_device_title(discovery_info: BluetoothServiceInfoBleak) -> str:
        """Return a useful title for an unvalidated manual-selection device."""
        address = discovery_info.address
        name = discovery_info.name

        if not name or name == address:
            return address

        return f"{name} ({address})"

    @staticmethod
    def _advertisement_is_bm2(
        device: DeviceData,
        discovery_info: BluetoothServiceInfoBleak,
    ) -> bool:
        """Process an advertisement and return whether it proves BM2 identity."""
        device.update(discovery_info)
        return device.bm2_generation is not BM2Generation.UNKNOWN

    async def _async_validate_device(
        self,
        discovery_info: BluetoothServiceInfoBleak,
    ) -> str:
        """Validate a selected/discovered Bluetooth device.

        Return one of:
            "valid_passive"
            "valid_active"
            "not_bm2"
            "cannot_validate"
        """
        address = discovery_info.address
        device = DeviceData()

        # First choice: protocol-specific passive validation.  This works even
        # where advertisements are receivable but a GATT connection is not.
        if self._advertisement_is_bm2(device, discovery_info):
            _LOGGER.debug(
                "%s validated as BM2 from %s advertisement",
                address,
                device.bm2_generation,
            )
            return "valid_passive"

        # BM2s can alternate packet types.  Give HA a chance to see a useful
        # Legacy/Enhanced packet before resorting to an active connection.
        def _process_advertisement(
            service_info: BluetoothServiceInfoBleak,
        ) -> bool:
            return self._advertisement_is_bm2(device, service_info)

        try:
            await async_process_advertisements(
                self.hass,
                _process_advertisement,
                {"address": address},
                BluetoothScanningMode.ACTIVE,
                ADDITIONAL_ADVERTISEMENT_TIMEOUT,
            )
        except TimeoutError:
            pass

        if device.bm2_generation is not BM2Generation.UNKNOWN:
            _LOGGER.debug(
                "%s validated as BM2 after additional advertisement (%s)",
                address,
                device.bm2_generation,
            )
            return "valid_passive"

        # Advertisement was inconclusive.  Try the active protocol once.
        #
        # Importantly, failure to CONNECT is not evidence that this is not a
        # BM2: marginal BLE reception can be sufficient for advertisements but
        # insufficient for a bidirectional GATT connection.
        ble_device = async_ble_device_from_address(
            self.hass,
            address,
            connectable=True,
        )

        if ble_device is None:
            _LOGGER.debug(
                "%s could not be actively validated: no connectable path",
                address,
            )
            return "cannot_validate"

        try:
            if await device.async_validate_active(ble_device):
                _LOGGER.debug("%s validated using active BM2 GATT protocol", address)
                return "valid_active"

            # We successfully connected and established that the BM2 protocol
            # is not present/valid.  This is a positive rejection.
            return "not_bm2"

        except Exception as ex:
            # Connection failure, timeout, etc. means "unknown", not "not BM2".
            _LOGGER.debug(
                "%s could not be actively validated as BM2: %s",
                address,
                ex,
            )
            return "cannot_validate"

    async def async_step_bluetooth(
        self,
        discovery_info: BluetoothServiceInfoBleak,
    ) -> ConfigFlowResult:
        """Handle Bluetooth discovery."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        validation = await self._async_validate_device(discovery_info)

        if validation == "not_bm2":
            return self.async_abort(reason="not_supported")

        if validation == "cannot_validate":
            return self.async_abort(reason="cannot_validate")

        self._discovery_info = discovery_info
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Confirm a positively validated Bluetooth discovery."""
        assert self._discovery_info is not None

        title = self._bm2_title(self._discovery_info.address)

        if user_input is not None:
            return self.async_create_entry(title=title, data=user_input)

        self._set_confirm_only()

        placeholders = {"name": title}
        self.context["title_placeholders"] = placeholders

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_BATTERY_TYPE,
                    default=DEFAULT_BATTERY_TYPE,
                ): vol.In(BATTERY_TYPES)
            }
        )

        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=data_schema,
            description_placeholders=placeholders,
        )

    def _manual_schema(
        self,
        defaults: dict[str, Any] | None = None,
    ) -> vol.Schema:
        """Build the manual device-selection schema."""
        defaults = defaults or {}

        address_selector = vol.In(
            {
                address: discovery.title
                for address, discovery in self._discovered_devices.items()
            }
        )

        schema: dict[Any, Any] = {
            vol.Required(
                CONF_BATTERY_TYPE,
                default=defaults.get(
                    CONF_BATTERY_TYPE,
                    DEFAULT_BATTERY_TYPE,
                ),
            ): vol.In(BATTERY_TYPES),
        }

        if CONF_ADDRESS in defaults:
            schema[
                vol.Required(
                    CONF_ADDRESS,
                    default=defaults[CONF_ADDRESS],
                )
            ] = address_selector
        else:
            schema[vol.Required(CONF_ADDRESS)] = address_selector

        return vol.Schema(schema)

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Allow manual selection of any currently discovered BLE device."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_ADDRESS]

            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()

            selected = self._discovered_devices.get(address)

            # The Bluetooth cache can change while the form is open.  Rebuild
            # the list once if the originally selected entry has disappeared.
            if selected is None:
                self._populate_discovered_devices()
                selected = self._discovered_devices.get(address)

            if selected is None:
                errors["base"] = "cannot_validate"
            else:
                validation = await self._async_validate_device(
                    selected.discovery_info
                )

                if validation in ("valid_passive", "valid_active"):
                    # Store only actual config values; CONF_ADDRESS is the
                    # unique ID and does not need to be duplicated in entry.data.
                    entry_data = {
                        key: value
                        for key, value in user_input.items()
                        if key != CONF_ADDRESS
                    }

                    return self.async_create_entry(
                        title=self._bm2_title(address),
                        data=entry_data,
                    )

                if validation == "not_bm2":
                    errors["base"] = "not_bm2"
                else:
                    errors["base"] = "cannot_validate"

        self._populate_discovered_devices()

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=self._manual_schema(user_input),
            errors=errors,
        )

    def _populate_discovered_devices(self) -> None:
        """Refresh the manually selectable Bluetooth device list."""
        self._discovered_devices.clear()

        current_addresses = self._async_current_ids(include_ignore=False)

        for discovery_info in async_discovered_service_info(self.hass, False):
            address = discovery_info.address

            if address in current_addresses:
                continue

            # Display known-name devices as BM2 candidates, but still validate
            # them after selection.  Everything else remains available because
            # a genuine BM2 may advertise no local name at all.
            if discovery_info.name in BM_NAMES:
                title = self._bm2_title(address)
            else:
                title = self._manual_device_title(discovery_info)

            self._discovered_devices[address] = DiscoveredDevice(
                title=title,
                discovery_info=discovery_info,
            )


class BMxOptionsFlow(OptionsFlow):
    """Handle BM2 options."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle options flow page 1."""
        if user_input is not None:
            self.user_input = user_input

            if user_input[CONF_BATTERY_TYPE] == "Custom":
                return await self.async_step_custom_battery_details()

            # Deliberately save these settings into data, not options, to
            # preserve the existing integration behaviour.
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=self.user_input,
                options=self.config_entry.options,
            )
            return self.async_create_entry(title="", data={})

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_MODE,
                    default=self.config_entry.data.get(
                        CONF_SCAN_MODE,
                        DEFAULT_SCAN_MODE,
                    ),
                ): vol.In(SCAN_MODES),
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=self.config_entry.data.get(
                        CONF_SCAN_INTERVAL,
                        DEFAULT_SCAN_INTERVAL,
                    ),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Clamp(min=MIN_SCAN_INTERVAL),
                ),
                vol.Required(
                    CONF_BATTERY_TYPE,
                    default=self.config_entry.data.get(
                        CONF_BATTERY_TYPE,
                        DEFAULT_BATTERY_TYPE,
                    ),
                ): vol.In(BATTERY_TYPES),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
        )

    async def async_step_custom_battery_details(
        self,
        user_input_2: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle options flow page 2."""
        if user_input_2 is not None:
            temp_numpy_volts = [
                float(user_input_2[CONF_CUSTOM_CRITICAL_VOLTAGE]),
                float(user_input_2[CONF_CUSTOM_LOW_VOLTAGE]),
                float(user_input_2[CONF_CUSTOM_FIFTY_PERCENT_VOLTAGE]),
                float(user_input_2[CONF_CUSTOM_HUNDRED_PERCENT_VOLTAGE]),
            ]
            temp_numpy_percent = [0, 20, 50, 100]

            self.user_input = self.user_input | user_input_2
            self.user_input[CONF_CUSTOM_NUMPY_VOLTS] = temp_numpy_volts
            self.user_input[CONF_CUSTOM_NUMPY_PERCENT] = temp_numpy_percent

            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=self.user_input,
                options=self.config_entry.options,
            )
            return self.async_create_entry(title="", data={})

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_CUSTOM_BATTERY_CHEMISTRY,
                    default=self.config_entry.data.get(
                        CONF_CUSTOM_BATTERY_CHEMISTRY,
                        DEFAULT_CUSTOM_BATTERY_CHEMISTRY,
                    ),
                ): str,
                vol.Required(
                    CONF_CUSTOM_CRITICAL_VOLTAGE,
                    default=self.config_entry.data.get(
                        CONF_CUSTOM_CRITICAL_VOLTAGE,
                        DEFAULT_CUSTOM_CRITICAL_VOLTAGE,
                    ),
                ): vol.All(vol.Coerce(float), vol.Clamp(min=9.0, max=16.0)),
                vol.Required(
                    CONF_CUSTOM_LOW_VOLTAGE,
                    default=self.config_entry.data.get(
                        CONF_CUSTOM_LOW_VOLTAGE,
                        DEFAULT_CUSTOM_LOW_VOLTAGE,
                    ),
                ): vol.All(vol.Coerce(float), vol.Clamp(min=9.0, max=16.0)),
                vol.Required(
                    CONF_CUSTOM_FIFTY_PERCENT_VOLTAGE,
                    default=self.config_entry.data.get(
                        CONF_CUSTOM_FIFTY_PERCENT_VOLTAGE,
                        DEFAULT_CUSTOM_FIFTY_PERCENT_VOLTAGE,
                    ),
                ): vol.All(vol.Coerce(float), vol.Clamp(min=9.0, max=16.0)),
                vol.Required(
                    CONF_CUSTOM_HUNDRED_PERCENT_VOLTAGE,
                    default=self.config_entry.data.get(
                        CONF_CUSTOM_HUNDRED_PERCENT_VOLTAGE,
                        DEFAULT_CUSTOM_HUNDRED_PERCENT_VOLTAGE,
                    ),
                ): vol.All(vol.Coerce(float), vol.Clamp(min=9.0, max=16.0)),
                vol.Required(
                    CONF_CUSTOM_FLOATING_VOLTAGE,
                    default=self.config_entry.data.get(
                        CONF_CUSTOM_FLOATING_VOLTAGE,
                        DEFAULT_CUSTOM_FLOATING_VOLTAGE,
                    ),
                ): vol.All(vol.Coerce(float), vol.Clamp(min=9.0, max=16.0)),
                vol.Required(
                    CONF_CUSTOM_CHARGING_VOLTAGE,
                    default=self.config_entry.data.get(
                        CONF_CUSTOM_CHARGING_VOLTAGE,
                        DEFAULT_CUSTOM_CHARGING_VOLTAGE,
                    ),
                ): vol.All(vol.Coerce(float), vol.Clamp(min=9.0, max=16.0)),
            }
        )

        return self.async_show_form(
            step_id="custom_battery_details",
            data_schema=data_schema,
        )