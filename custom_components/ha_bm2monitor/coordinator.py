"""Integration 101 Template integration using DataUpdateCoordinator."""

from dataclasses import dataclass
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_SCAN_INTERVAL,
    CONF_ADDRESS
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import API #, APIAuthError
from .const import (
    DOMAIN,
    DEFAULT_SCAN_INTERVAL,
    CONF_BATTERY_TYPE,
    DEFAULT_BATTERY_TYPE,
    CONF_PERSISTENT_CONNECTION,
    DEFAULT_PERSISTENT_CONNECTION,
    Device,
    DeviceType
)
import asyncio
import datetime

_LOGGER = logging.getLogger(__name__)


@dataclass
class ExampleAPIData:
    """Class to hold api data."""

    controller_name: str
    devices: list[Device]


class ExampleCoordinator(DataUpdateCoordinator):
    """My example coordinator."""

    data: ExampleAPIData

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize coordinator."""
        # Set variables from values entered in config flow setup
        self.address = config_entry.data[CONF_ADDRESS]

        # set variables from options.  You need a default here in case options have not been set
        self.poll_interval = config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )

        self.battery_type = config_entry.options.get(
            CONF_BATTERY_TYPE, DEFAULT_BATTERY_TYPE
        )
        self.persistent_connection = config_entry.options.get(
            CONF_PERSISTENT_CONNECTION, DEFAULT_PERSISTENT_CONNECTION
        )

        # Initialise DataUpdateCoordinator
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({config_entry.unique_id})",
            # Method to call on every update interval.
            update_method=self.async_update_data,
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(seconds=self.poll_interval),
        )

        # Initialise your api here
        self.api = API(hass = hass, address = self.address, battery_type = self.battery_type, persistent_connection = self.persistent_connection)

    async def _async_setup(self):
        """ This method will be called automatically during
        coordinator.async_config_entry_first_refresh """
        # try:
        #     devices = await self.api.get_devices()

        # except Exception as err:
        #     # This will show entities as unavailable by raising UpdateFailed exception
        #     _LOGGER.error("in coordinatory/async_update_data - about to raise UpdateFailed")
        #     raise UpdateFailed(f"Error communicating with API: {err}") from err
        
        pass
    
    async def async_update_data(self):
        """Fetch data from API endpoint.
        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """

        # # Check to see if we need to change the update interval
        # temp_poll_interval = config_entry.options.get(
        #     CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        # )
        # if temp_poll_interval != self.update_interval:
        #     _LOGGER.error("in coordinator/async_update_data - changing update_interval to " + str(temp_poll_interval))
        #     self.update_interval = temp_poll_interval
        
        
        try:
            devices = None
            devices = await self.api.get_devices()
        # except APIAuthError as err:
        #     _LOGGER.error(err)
        #     raise UpdateFailed(err) from err
        except Exception as err:
            # This will show entities as unavailable by raising UpdateFailed exception
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        # What is returned here is stored in self.data by the DataUpdateCoordinator
        else:
            return ExampleAPIData(self.api.controller_name, devices)

    def get_device_by_type(
        self, device_type: DeviceType) -> Device | None:
        """Return device by device type."""
        # Called by the sensors to get their updated data from self.data
        if not self.data.devices is None:
            try:
                return [
                    device
                    for device in self.data.devices
                    if device.device_type == device_type
                ][0]
            except IndexError:
                return None
        else:
            return None
