"""Interfaces with the Integration 101 Template api sensors."""

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricPotential,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.sensor import SensorDeviceClass

from .const import (
    DOMAIN,
    Device,
    DeviceType
)

from .coordinator import ExampleCoordinator
from bluetooth_data_tools import human_readable_name

#_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up the Sensors."""
    # This gets the data update coordinator from hass.data as specified in your __init__.py
    coordinator: ExampleCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ].coordinator

    # Enumerate all the sensors in your data value from your DataUpdateCoordinator and add an instance of your sensor class
    # to a list for each one.
    sensors = [
        ExampleSensor(coordinator, device)
        for device in coordinator.data.devices
    ]

    # Create the sensors.
    async_add_entities(sensors, update_before_add = True)

class ExampleSensor(CoordinatorEntity, SensorEntity):
    """Implementation of a sensor."""

    def __init__(self, coordinator: ExampleCoordinator, device: Device) -> None:
        """Initialise sensor."""
        super().__init__(coordinator)
        self.device = device
        self.device_unique_id = device.device_unique_id


    @callback
    def _handle_coordinator_update(self) -> None:
        """Update sensor with latest data from coordinator."""
        # This method is called by your DataUpdateCoordinator when a successful update runs.
        self.device = self.coordinator.get_device_by_type(
            self.device.device_type)
            
        if not self.device is None:
            self.async_write_ha_state()

    @property
    def device_class(self) -> SensorDeviceClass | None:
        """Return device class."""
        # https://developers.home-assistant.io/docs/core/entity/sensor/#available-device-classes
        return self.device.device_class

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        # Identifiers are what group entities into the same device.
        # If your device is created elsewhere, you can just specify the indentifiers parameter.
        # If your device connects via another device, add via_device parameter with the indentifiers of that device.
        return DeviceInfo(
            name=f"{human_readable_name(None, "BM2 battery monitor", self.coordinator.address)}",
            manufacturer="Shenzhen Leagend Optoelectronics",
            model="BM2",
            model_id=self.coordinator.address,
            identifiers={
                (
                    DOMAIN,
                    self.coordinator.address,
                )
            },
        )

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return self.device.name

    @property
    def native_value(self) -> int | float | str:
        """Return the state of the entity."""
        # Using native value and native unit of measurement, allows you to change units
        # in Lovelace and HA will automatically calculate the correct value.
        return self.device.state

    @property
    def native_unit_of_measurement(self) -> UnitOfElectricPotential | None:
        """Return unit of temperature."""
        return self.device.device_unit

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        # All entities must have a unique id.  Think carefully what you want this to be as
        # changing it later will cause HA to create new entities.
        return self.device.device_unique_id

    @property
    def extra_state_attributes(self):
        """Return the extra state attributes."""
        # Add any additional attributes you want on your sensor.
        attrs = {}
        attrs["battery_type"] = self.coordinator.battery_type
        return attrs

    @property
    def icon(self) -> str:
        """Return icon, only for the status entity."""
        return self.device.device_icon

    @property
    def available(self) -> bool:
        """Return True if entity is available.

        The sensor is only created when the device is seen.

        Since these are sleepy devices which stop broadcasting
        when not in use, we can't rely on the last update time
        so once we have seen the device we always return True.
        """
        return True

    # @property
    # def assumed_state(self) -> bool:
    #     """Return True if the device is no longer broadcasting."""
    #     return not self.processor.available
