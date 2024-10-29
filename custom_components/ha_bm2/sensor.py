"""Support for BM2 BLE sensor."""

from __future__ import annotations

from typing import cast

from xiaomi_ble import DeviceClass, SensorUpdate, Units
from xiaomi_ble.parser import ExtendedSensorDeviceClass

from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataUpdate,
    PassiveBluetoothProcessorEntity,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONCENTRATION_MILLIGRAMS_PER_CUBIC_METER,
    LIGHT_LUX,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfConductivity,
    UnitOfElectricPotential,
    UnitOfMass,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.sensor import sensor_device_info_to_hass_device_info

from .coordinator import XiaomiPassiveBluetoothDataProcessor
from .device import device_key_to_bluetooth_entity_key
from .types import XiaomiBLEConfigEntry

SENSOR_DESCRIPTIONS = {
    (DeviceClass.BATTERY, Units.PERCENTAGE): SensorEntityDescription(
        key=f"{DeviceClass.BATTERY}_{Units.PERCENTAGE}",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    )
}

def sensor_update_to_bluetooth_data_update(
    sensor_update: SensorUpdate,
) -> PassiveBluetoothDataUpdate[float | None]:
    """Convert a sensor update to a bluetooth data update."""
    return PassiveBluetoothDataUpdate(
        devices={
            device_id: sensor_device_info_to_hass_device_info(device_info)
            for device_id, device_info in sensor_update.devices.items()
        },
        entity_descriptions={
            device_key_to_bluetooth_entity_key(device_key): SENSOR_DESCRIPTIONS[
                (description.device_class, description.native_unit_of_measurement)
            ]
            for device_key, description in sensor_update.entity_descriptions.items()
            if description.device_class
        },
        entity_data={
            device_key_to_bluetooth_entity_key(device_key): cast(
                float | None, sensor_values.native_value
            )
            for device_key, sensor_values in sensor_update.entity_values.items()
        },
        entity_names={
            device_key_to_bluetooth_entity_key(device_key): sensor_values.name
            for device_key, sensor_values in sensor_update.entity_values.items()
        },
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XiaomiBLEConfigEntry, ### Follow this
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the BM2 BLE sensor."""
    coordinator = entry.runtime_data
    processor = XiaomiPassiveBluetoothDataProcessor(  ### Follow this
        sensor_update_to_bluetooth_data_update
    )
    entry.async_on_unload(
        processor.async_add_entities_listener(
            XiaomiBluetoothSensorEntity, async_add_entities  ### Follow this
        )
    )
    entry.async_on_unload(
        coordinator.async_register_processor(processor, SensorEntityDescription)
    )


class BM2BluetoothSensorEntity(
    PassiveBluetoothProcessorEntity[XiaomiPassiveBluetoothDataProcessor[float | None]],
    SensorEntity,
):
    """Representation of a BM2 ble sensor."""

    @property
    def native_value(self) -> int | float | None:
        """Return the native value."""
        return self.processor.entity_data.get(self.entity_key)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.processor.coordinator.sleepy_device or super().available
