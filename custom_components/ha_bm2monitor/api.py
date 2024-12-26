"""API Placeholder.

You should create your api seperately and have it hosted on PYPI.  This is included here for the sole purpose
of making this example code executable.
"""
from homeassistant.core import HomeAssistant
import logging
#from homeassistant.util import slugify
from bluetooth_data_tools import short_address
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricPotential,
)

from .const import (
    CONNECTION_TIMEOUT,
    GATT_TIMEOUT,
    DEVICES,
    BATTERY_STATUS,
    BATTERY_STATUS_ICON,
    Device,
    DeviceType
)

from bleak import BleakClient
from bleak.exc import BleakError
import binascii
from Crypto.Cipher import AES
import asyncio
import numpy as np
from contextlib import AsyncExitStack

import datetime
import time

_LOGGER = logging.getLogger(__name__)


class API:
    """Class for example API."""

    def __init__(self, hass: HomeAssistant, address: str, ble_device, battery_type: str) -> None:
        """Initialise."""
        self.address = address
        self.battery_type = battery_type
        self.hass = hass
        self.voltage = None
        self.percentage = None
        self.status = None
        self.status_adjusted = None
        self.status_raw = None
        self.gotdata = None

        """ Bluetooth stuff"""
        self._ble_device = ble_device
        self._client: BleakClient | None = None
        self._client_stack = AsyncExitStack()
        self._lock = asyncio.Lock()

    @property
    def controller_name(self) -> str:
        """Return the name of the controller."""
        return short_address(self.address)

    def adjust_percentage(self, raw_percentage: int) -> int:
        """ Use self.battery_type to determine if we need to adjust the percentage based on voltage
            BM2's default percentage and status values are extremely optimistic! """
            
        np_percent = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

        match self.battery_type:
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
                return int(raw_percentage)
        
        return int(np.interp(self.voltage, np_voltage, np_percent))

    def adjust_status(self, raw_status: int, adjusted_percentage: int) -> int:
        """ Use self.battery_type to determine if we need to adjust the status based on voltage
            BM2's default percentage and status values are extremely optimistic! """

        _LOGGER.error ("in api/adjust_status - battery_type = " + str(self.battery_type))
        if ( (self.battery_type == "Automatic (via BM2)")  or (raw_status == 4) ) :
            # Just return whatever the BM2 is telling us
            return raw_status

        match self.battery_type:
            case "AGM":
                low_percentage = 30
                critical_percentage = 20
                
            case "Deep-cycle":
                low_percentage = 50
                critical_percentage = 20
                
            case "Lead-acid":
                low_percentage = 60
                critical_percentage = 50
            
            case "LiFePO4":
                low_percentage = 20
                critical_percentage = 5
            
            case "Lithium-ion":
                low_percentage = 30
                critical_percentage = 20

            case _:
                low_percentage = 60
                critical_percentage = 50

        if adjusted_percentage <= critical_percentage:
            return 8    # Critical
        elif adjusted_percentage <= low_percentage:
            return 1    # Low
        else:
            return 2    # Normal

    async def get_devices(self) -> list[Device]:
        """ Connect to the BM2 device and retrieve the values """
        _LOGGER.error("in apy/async_get_devices - about to run threadsafe read_gatt, _gotdata = " + str(self.gotdata))
        await self.read_gatt()
        _LOGGER.error("in apy/async_get_devices - after threadsafe read_gatt, _gotdata = " + str(self.gotdata))

        # # Nasty
        # _LOGGER.error("in apy/get_devices - starting nasty tick check")
        # ticks = 0
        # while self._gotdata != True:
        #     time.sleep(1.0)
        #     ticks += 1
        #     if ticks > GATT_TIMEOUT:
        #         # We don't seem to have had any response
        #         raise APIGATTError("Timeout reading BM2 GATT")

        # _LOGGER.error("in apy/get_devices - finished nasty tick check")
        return [
            Device(
                # device_id=device.get("id"),
                device_unique_id=self.get_device_unique_id(device.get("type")),
                device_type=device.get("type"),
                device_class=device.get("class"),
                device_unit=device.get("unit"),
                name=self.get_device_name(device.get("type")),
                state=self.get_device_value(device.get("type")),
                device_icon=self.get_device_icon(device.get("type"), self.get_device_value(device.get("type")))
            )
            for device in DEVICES
        ]

    # def get_devices(self) -> list[Device]:
    #     """ Connect to the BM2 device and retrieve the values """
    #     _LOGGER.error("in apy/get_devices - about to run threadsafe read_gatt, _gotdata = " + str(self.gotdata))
    #     asyncio.run_coroutine_threadsafe(self.read_gatt(), self.hass.loop)
    #     _LOGGER.error("in apy/get_devices - after threadsafe read_gatt, _gotdata = " + str(self.gotdata))

    #     # # Nasty
    #     # _LOGGER.error("in apy/get_devices - starting nasty tick check")
    #     # ticks = 0
    #     # while self._gotdata != True:
    #     #     time.sleep(1.0)
    #     #     ticks += 1
    #     #     if ticks > GATT_TIMEOUT:
    #     #         # We don't seem to have had any response
    #     #         raise APIGATTError("Timeout reading BM2 GATT")

    #     # _LOGGER.error("in apy/get_devices - finished nasty tick check")
    #     return [
    #         Device(
    #             # device_id=device.get("id"),
    #             device_unique_id=self.get_device_unique_id(device.get("type")),
    #             device_type=device.get("type"),
    #             device_class=device.get("class"),
    #             device_unit=device.get("unit"),
    #             name=self.get_device_name(device.get("type")),
    #             state=self.get_device_value(device.get("type")),
    #             device_icon=self.get_device_icon(device.get("type"), self.get_device_value(device.get("type")))
    #         )
    #         for device in DEVICES
    #     ]


    def get_device_unique_id(self, device_type: DeviceType) -> str:
        """Return a unique device id."""
        if device_type == DeviceType.VOLTAGE_SENSOR:
            return f"bm2_({short_address(self.address)})_volts"
        if device_type == DeviceType.PERCENTAGE_SENSOR:
            return f"bm2_({short_address(self.address)})_percentage"
        if device_type == DeviceType.STATUS_SENSOR:
            return f"bm2_({short_address(self.address)})_status"

    def get_device_name(self, device_type: DeviceType) -> str:
        """Return the device name."""
        if device_type == DeviceType.VOLTAGE_SENSOR:
            return f"BM2 ({short_address(self.address)}) volts"
        if device_type == DeviceType.PERCENTAGE_SENSOR:
            return f"BM2 ({short_address(self.address)}) percentage"
        if device_type == DeviceType.STATUS_SENSOR:
            return f"BM2 ({short_address(self.address)}) status"

    def get_device_value(self, device_type: DeviceType) -> int | str | float:
        """Get device value.  It's already been written"""
        if device_type == DeviceType.VOLTAGE_SENSOR:
            _LOGGER.error ("In api/get_device_value - returning " + str(self.voltage) + " " + str(datetime.datetime.now().strftime("%H:%M:%S:%f")))
            return self.voltage
        if device_type == DeviceType.PERCENTAGE_SENSOR:
            return self.percentage
        if device_type == DeviceType.STATUS_SENSOR:
            return self.status

    def get_device_icon(self, device_type: DeviceType, state) -> str:
        """Get device icon, only for DeviceType.STATUS_SENSOR"""
        if device_type == DeviceType.STATUS_SENSOR:
            return BATTERY_STATUS_ICON.get(state, "mdi:battery-off")
        else:
            return None

    async def read_gatt(self) -> bool:
        await self.get_client()

        """ This is the BM2 UUID that we need to read """
        uuid_str = "{0000fff4-0000-1000-8000-00805f9b34fb}"
        self.gotdata = False
        ticks = 0

        """ We can't directly read a GATT, we have to register our interest in the UUID and get notified of the value
        But we're only interested in getting a single value so we'll de-register as soon as we get something """
        await self._client.start_notify(uuid_str, self.notification_handler)
        while self.gotdata != True:
            await asyncio.sleep(1.0)
            ticks += 1
            if ticks > GATT_TIMEOUT:
                # We don't seem to have had any response
                raise APIGATTError("Timeout reading BM2 GATT")

        await self._client.stop_notify(uuid_str)
        await self._client.disconnect()
        self._client = None

        return self.gotdata

    async def get_client(self):
        async with self._lock:
            if not self._client:
                try:
                    self._client = await self._client_stack.enter_async_context(BleakClient(self._ble_device, timeout=CONNECTION_TIMEOUT))
                except asyncio.TimeoutError as exc:
                    raise BleakError("Timeout on connect") from exc
                except BleakError as exc:
                    raise BleakError("Error on connect") from exc
            else:
                pass

    def notification_handler(self, sender, data):
        """Simple bluetooth notification handler"""

        """ We need to decrypt the response """
        key = bytearray([(b&255) for b in [108,101,97,103,101,110,100,-1,-2,49,56,56,50,52,54,54]])
        cipher = AES.new(key, AES.MODE_CBC, 16 * b'\0')
        ble_msg = cipher.decrypt(data)
        raw = binascii.hexlify(ble_msg).decode()

        self.voltage = int(raw[2:5],16) / 100.0
        self.percentage = self.adjust_percentage(int(raw[6:8],16))
        self.status = BATTERY_STATUS.get(self.adjust_status(int(raw[5:6],16), self.percentage), "Unknown")
        self.status_adjusted = self.adjust_status(int(raw[5:6],16), self.percentage)
        self.status_raw = int(raw[5:6],16)
        self.gotdata = True
        _LOGGER.error("in api/notification_handler: .status_raw = " + str(self.status_raw) + ", .status_adjusted = " + str(self.status_adjusted))
        
    def update_from_advertisement(self, advertisement):
        """ We aren't listening for advertisements/broadcasts, we're doing direct connections """
        pass


class APIAuthError(Exception):
    """Exception class for auth error."""

class APIConnectionError(Exception):
    """Exception class for generic connection error."""

class APIGATTError(Exception):
    """Exception class for GATT connection error."""
