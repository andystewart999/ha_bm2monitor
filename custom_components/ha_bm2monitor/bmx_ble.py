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
    GATT_TIMEOUT,
    CONF_CUSTOM_BATTERY_CHEMISTRY,
    DEFAULT_CUSTOM_BATTERY_CHEMISTRY,
    CONF_CUSTOM_CRITICAL_VOLTAGE,
    DEFAULT_CUSTOM_CRITICAL_VOLTAGE,
    CONF_CUSTOM_LOW_VOLTAGE,
    DEFAULT_CUSTOM_LOW_VOLTAGE,
    CONF_CUSTOM_FIFTY_PERCENT_VOLTAGE,
    DEFAULT_CUSTOM_FIFTY_PERCENT_VOLTAGE,
    CONF_CUSTOM_HUNDRED_PERCENT_VOLTAGE,
    DEFAULT_CUSTOM_HUNDRED_PERCENT_VOLTAGE,
    CONF_CUSTOM_FLOATING_VOLTAGE,
    DEFAULT_CUSTOM_FLOATING_VOLTAGE,
    CONF_CUSTOM_CHARGING_VOLTAGE,
    DEFAULT_CUSTOM_CHARGING_VOLTAGE,
    CONF_CUSTOM_NUMPY_VOLTS,
    DEFAULT_CUSTOM_NUMPY_VOLTS,
    CONF_CUSTOM_NUMPY_PERCENT,
    DEFAULT_CUSTOM_NUMPY_PERCENT
)




import logging
import time
from dataclasses import dataclass
from enum import Enum, auto
#from enum import StrEnum

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
#BYTES_TO_MODEL = {
#    b'\x03"': Models.BM2,
#    b'\x04"': Models.BM6,
#}

DEVICE_TYPES = {
    Models.BM2: ModelDescription(
        device_type="BM2 battery monitor",
        identifier = BMx_MANUFACTURER,  #TBD if this is going to work
        characteristic = "{0000fff4-0000-1000-8000-00805f9b34fb}"
    ),
    Models.BM6: ModelDescription(
        device_type="BM6 battery monitor",
        identifier = "TBD",
        characteristic = "{TBD}"
    )
}


class Battery(StrEnum):
    agm = "agm"
    deepcycle = "deepcycle"
    leadacid = "leadacid"
    lifepo4 = "lifepo4"
    lithiumion = "lithiumion"
    itech120x = "itech120x"
    custom = "custom"

@dataclass
class BatteryDetail:
    battery_chemistry: str
    volts_to_percent: list
    critical_voltage: int
    low_voltage: int
    floating_voltage: float
    charging_voltage: float

BATTERIES = {
    Battery.agm:        BatteryDetail("AGM", [10.5, 11.51, 11.66, 11.81, 11.95, 12.05, 12.15, 12.3, 12.5, 12.75, 12.8, 12.85], 11.66, 11.81, 13.6, 14.3),
    Battery.deepcycle:  BatteryDetail("Deep-cycle", [10.5, 11.51, 11.66, 11.81, 11.95, 12.05, 12.15, 12.3, 12.5, 12.75, 12.8], 11.66, 12.05, 13.6, 14.4),
    Battery.leadacid:   BatteryDetail("Lead-acid", [10.5, 11.31, 11.58, 11.75, 11.9, 12.06, 12.2, 12.32, 12.42, 12.5, 12.7], 12.06, 12.2, 13.7, 14.5),
    Battery.lifepo4:    BatteryDetail("LiFePO4", [10.0, 12.0, 12.5, 12.8, 12.9, 13.0, 13.1, 13.2, 13.3, 13.4, 13.6], 10.5, 12.0, 13.5, 14.4),
    Battery.lithiumion: BatteryDetail("Lithium-ion", [10.0, 12.0, 12.8, 12.9, 13.0, 13.05, 13.1, 13.2, 13.3, 13.4, 13.6], 10.5, 12.0, 13.5, 14.25),
    Battery.itech120x:  BatteryDetail("iTechworld 120X (LiFePO4)", [9.5, 10.5, 12.5, 12.7, 12.8, 12.89, 12.91, 12.99, 13.01, 13.1, 13.5], 10.5, 12.5, 13.5, 14.35),
    Battery.custom:     BatteryDetail("Custom", [10.5, 11.58, 12.06, 13.6], 12.06, 12.2, 13.7, 14.5)
}

# Can we do this with a one-liner 'any' call, and is that more efficient?  Probably!  #TODO
CHEMISTRY_OPTION_TO_BATTERY = {
    "AGM": Battery.agm,
    "Deep-cycle": Battery.deepcycle,
    "Lead-acid": Battery.leadacid,
    "LifePO4": Battery.lifepo4,
    "Lithium-ion": Battery.lithiumion,
    "itech120x": Battery.itech120x,
    "Custom": Battery.custom
}


class BMxBluetoothDeviceData(BluetoothData):
    """Data for BMx BLE sensors."""

    def __init__(self) -> None:
        super().__init__()

        # If this is True we are currently charging
        self._charging = False
        
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

        _LOGGER.debug("Inside 'poll_needed', _ignore_advertisement = %s, _charging = %s, _model_info = %s", str(self._ignore_advertisement), str(self._charging), str(self._model_info))

        if self._ignore_advertisement == True:
            return False

        if last_poll is None:
            return True

        scan_mode = self._options.get(CONF_SCAN_MODE, DEFAULT_SCAN_MODE)
        _LOGGER.debug("Inside 'poll_needed', scan_mode = %s", scan_mode)

        if scan_mode == "Never rate limit sensor updates":
            _LOGGER.debug("Sensor updates not rate-limited, returning poll_needed == True")
            return True
        elif scan_mode == "Only rate limit when not charging" and self._charging == True:
            _LOGGER.debug("Sensor updates not rate-limited during charging, returning poll_needed == True")
            return True
    
        update_interval = self._options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        _LOGGER.debug("Inside 'poll_needed', update_interval = %s", str(update_interval))

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

            """ Carry out any adjustments as defined by the battery type
                In keeping with the oralb-ble implementation, at each poll we're doing a battery type lookup
                Seems a bit inefficient, in the future I'll probably change this to only capture it once at
                startup, and if the options change """

            battery_option = self._options.get(CONF_BATTERY_TYPE, DEFAULT_BATTERY_TYPE)
            
            if battery_option != "Automatic (via BM2)":
                # We only need to make potential adjustments to status and percentage if a specific battery chemistry has been selected
                if battery_option != "Custom":
                    battery_chemistry = CHEMISTRY_OPTION_TO_BATTERY[battery_option]
                    battery_detail = BATTERIES[battery_chemistry]
                    custom = False
                else:
                    battery_detail = BATTERIES["custom"]
                    battery_detail.battery_chemistry = self._options.get(CONF_CUSTOM_BATTERY_CHEMISTRY, DEFAULT_CUSTOM_BATTERY_CHEMISTRY)
                    battery_detail.volts_to_percent = self._options.get(CONF_CUSTOM_NUMPY_VOLTS, DEFAULT_CUSTOM_NUMPY_VOLTS)
                    battery_detail.critical_voltage = self._options.get(CONF_CUSTOM_CRITICAL_VOLTAGE, DEFAULT_CUSTOM_CRITICAL_VOLTAGE)
                    battery_detail.low_voltage = self._options.get(CONF_CUSTOM_LOW_VOLTAGE, DEFAULT_CUSTOM_LOW_VOLTAGE)
                    battery_detail.floating_voltage = self._options.get(CONF_CUSTOM_FLOATING_VOLTAGE, DEFAULT_CUSTOM_FLOATING_VOLTAGE)
                    battery_detail.charging_voltage = self._options.get(CONF_CUSTOM_CHARGING_VOLTAGE, DEFAULT_CUSTOM_CHARGING_VOLTAGE)
                    custom = True

                percentage = self._adjust_percentage(percentage, battery_detail, voltage, custom)
                status = self._adjust_status(status, battery_detail, voltage)

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
            if status >= 4: #charging or floating, ie attached to a powered-on charger
                self._charging = True
                _LOGGER.debug("Setting self._charging = %s", str(self._charging))
            else:
                self._charging = False
                _LOGGER.debug("Setting self._charging = %s", str(self._charging))
            
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

    def _adjust_percentage(self, raw_percentage: int, battery_detail, voltage: float, custom: bool = False) -> int:
        """ Use battery_detail to determine if we need to adjust the percentage based on voltage
            BM2's default percentage and status values are extremely optimistic! """

        # Using numpy for voltage/percentage calculation interpolation
        if not custom:
            np_percent = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        else:
            np_percent = [0, 20, 50, 100]

        np_voltage = battery_detail.volts_to_percent
        new_percentage = int(np.interp(voltage, np_voltage, np_percent))
        _LOGGER.debug ("Adjusting percentage based on battery chemistry of %s: actual voltage = %s, raw percentage = %s, updated percentage = %s", battery_detail.battery_chemistry, str(voltage), str(raw_percentage), str(new_percentage))

        return new_percentage

    def _adjust_status(self, raw_status: int, battery_detail, voltage: float) -> int:
        """ Use battery_detail to determine if we need to adjust the status based on voltage
            BM2's default percentage and status values are extremely optimistic!
            Obviously I'd prefer to use 4 for floating and 8 for charging, but the
            BM2 doesn't distinguish between the two """

        if voltage >= battery_detail.charging_voltage:
            new_status =  4    # Charging
        elif voltage >= battery_detail.floating_voltage:
            new_status =  8    # Floating
        elif voltage <= battery_detail.critical_voltage:
            new_status =  0    # Critical
        elif voltage <= battery_detail.low_voltage:
            new_status =  1    # Low
        else:
            new_status =  2    # Normal
        
        _LOGGER.debug ("Adjusting state based on battery chemistry of %s: critical voltage = %s, low voltage = %s, float voltage = %s, charging voltage = %s, actual voltage = %s, raw state = %s, updated state = %s", battery_detail.battery_chemistry, str(battery_detail.critical_voltage), str(battery_detail.low_voltage), str(battery_detail.floating_voltage), str(battery_detail.charging_voltage), str(voltage), str(raw_status), str(new_status))
        
        return new_status
