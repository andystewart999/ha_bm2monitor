"""Constants for the Integration 101 Template integration."""

from dataclasses import dataclass
from enum import StrEnum
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricPotential,
)

DOMAIN = "ha_bm2monitor"

CONF_BATTERY_TYPE = "battery_type"
DEFAULT_BATTERY_TYPE = "Automatic (via BM2)"
DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 30
CONNECTION_TIMEOUT = 45
GATT_TIMEOUT = 45

class DeviceType(StrEnum):
    """Sensor types."""
    VOLTAGE_SENSOR = "voltage_sensor"
    PERCENTAGE_SENSOR = "percentage_sensor"
    STATUS_SENSOR = "status_sensor"

@dataclass
class Device:
    """BM2 sensor"""
#    device_id: int
    device_unique_id: str
#    device_address: str
    device_type: DeviceType
    device_class: SensorDeviceClass | None
    device_unit: UnitOfElectricPotential | None
    device_icon: str | None
    name: str
    state: int | str

DEVICES = [
    {"type": DeviceType.VOLTAGE_SENSOR, "class": SensorDeviceClass.VOLTAGE, "unit": UnitOfElectricPotential.VOLT},
    {"type": DeviceType.PERCENTAGE_SENSOR, "class": SensorDeviceClass.BATTERY, "unit": PERCENTAGE},
    {"type": DeviceType.STATUS_SENSOR, "class": None, "unit": None},
]

BATTERY_TYPES = [
    "Automatic (via BM2)",
    "AGM",
    "Deep-cycle",
    "Lead-acid",
    "LiFePO4",
    "Lithium-ion"
]

BATTERY_STATUS = {
    1: "Low",
    2: "Normal",
    4: "Charging",
    8: "Critical"
}

BATTERY_STATUS_ICON = {
    "Low" : "mdi:battery-arrow-down-outline",
    "Normal" : "mdi:battery-check",
    "Charging" : "mdi:battery-charging-100",
    "Critical" : "mdi:battery-remove-outline"
}
