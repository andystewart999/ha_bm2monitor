"""Parser for BMx BLE advertisements.

This file is shamelessly copied from the following repository:
https://github.com/Ernst79/bleparser/blob/c42ae922e1abed2720c7fac993777e1bd59c0c93/package/bleparser/oral_b.py

MIT License applies.
"""

from __future__ import annotations


from sensor_state_data import (
    BinarySensorDeviceClass,
    BinarySensorValue,
    DeviceKey,
    SensorDescription,
    SensorDeviceClass,
    SensorDeviceInfo,
    SensorUpdate,
    SensorValue,
    Units,
)

from .const import (
    CONF_SCAN_MODE,
    DEFAULT_SCAN_MODE,
    DEFAULT_SCAN_INTERVAL,
    CONF_BATTERY_TYPE,
    DEFAULT_BATTERY_TYPE,
    BATTERY_STATUS_LIST,
    BATTERY_STATUS_ICON,
    GATT_TIMEOUT
)

import logging
import time
from dataclasses import dataclass
from enum import Enum, auto

from bleak import BleakError, BLEDevice
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
    retry_bluetooth_connection_error,
)
from bluetooth_data_tools import short_address
from bluetooth_sensor_state_data import BluetoothData
from home_assistant_bluetooth import BluetoothServiceInfo
from sensor_state_data import SensorDeviceClass, SensorUpdate, Units
from sensor_state_data.enum import StrEnum
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricPotential,
    CONF_SCAN_INTERVAL
)

# For the decryption of the returned characteristic payload
import asyncio
import binascii
from Crypto.Cipher import AES

# For percentage interpolation
import numpy as np

_LOGGER = logging.getLogger(__name__)

class BMxSensor(StrEnum):
    BATTERY_PERCENT = "battery_percent"
    BATTERY_STATUS = "battery_status"
    BATTERY_VOLTAGE = "battery_voltage"
    SIGNAL_STRENGTH = "signal_strength"


@dataclass
class ModelDescription:
    device_type: str
    identifier: str | byte | None
    characteristic: str

BMx_MANUFACTURER = 0x004C

class Models(Enum):
    BM2 = auto()
    BM6 = auto() # Placeholder - not yet supported

# Placeholder for future support of BM6...
BYTES_TO_MODEL = {
    b'\x03"': Models.BM2,
    b'\x04"': Models.BM6,
}

DEVICE_TYPES = {
    Models.BM2: ModelDescription(
        device_type="BM2 battery monitor",
        identifier = 0x004C,  #TBD if this is going to work
        characteristic = "{0000fff4-0000-1000-8000-00805f9b34fb}"

    ),
    Models.BM6: ModelDescription(
        device_type="BM6 battery monitor",
        identifier = "TBD",
        characteristic = "{TBD}"
    )
}

class BMxBluetoothDeviceData(BluetoothData):
    """Data for BMx BLE sensors."""

    def __init__(self) -> None:
        super().__init__()

        # If this is True we are currently charging
        self._charging = None
        
        # Somewhere to temporarily store GATT data, and capture that we're waiting for data
        self._gattdata = None
        self._ignore_advertisement = False
        
        # Somewhere to store model info for later use
        self._model_info = None
    

    def _start_update(self, service_info: BluetoothServiceInfo) -> None:
        """ Update from BLE advertisement data, and active connection data
            We actually don't really need to parse the advertisement data itsekf, 
            as the characteristic data we're about to get is a superset of it """

        _LOGGER.debug("New advertisement - %s", str(service_info))
        manufacturer_data = service_info.manufacturer_data
        address = service_info.address
        
        if BMx_MANUFACTURER not in manufacturer_data:   # This is the manufacturer_data key where the current battery percentage is stored (in the last array item), although as stated above we don't really need this data.  It's a useful check though
            return None

        data = manufacturer_data[BMx_MANUFACTURER]
        self.set_device_manufacturer("Shenzhen Leagend Optoelectronics")

        model = Models.BM2   # Placeholder - logic required to distinguish between the BM2 and the BM6
        #model = BYTES_TO_MODEL.get(5, Models.BM2)   # Placeholder - logic required to distinguish between the BM2 and the BM6
        model_info = DEVICE_TYPES[model]
        self._model_info = model_info
        self.set_device_type(model_info.device_type)
        name = f"{model_info.device_type} ({short_address(address)})"
        self.set_device_name(name)
        self.set_title(name)

    def poll_needed(
        self, service_info: BluetoothServiceInfo, last_poll: float | None
    ) -> bool:
        """
        This is called every time we get a service_info for a device. It means the
        device is working and online.
        """

        if self._ignore_advertisement == True:
            return False

        if last_poll is None:
            return True

        scan_mode = self._options.get(CONF_SCAN_MODE, DEFAULT_SCAN_MODE)

        if scan_mode == "Never rate limit sensor updates":
            _LOGGER.debug("Sensor updates not rate-limited, returning poll_needed == True")
            return True
        elif scan_mode == "Only rate limit when not charging" and self._charging == True:
            _LOGGER.debug("Sensor updates not rate-limited during charging, returning poll_needed == True")
            return True
    
        update_interval = self._options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        pollneeded = last_poll > update_interval
        _LOGGER.debug("Sensor updates rate-limited, returning poll_needed == %s", str(pollneeded))

        return pollneeded

    @retry_bluetooth_connection_error()
    async def _get_payload(self, client: BleakClientWithServiceCache) -> None:
        """Get the payload from BM2 using its gatt_characteristic."""

        ticks = 0
        self._gattdata = None
        
        # While we're waiting for the data to come through, we should stop handling advertisements, as sometimes it takes a few seconds
        self._ignoreadvertisement = True

        await client.start_notify(self._model_info.characteristic, self.notification_handler)
        while (self._gattdata is None) and (ticks < GATT_TIMEOUT * 4):
            await asyncio.sleep(0.25)
            ticks += 1

        await client.stop_notify(self._model_info.characteristic)
        self._ignore_advertisement = False

        if self._gattdata is not None:
            _LOGGER.debug("Successfully read characteristic %s", self._model_info.characteristic)

            """ We need to decrypt the response """
            key = bytearray([(b&255) for b in [108,101,97,103,101,110,100,-1,-2,49,56,56,50,52,54,54]])
            cipher = AES.new(key, AES.MODE_CBC, 16 * b'\0')
            ble_msg = cipher.decrypt(self._gattdata)
            raw = binascii.hexlify(ble_msg).decode()
    
            voltage = int(raw[2:5],16) / 100.0
            percentage = int(raw[6:8],16)
            status = int(raw[5:6],16)
            _LOGGER.debug("Raw characteristic data: voltage = %s, percentage = %s, status = %s", str(voltage), str(percentage), str(status))

            # Carry out any adjustments as defined by the battery type
            percentage = self._adjust_percentage(percentage, self._options.get(CONF_BATTERY_TYPE, DEFAULT_BATTERY_TYPE), voltage)
            status = self._adjust_status(status, self._options.get(CONF_BATTERY_TYPE, DEFAULT_BATTERY_TYPE), percentage, voltage)
            _LOGGER.debug("Adjusted characteristic data: percentage = %s, status = %s", str(percentage), str(status))
            
            # Convert status into something human_readable
            status_text = BATTERY_STATUS_LIST.get(status, "Unknown")
            
            self.update_sensor(
                key = str(BMxSensor.BATTERY_PERCENT),
                native_unit_of_measurement = PERCENTAGE,
                native_value = percentage,
                device_class = SensorDeviceClass.BATTERY
            )
    
            self.update_sensor(
                key = str(BMxSensor.BATTERY_VOLTAGE),
                native_unit_of_measurement = UnitOfElectricPotential,
                native_value = voltage,
                device_class = SensorDeviceClass.VOLTAGE
            )
    
            self.update_sensor(
                key = str(BMxSensor.BATTERY_STATUS),
                native_unit_of_measurement = None,
                native_value = status_text,
                device_class = None,
                #name = "Status"
            )

            # Update internal charging flag
            if status == 4:
                self._charging = True
            else:
                self._charging = False
            
    def notification_handler(self, sender, data):
        """Simple bluetooth notification handler"""
        self._gattdata = data

    async def async_poll(self, ble_device: BLEDevice) -> SensorUpdate:
        """
        Poll the device to retrieve percentage, status and voltage
        """
        _LOGGER.debug("Connecting to BM2 device: %s", ble_device.address)
        client = await establish_connection(
            BleakClientWithServiceCache, ble_device, ble_device.address
        )

        try:
            await self._get_payload(client)
        except BleakError as err:
            _LOGGER.warning(f"Reading gatt characters failed with err: {err}")
        finally:
            await client.disconnect()
            _LOGGER.debug("Disconnected from active bluetooth client")
        return self._finish_update()

    def _adjust_percentage(self, raw_percentage: int, battery_type: str, voltage: float) -> int:
        """ Use battery_type to determine if we need to adjust the percentage based on voltage
            BM2's default percentage and status values are extremely optimistic! """
            
        np_percent = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

        match battery_type:
            case "Automatic (via BM2)":
                return raw_percentage
                
            case "AGM":
                np_voltage = [10.5, 11.51, 11.66, 11.81, 11.95, 12.05, 12.15, 12.3, 12.5, 12.75, 12.8, 12.85]
                
            case "Deep-cycle":
                np_voltage = [10.5, 11.51, 11.66, 11.81, 11.95, 12.05, 12.15, 12.3, 12.5, 12.75, 12.8]
                
            case "Lead-acid":
                np_voltage = [10.5, 11.31, 11.58, 11.75, 11.9, 12.06, 12.2, 12.32, 12.42, 12.5, 12.7]
            
            case "LiFePO4":
                np_percent = [0, 9, 14, 17, 20, 30, 40, 70, 90, 99, 100]
                np_voltage = [10.0, 12.0, 12.5, 12.8, 12.9, 13.0, 13.1, 13.2, 13.3, 13.4, 13.6]
            
            case "Lithium-ion":
                np_voltage = [10.0, 12.0, 12.8, 12.9, 13.0, 13.05, 13.1, 13.2, 13.3, 13.4, 13.6]
                
            case _:
                return raw_percentage
        
        _LOGGER.debug ("Adjusting percentage based on battery chemistry of %s: current voltage = %s, default percentage = %s", battery_type, str(voltage), str(raw_percentage))
        return int(np.interp(voltage, np_voltage, np_percent))

    def _adjust_status(self, raw_status: int, battery_type: str, percentage: int, voltage: float) -> int:
        """ Use self.battery_type to determine if we need to adjust the status based on voltage
            BM2's default percentage and status values are extremely optimistic! """

        if battery_type == "Automatic (via BM2)": # or raw_status == 4:  # Charging
            # Just return whatever the BM2 is telling us
            return raw_status

        match battery_type:
            case "AGM":
                low_percentage = 30
                critical_percentage = 20
                float_voltage = 13.6
                charging_voltage = 14.3
                
            case "Deep-cycle":
                low_percentage = 50
                critical_percentage = 20
                float_voltage = 13.6
                charging_voltage = 14.4
                
            case "Lead-acid":
                low_percentage = 60
                critical_percentage = 50
                float_voltage = 13.7
                charging_voltage = 14.5
            
            case "LiFePO4":
                low_percentage = 20
                critical_percentage = 5
                float_voltage = 13.5
                charging_voltage = 14.4
            
            case "Lithium-ion":
                low_percentage = 30
                critical_percentage = 20
                float_voltage = 13.5
                charging_voltage = 14.25

            case _:
                low_percentage = 60
                critical_percentage = 50
                float_voltage = 13.6
                charging_voltage = 13.9

        _LOGGER.debug ("Adjusting state based on battery chemistry of %s: low percentage = %s, critical percentage = %s, charging voltage = %s, current voltage = %s", battery_type, str(low_percentage), str(critical_percentage), str(charging_voltage), str(voltage))
        if voltage >= charging_voltage:
            return 8    # Charging
        elif voltage >= float_voltage:
            return 4    # Floating
        elif percentage <= critical_percentage:
            return 0    # Critical
        elif percentage <= low_percentage:
            return 1    # Low
        else:
            return 2    # Normal

