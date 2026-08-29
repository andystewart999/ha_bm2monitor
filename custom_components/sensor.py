"""Support for BMx battery monitor sensors."""

from __future__ import annotations

import logging

from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataProcessor,
    PassiveBluetoothDataUpdate,
    PassiveBluetoothEntityKey,
    PassiveBluetoothProcessorEntity,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfElectricPotential,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.sensor import sensor_device_info_to_hass_device_info

from . import BMxConfigEntry
from .bmx_ble import BMxSensor, SensorUpdate
from .const import BATTERY_STATUS_ICON
from .device import device_key_to_bluetooth_entity_key

_LOGGER = logging.getLogger(__name__)

SENSOR_DESCRIPTIONS: dict[str, SensorEntityDescription] = {
    BMxSensor.BATTERY_VOLTAGE: SensorEntityDescription(
        key=BMxSensor.BATTERY_VOLTAGE,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=2,
        name="Voltage",
        icon="mdi:current-dc",
    ),
    BMxSensor.BATTERY_STATUS: SensorEntityDescription(
        key=BMxSensor.BATTERY_STATUS,
        translation_key="status",
        name="Status",
    ),
    BMxSensor.BATTERY_PERCENT: SensorEntityDescription(
        key=BMxSensor.BATTERY_PERCENT,
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        name="Percent",
    ),
    BMxSensor.SIGNAL_STRENGTH: SensorEntityDescription(
        key=BMxSensor.SIGNAL_STRENGTH,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        name="Signal strength",
    ),

    # ADVERTISEMENT FALLBACK:
    # This is an inferred protocol era, not an exact firmware revision.
    BMxSensor.BM2_GENERATION: SensorEntityDescription(
        key=BMxSensor.BM2_GENERATION,
        name="BM2 generation",
        icon="mdi:timeline-clock-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
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
    _LOGGER.debug("Setting up sensors")
    coordinator = entry.runtime_data
    processor = PassiveBluetoothDataProcessor(sensor_update_to_bluetooth_data_update)

    entry.async_on_unload(
        processor.async_add_entities_listener(
            BMxBluetoothSensorEntity,
            async_add_entities,
        )
    )
    entry.async_on_unload(
        coordinator.async_register_processor(
            processor,
            SensorEntityDescription,
        )
    )


class BMxBluetoothSensorEntity(
    PassiveBluetoothProcessorEntity[
        PassiveBluetoothDataProcessor[str | int | None, SensorUpdate]
    ],
    SensorEntity,
):
    """Representation of a BMx BLE sensor."""

    @property
    def native_value(self) -> str | int | None:
        """Return the native value."""
        return self.processor.entity_data.get(self.entity_key)

    @property
    def available(self) -> bool:
        """Return whether the processor is available."""
        return self.processor.available

    @property
    def assumed_state(self) -> bool:
        """Return True if the device is no longer broadcasting."""
        return not self.processor.available

    @property
    def icon(self) -> str | None:
        """Return dynamic icons for selected entities."""
        if self.entity_key.key == BMxSensor.BATTERY_STATUS:
            return BATTERY_STATUS_ICON.get(
                self.processor.entity_data.get(self.entity_key),
                "mdi:battery-off",
            )

        if self.entity_key.key == BMxSensor.BATTERY_VOLTAGE:
            return "mdi:current-dc"

        return self.entity_description.icon