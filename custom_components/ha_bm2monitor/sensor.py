"""Support for BMx battery monitor sensors."""

from __future__ import annotations

from .bmx_ble import BMxSensor, SensorUpdate

from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataProcessor,
    PassiveBluetoothDataUpdate,
    PassiveBluetoothProcessorEntity,
    PassiveBluetoothEntityKey
)

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfTime,
    UnitOfElectricPotential
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.sensor import sensor_device_info_to_hass_device_info

from . import BMxConfigEntry
from .device import device_key_to_bluetooth_entity_key
from .const import BATTERY_STATUS_ICON

import logging
_LOGGER = logging.getLogger(__name__)

SENSOR_DESCRIPTIONS: dict[str, SensorEntityDescription] = {
    BMxSensor.BATTERY_VOLTAGE: SensorEntityDescription(
        key=BMxSensor.BATTERY_VOLTAGE,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        name="Voltage",
        icon="mdi:current-dc"
    ),
    BMxSensor.BATTERY_STATUS: SensorEntityDescription(
        key=BMxSensor.BATTERY_STATUS,
        translation_key="status",
        name="Status"
    ),
    BMxSensor.BATTERY_PERCENT: SensorEntityDescription(
        key=BMxSensor.BATTERY_PERCENT,
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        name="Percent"
    ),
    BMxSensor.SIGNAL_STRENGTH: SensorEntityDescription(
        key=BMxSensor.SIGNAL_STRENGTH,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        name="Signal strength"
    ),
}


def sensor_update_to_bluetooth_data_update(
    sensor_update: SensorUpdate,
    ) -> PassiveBluetoothDataUpdate:

    """Convert a sensor update to a bluetooth data update."""
    return PassiveBluetoothDataUpdate(
        devices={
            device_id: sensor_device_info_to_hass_device_info(device_info)
            for device_id, device_info in sensor_update.devices.items()
        },
        entity_descriptions={
            device_key_to_bluetooth_entity_key(device_key): SENSOR_DESCRIPTIONS[
                device_key.key
            ]
            for device_key in sensor_update.entity_descriptions
        },
        entity_data={
            device_key_to_bluetooth_entity_key(device_key): sensor_values.native_value
            for device_key, sensor_values in sensor_update.entity_values.items()
        },
        entity_names={},
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BMxConfigEntry,
    async_add_entities: AddEntitiesCallback,
    ) -> None:

    """Set up the BMx BLE sensors."""
    coordinator = entry.runtime_data
    processor = PassiveBluetoothDataProcessor(sensor_update_to_bluetooth_data_update)
    entry.async_on_unload(
        processor.async_add_entities_listener(
            BMxBluetoothSensorEntity, async_add_entities
        )
    )
    entry.async_on_unload(
        coordinator.async_register_processor(processor, SensorEntityDescription)
    )


class BMxBluetoothSensorEntity(
    PassiveBluetoothProcessorEntity[
        PassiveBluetoothDataProcessor[str | int | None, SensorUpdate]
    ],
    SensorEntity,
    ):
    """Representation of a BMX BLE sensor."""

    @property
    def native_value(self) -> str | int | None:
        """Return the native value."""
        return self.processor.entity_data.get(self.entity_key)

    @property
    def available(self) -> bool:
        return True

    @property
    def assumed_state(self) -> bool:
        """Return True if the device is no longer broadcasting."""
        return not self.processor.available

#   @property
#     def extra_state_attributes(self):
#         """Return the extra state attributes."""
#         attrs = {}
#         attrs["battery_type"] = self.coordinator.battery_type
#         return attrs

    @property
    def icon(self) -> str:

        """Return icon only for the status and volts entities."""
        if self.entity_key.key == "battery_status":
            return BATTERY_STATUS_ICON.get(self.processor.entity_data.get(self.entity_key), "mdi:battery-off")
        elif self.entity_key.key == "battery_voltage":
            return "mdi:current-dc"
