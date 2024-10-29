"""Support for BM2 BLE."""

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry

if TYPE_CHECKING:
    from .coordinator import BME2ActiveBluetoothProcessorCoordinator

type BME2BLEConfigEntry = ConfigEntry[BME2ActiveBluetoothProcessorCoordinator]
