"""Parser and active BLE reader for BMx battery monitors.

The integration continues to prefer an active GATT read.  On BM2 firmware that
broadcasts the newer encrypted 16-byte telemetry packet, the latest
advertisement is decoded and cached so that it can be used if the active read
fails.

Changes for advertisement fallback are marked with:
    # ADVERTISEMENT FALLBACK:
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum, auto

import numpy as np
from bleak import BLEDevice
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
    retry_bluetooth_connection_error,
)
from bluetooth_data_tools import short_address
from bluetooth_sensor_state_data import BluetoothData
from Crypto.Cipher import AES
from home_assistant_bluetooth import BluetoothServiceInfo
from homeassistant.const import (
    CONF_SCAN_INTERVAL,
    PERCENTAGE,
    UnitOfElectricPotential,
)
from sensor_state_data import DeviceKey, SensorDeviceClass, SensorUpdate
from sensor_state_data.enum import StrEnum

from .const import (
    BATTERY_STATUS_LIST,
    CONF_BATTERY_TYPE,
    CONF_CUSTOM_BATTERY_CHEMISTRY,
    CONF_CUSTOM_CHARGING_VOLTAGE,
    CONF_CUSTOM_CRITICAL_VOLTAGE,
    CONF_CUSTOM_FLOATING_VOLTAGE,
    CONF_CUSTOM_LOW_VOLTAGE,
    CONF_CUSTOM_NUMPY_VOLTS,
    CONF_SCAN_MODE,
    DEFAULT_BATTERY_TYPE,
    DEFAULT_CUSTOM_BATTERY_CHEMISTRY,
    DEFAULT_CUSTOM_CHARGING_VOLTAGE,
    DEFAULT_CUSTOM_CRITICAL_VOLTAGE,
    DEFAULT_CUSTOM_FLOATING_VOLTAGE,
    DEFAULT_CUSTOM_LOW_VOLTAGE,
    DEFAULT_CUSTOM_NUMPY_VOLTS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCAN_MODE,
    GATT_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


# ADVERTISEMENT FALLBACK:
# The BM2 GATT notification and the newer encrypted manufacturer advertisement
# use the same AES-128-CBC key and a zero IV.
BM2_AES_KEY = bytes(
    [108, 101, 97, 103, 101, 110, 100, 255, 254, 49, 56, 56, 50, 52, 54, 54]
)
BM2_AES_IV = bytes(16)

# The useful manufacturer-data BODY is 14 bytes in Home Assistant.  HA keeps
# the two-byte manufacturer identifier separately as the dict key, so those
# two bytes are prepended before decrypting the resulting 16-byte block.
BM2_ENHANCED_ADVERTISEMENT_PAYLOAD_LENGTH = 14

# ADVERTISEMENT FALLBACK:
# Legacy BM2s use an iBeacon-shaped Apple manufacturer record.  Home Assistant
# removes the 0x004C manufacturer ID, leaving a 23-byte body:
#   02 15 + fixed 16-byte UUID + major(2) + minor(2) + percentage(1)
BM2_LEGACY_MANUFACTURER_ID = 0x004C
BM2_LEGACY_PAYLOAD_LENGTH = 23
BM2_LEGACY_PREFIX = bytes.fromhex(
    "0215655f83caae16a10a702e31f30d58dd82"
)

# Sanity bounds are intentionally a little wider than the commonly-used
# 10-15 V range so unusual 12 V battery chemistries/states are not rejected.
BM2_MIN_VALID_VOLTAGE = 5.0
BM2_MAX_VALID_VOLTAGE = 20.0
BM2_MIN_VALID_PERCENTAGE = 0
BM2_MAX_VALID_PERCENTAGE = 100


class BMxSensor(StrEnum):
    BATTERY_PERCENT = "battery_percent"
    BATTERY_STATUS = "battery_status"
    BATTERY_VOLTAGE = "battery_voltage"
    SIGNAL_STRENGTH = "signal_strength"
    BM2_GENERATION = "bm2_generation"


class BM2Generation(StrEnum):
    """General BM2 protocol generation inferred from advertisement format."""

    UNKNOWN = "Unknown"
    LEGACY = "Legacy (percentage advertisement)"
    ENHANCED = "Enhanced (voltage + percentage advertisement)"


@dataclass
class ModelDescription:
    device_type: str
    identifier: int | str | bytes | None
    characteristic: str


# Apple manufacturer ID used by the BM2 iBeacon frame.  Retained as model
# metadata for compatibility/documentation, but no longer used to reject a
# device advertisement.
BMx_MANUFACTURER = 0x004C


class Models(Enum):
    BM2 = auto()
    BM6 = auto()  # Placeholder - not yet supported


DEVICE_TYPES = {
    Models.BM2: ModelDescription(
        device_type="BM2 battery monitor",
        identifier=BMx_MANUFACTURER,
        characteristic="{0000fff4-0000-1000-8000-00805f9b34fb}",
    ),
    Models.BM6: ModelDescription(
        device_type="BM6 battery monitor",
        identifier="TBD",
        characteristic="{TBD}",
    ),
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
    volts_to_percent: list[float]
    critical_voltage: float
    low_voltage: float
    floating_voltage: float
    charging_voltage: float


BATTERIES = {
    Battery.agm: BatteryDetail(
        "AGM",
        [10.5, 11.51, 11.66, 11.81, 11.95, 12.05, 12.15, 12.3, 12.5, 12.75, 12.8, 12.85],
        11.66,
        11.81,
        13.6,
        14.3,
    ),
    Battery.deepcycle: BatteryDetail(
        "Deep-cycle",
        [10.5, 11.51, 11.66, 11.81, 11.95, 12.05, 12.15, 12.3, 12.5, 12.75, 12.8],
        11.66,
        12.05,
        13.6,
        14.4,
    ),
    Battery.leadacid: BatteryDetail(
        "Lead-acid",
        [10.5, 11.31, 11.58, 11.75, 11.9, 12.06, 12.2, 12.32, 12.42, 12.5, 12.7],
        12.06,
        12.2,
        13.7,
        14.5,
    ),
    Battery.lifepo4: BatteryDetail(
        "LiFePO4",
        [10.0, 12.0, 12.5, 12.8, 12.9, 13.0, 13.1, 13.2, 13.3, 13.4, 13.6],
        10.5,
        12.0,
        13.5,
        14.4,
    ),
    Battery.lithiumion: BatteryDetail(
        "Lithium-ion",
        [10.0, 12.0, 12.8, 12.9, 13.0, 13.05, 13.1, 13.2, 13.3, 13.4, 13.6],
        10.5,
        12.0,
        13.5,
        14.25,
    ),
    Battery.itech120x: BatteryDetail(
        "iTechworld 120X (LiFePO4)",
        [9.5, 10.5, 12.5, 12.7, 12.8, 12.89, 12.91, 12.99, 13.01, 13.1, 13.5],
        10.5,
        12.5,
        13.5,
        14.35,
    ),
    Battery.custom: BatteryDetail(
        "Custom",
        [10.5, 11.58, 12.06, 13.6],
        12.06,
        12.2,
        13.7,
        14.5,
    ),
}


CHEMISTRY_OPTION_TO_BATTERY = {
    "AGM": Battery.agm,
    "Deep-cycle": Battery.deepcycle,
    "Lead-acid": Battery.leadacid,
    "LifePO4": Battery.lifepo4,
    "Lithium-ion": Battery.lithiumion,
    "itech120x": Battery.itech120x,
    "Custom": Battery.custom,
}


# ADVERTISEMENT FALLBACK:
# A common internal representation means GATT and advertisement decoding can
# share all battery-chemistry adjustment and sensor publishing logic.
@dataclass(frozen=True)
class BMxReading:
    voltage: float | None
    percentage: int | None
    status: int | None
    source: str
    generation: BM2Generation = BM2Generation.UNKNOWN


class BMxBluetoothDeviceData(BluetoothData):
    """Data for BMx BLE sensors."""

    def __init__(self) -> None:
        super().__init__()

        # If True, the latest interpreted status says the battery is charging
        # or floating.
        self._charging = False

        # Temporary storage populated by the BLE notification callback.
        self._gattdata: bytes | None = None

        # Prevent a new advertisement from causing a second active poll while
        # we are already waiting for GATT data.
        self._ignore_advertisement = False

        # Model metadata populated when the first advertisement is seen.
        self._model_info: ModelDescription | None = None

        # Populated by __init__.py immediately after construction.
        self._entrydata: dict = {}

        # ADVERTISEMENT FALLBACK:
        # The latest successfully decoded passive reading is cached but NOT
        # published from _start_update().  This preserves active-GATT-first
        # behaviour.
        self._advertisement_reading: BMxReading | None = None

        # ADVERTISEMENT FALLBACK:
        # General protocol era inferred from the advertisement format.  This is
        # intentionally not presented as an exact firmware version.
        self._bm2_generation = BM2Generation.UNKNOWN

    @property
    def bm2_generation(self) -> BM2Generation:
        """Return the inferred general BM2 protocol generation."""
        return self._bm2_generation

    def _start_update(self, service_info: BluetoothServiceInfo) -> None:
        """Process an advertisement.

        Device metadata is refreshed and, where possible, the newer encrypted
        BM2 telemetry frame is decoded and cached.  Sensor values are deliberately
        not published here; the cache is only consumed when the scheduled active
        poll fails (or no connectable Bluetooth path exists).
        """
        _LOGGER.debug("New advertisement - %s", service_info)

        address = service_info.address

        # ADVERTISEMENT FALLBACK:
        # Do not require manufacturer ID 0x004C.  That is the Apple iBeacon
        # record and is not the encrypted voltage/SOC telemetry record.
        self.set_device_manufacturer("Shenzhen Leagend Optoelectronics")

        model = Models.BM2  # Right now we only support the BM2
        model_info = DEVICE_TYPES[model]
        self._model_info = model_info

        self.set_device_type(model_info.device_type)
        name = f"{model_info.device_type} ({short_address(address)})"
        self.set_device_name(name)
        self.set_title(name)

        # ADVERTISEMENT FALLBACK:
        reading = self._decode_advertisement(service_info.manufacturer_data)
        if reading is not None:
            # CONFIG FLOW / GENERATION:
            # Enhanced BM2s can emit BOTH the old iBeacon-style percentage
            # packet and the newer encrypted voltage+percentage packet.
            #
            # Once Enhanced has been positively observed, never downgrade the
            # device back to Legacy merely because the next advertisement was
            # the old-format packet.
            if reading.generation is BM2Generation.ENHANCED:
                self._bm2_generation = BM2Generation.ENHANCED
                self._advertisement_reading = reading

            elif (
                reading.generation is BM2Generation.LEGACY
                and self._bm2_generation is BM2Generation.ENHANCED
                and self._advertisement_reading is not None
            ):
                # Preserve the most recently known enhanced voltage while
                # accepting the fresher percentage from the legacy packet.
                self._advertisement_reading = BMxReading(
                    voltage=self._advertisement_reading.voltage,
                    percentage=reading.percentage,
                    status=None,
                    source="advertisement",
                    generation=BM2Generation.ENHANCED,
                )

            else:
                self._bm2_generation = reading.generation
                self._advertisement_reading = reading

            _LOGGER.debug(
                "Cached BM2 advertisement reading for %s: generation=%s, "
                "voltage=%s, percentage=%s",
                address,
                self._bm2_generation,
                self._advertisement_reading.voltage,
                self._advertisement_reading.percentage,
            )

    def poll_needed(
        self,
        service_info: BluetoothServiceInfo,
        last_poll: float | None,
    ) -> bool:
        """Return True when the coordinator should perform its scheduled poll."""
        _LOGGER.debug(
            "Inside 'poll_needed' for %s, _ignore_advertisement=%s, "
            "_charging=%s, _model_info=%s",
            service_info.address,
            self._ignore_advertisement,
            self._charging,
            self._model_info,
        )

        if self._ignore_advertisement:
            return False

        if last_poll is None:
            return True

        scan_mode = self._entrydata.get(CONF_SCAN_MODE, DEFAULT_SCAN_MODE)

        if scan_mode == "Never rate limit sensor updates":
            return True

        if scan_mode == "Only rate limit when not charging" and self._charging:
            return True

        update_interval = self._entrydata.get(
            CONF_SCAN_INTERVAL,
            DEFAULT_SCAN_INTERVAL,
        )

        # Keep the existing coordinator semantics used by the integration.
        poll_needed = last_poll > update_interval

        _LOGGER.debug(
            "Poll rate limited for %s: update_interval=%s, last_poll=%s, "
            "poll_needed=%s",
            service_info.address,
            update_interval,
            last_poll,
            poll_needed,
        )
        return poll_needed

    @staticmethod
    def _decrypt(data: bytes) -> bytes:
        """Decrypt one complete 16-byte BM2 AES block."""
        if len(data) != AES.block_size:
            raise ValueError(
                f"BM2 encrypted payload must be {AES.block_size} bytes; "
                f"received {len(data)}"
            )

        cipher = AES.new(BM2_AES_KEY, AES.MODE_CBC, BM2_AES_IV)
        return cipher.decrypt(data)

    # ADVERTISEMENT FALLBACK:
    def _decode_advertisement(
        self,
        manufacturer_data: dict[int, bytes],
    ) -> BMxReading | None:
        """Decode either known BM2 advertisement generation.

        Enhanced/newer format:
            - any 14-byte manufacturer-data body
            - prepend the two-byte manufacturer ID (little-endian)
            - AES decrypt the resulting 16-byte block
            - decrypted bytes 6-7 = voltage * 100, big-endian
            - decrypted byte 8 = battery percentage

        Legacy/older format:
            - Apple manufacturer ID 0x004C
            - 23-byte iBeacon-shaped body
            - fixed BM2 UUID prefix
            - final byte = battery percentage
            - no voltage is present in the advertisement
        """

        # Prefer the enhanced packet when both formats are advertised.
        for manufacturer_id, payload in manufacturer_data.items():
            if len(payload) != BM2_ENHANCED_ADVERTISEMENT_PAYLOAD_LENGTH:
                continue

            encrypted = manufacturer_id.to_bytes(2, byteorder="little") + payload

            try:
                decrypted = self._decrypt(encrypted)
            except ValueError:
                continue

            voltage = int.from_bytes(decrypted[6:8], byteorder="big") / 100.0
            percentage = decrypted[8]

            # Packet length alone is not enough to identify BM2 telemetry.
            if not BM2_MIN_VALID_VOLTAGE <= voltage <= BM2_MAX_VALID_VOLTAGE:
                continue
            if not (
                BM2_MIN_VALID_PERCENTAGE
                <= percentage
                <= BM2_MAX_VALID_PERCENTAGE
            ):
                continue

            return BMxReading(
                voltage=voltage,
                percentage=percentage,
                status=None,
                source="advertisement",
                generation=BM2Generation.ENHANCED,
            )

        # Legacy packet: Home Assistant exposes 0x004C as the dict key, so the
        # payload itself begins at the iBeacon 0x02 0x15 marker.
        legacy_payload = manufacturer_data.get(BM2_LEGACY_MANUFACTURER_ID)

        if (
            legacy_payload is not None
            and len(legacy_payload) == BM2_LEGACY_PAYLOAD_LENGTH
            and legacy_payload.startswith(BM2_LEGACY_PREFIX)
        ):
            percentage = legacy_payload[-1]

            if (
                BM2_MIN_VALID_PERCENTAGE
                <= percentage
                <= BM2_MAX_VALID_PERCENTAGE
            ):
                return BMxReading(
                    voltage=None,
                    percentage=percentage,
                    status=None,
                    source="advertisement",
                    generation=BM2Generation.LEGACY,
                )

        return None

    def _decode_gatt(self, data: bytes) -> BMxReading:
        """Decode the BM2 GATT notification payload."""
        decrypted = self._decrypt(data)

        # Preserve the currently proven GATT byte/nibble mapping from the
        # existing integration:
        #   voltage    = decrypted hex chars [2:5] / 100
        #   status     = decrypted hex char  [5:6]
        #   percentage = decrypted hex chars [6:8]
        raw = decrypted.hex()

        return BMxReading(
            voltage=int(raw[2:5], 16) / 100.0,
            percentage=int(raw[6:8], 16),
            status=int(raw[5:6], 16),
            source="gatt",
            generation=BM2Generation.UNKNOWN,
        )

    def _battery_detail(self) -> tuple[BatteryDetail | None, bool]:
        """Return configured battery chemistry details and custom flag."""
        battery_option = self._entrydata.get(
            CONF_BATTERY_TYPE,
            DEFAULT_BATTERY_TYPE,
        )

        if battery_option == "Automatic (via BM2)":
            return None, False

        if battery_option != "Custom":
            battery_chemistry = CHEMISTRY_OPTION_TO_BATTERY[battery_option]
            return BATTERIES[battery_chemistry], False

        # Create a fresh BatteryDetail rather than mutating the shared
        # BATTERIES[Battery.custom] object.
        battery_detail = BatteryDetail(
            battery_chemistry=self._entrydata.get(
                CONF_CUSTOM_BATTERY_CHEMISTRY,
                DEFAULT_CUSTOM_BATTERY_CHEMISTRY,
            ),
            volts_to_percent=self._entrydata.get(
                CONF_CUSTOM_NUMPY_VOLTS,
                DEFAULT_CUSTOM_NUMPY_VOLTS,
            ),
            critical_voltage=self._entrydata.get(
                CONF_CUSTOM_CRITICAL_VOLTAGE,
                DEFAULT_CUSTOM_CRITICAL_VOLTAGE,
            ),
            low_voltage=self._entrydata.get(
                CONF_CUSTOM_LOW_VOLTAGE,
                DEFAULT_CUSTOM_LOW_VOLTAGE,
            ),
            floating_voltage=self._entrydata.get(
                CONF_CUSTOM_FLOATING_VOLTAGE,
                DEFAULT_CUSTOM_FLOATING_VOLTAGE,
            ),
            charging_voltage=self._entrydata.get(
                CONF_CUSTOM_CHARGING_VOLTAGE,
                DEFAULT_CUSTOM_CHARGING_VOLTAGE,
            ),
        )
        return battery_detail, True

    # ADVERTISEMENT FALLBACK:
    def _apply_reading(self, reading: BMxReading) -> None:
        """Apply available fields and publish a decoded reading.

        Advertisement fallback can be partial.  Legacy advertisements carry
        percentage but no voltage/status, so unavailable fields are deliberately
        left at their previous Home Assistant values.
        """
        voltage = reading.voltage
        percentage = reading.percentage
        status = reading.status

        battery_detail, custom = self._battery_detail()

        # Chemistry-based percentage/status calculations require voltage.
        if battery_detail is not None and voltage is not None:
            if percentage is not None:
                percentage = self._adjust_percentage(
                    percentage,
                    battery_detail,
                    voltage,
                    custom,
                )

            status = self._adjust_status(
                status if status is not None else 2,
                battery_detail,
                voltage,
            )

        if percentage is not None:
            self.update_sensor(
                key=str(BMxSensor.BATTERY_PERCENT),
                native_unit_of_measurement=PERCENTAGE,
                native_value=percentage,
                device_class=SensorDeviceClass.BATTERY,
            )

        if voltage is not None:
            self.update_sensor(
                key=str(BMxSensor.BATTERY_VOLTAGE),
                native_unit_of_measurement=UnitOfElectricPotential.VOLT,
                native_value=voltage,
                device_class=SensorDeviceClass.VOLTAGE,
            )

        # Automatic-via-BM2 passive packets do not expose a decoded status.
        # Leave the previous status intact instead of inventing one.
        if status is not None:
            status_text = BATTERY_STATUS_LIST.get(status, "Unknown")
            self.update_sensor(
                key=str(BMxSensor.BATTERY_STATUS),
                native_unit_of_measurement=None,
                native_value=status_text,
                device_class=None,
            )
            self._charging = status >= 4

        # Generation is inferred from advertisements.  Publish it alongside
        # either an active or fallback update once it is known.
        if self._bm2_generation is not BM2Generation.UNKNOWN:
            self.update_sensor(
                key=str(BMxSensor.BM2_GENERATION),
                native_unit_of_measurement=None,
                native_value=str(self._bm2_generation),
                device_class=None,
            )

        _LOGGER.debug(
            "Published BM2 %s reading: generation=%s, voltage=%s, "
            "percentage=%s, status=%s",
            reading.source,
            self._bm2_generation,
            voltage,
            percentage,
            status,
        )

    @retry_bluetooth_connection_error()
    async def _get_payload(
        self,
        client: BleakClientWithServiceCache,
    ) -> BMxReading:
        """Read and decode the active BM2 GATT notification."""
        if self._model_info is None:
            raise RuntimeError("BM2 model information is not initialised")

        self._gattdata = None
        self._ignore_advertisement = True

        try:
            await client.start_notify(
                self._model_info.characteristic,
                self.notification_handler,
            )

            ticks = 0
            while self._gattdata is None and ticks < GATT_TIMEOUT * 4:
                await asyncio.sleep(0.25)
                ticks += 1

        finally:
            # Always attempt to stop notification handling and, importantly,
            # always clear the ignore flag even if Bleak throws.
            try:
                await client.stop_notify(self._model_info.characteristic)
            finally:
                self._ignore_advertisement = False

        if self._gattdata is None:
            # CHANGED:
            # The previous implementation silently returned here.  Raising
            # makes a no-notification timeout a genuine failed active read,
            # allowing async_poll() to use the cached advertisement.
            raise TimeoutError(
                f"Timed out waiting for BM2 GATT notification from {client.address}"
            )

        _LOGGER.debug(
            "Successfully read characteristic %s",
            self._model_info.characteristic,
        )
        return self._decode_gatt(self._gattdata)

    def notification_handler(self, sender, data: bytearray) -> None:
        """Bluetooth notification handler."""
        self._gattdata = bytes(data)

    async def async_validate_active(self, ble_device: BLEDevice) -> bool:
        """Positively validate a BM2 using its active GATT protocol.

        This is intended for config-flow validation only.

        Returns:
            True:
                FFF4 exists, a notification was received, it decrypted with
                the BM2 key, and the decoded values are plausible.

            False:
                The device is positively incompatible (for example FFF4 is
                absent, or a notification decrypts to implausible BM2 data).

        Connection errors and notification timeouts deliberately propagate.
        The config flow treats those as "could not validate" rather than
        incorrectly declaring that the device is not a BM2.
        """
        client: BleakClientWithServiceCache | None = None

        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                ble_device.address,
            )

            # Config-flow DeviceData instances may not have processed an
            # advertisement through _start_update() yet.
            if self._model_info is None:
                self._model_info = DEVICE_TYPES[Models.BM2]

            target_uuid = self._model_info.characteristic.lower().strip("{}")

            characteristic_found = any(
                characteristic.uuid.lower().strip("{}") == target_uuid
                for service in client.services
                for characteristic in service.characteristics
            )

            if not characteristic_found:
                _LOGGER.debug(
                    "BM2 validation failed for %s: characteristic %s not found",
                    ble_device.address,
                    self._model_info.characteristic,
                )
                return False

            reading = await self._get_payload(client)

            if reading.voltage is None or reading.percentage is None:
                return False

            if not (
                BM2_MIN_VALID_VOLTAGE
                <= reading.voltage
                <= BM2_MAX_VALID_VOLTAGE
            ):
                return False

            if not (
                BM2_MIN_VALID_PERCENTAGE
                <= reading.percentage
                <= BM2_MAX_VALID_PERCENTAGE
            ):
                return False

            if (
                reading.status is not None
                and reading.status not in BATTERY_STATUS_LIST
            ):
                return False

            return True

        finally:
            if client is not None:
                await client.disconnect()

    async def async_poll(
        self,
        ble_device: BLEDevice | None,
    ) -> SensorUpdate:
        """Prefer an active GATT read and fall back to advertisement data.

        Passing ble_device=None means Home Assistant heard the device through a
        passive scanner/proxy but currently has no connectable Bluetooth path.
        """
        client: BleakClientWithServiceCache | None = None

        try:
            if ble_device is None:
                raise ConnectionError(
                    "No connectable Bluetooth path is currently available"
                )

            _LOGGER.debug(
                "Connecting to Bluetooth device %s",
                ble_device.address,
            )

            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                ble_device.address,
            )

            _LOGGER.debug(
                "Connected to BM2 device %s",
                ble_device.address,
            )

            reading = await self._get_payload(client)
            self._apply_reading(reading)
            return self._finish_update()

        except Exception as ex:
            # ADVERTISEMENT FALLBACK:
            # Active connection/read failed.  If the immediately preceding
            # advertisement contained usable telemetry, publish it instead.
            if self._advertisement_reading is not None:
                address = ble_device.address if ble_device is not None else "unknown"
                _LOGGER.debug(
                    "Active BM2 read failed for %s (%s); using cached "
                    "advertisement data",
                    address,
                    ex,
                )
                self._apply_reading(self._advertisement_reading)
                return self._finish_update()

            # No usable passive fallback exists, so preserve the failure.
            raise

        finally:
            if client is not None:
                try:
                    await client.disconnect()
                finally:
                    _LOGGER.debug(
                        "Disconnected from active Bluetooth client"
                    )

    def _adjust_percentage(
        self,
        raw_percentage: int,
        battery_detail: BatteryDetail,
        voltage: float,
        custom: bool = False,
    ) -> int:
        """Adjust battery percentage using the configured chemistry curve."""
        if not custom:
            np_percent = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        else:
            np_percent = [0, 20, 50, 100]

        new_percentage = int(
            np.interp(
                voltage,
                battery_detail.volts_to_percent,
                np_percent,
            )
        )

        _LOGGER.debug(
            "Adjusting percentage based on battery chemistry %s: "
            "voltage=%s, raw=%s, adjusted=%s",
            battery_detail.battery_chemistry,
            voltage,
            raw_percentage,
            new_percentage,
        )
        return new_percentage

    def _adjust_status(
        self,
        raw_status: int,
        battery_detail: BatteryDetail,
        voltage: float,
    ) -> int:
        """Adjust battery status using the configured chemistry thresholds."""
        if voltage >= battery_detail.charging_voltage:
            new_status = 4  # Charging
        elif voltage >= battery_detail.floating_voltage:
            new_status = 8  # Floating
        elif voltage <= battery_detail.critical_voltage:
            new_status = 0  # Critical
        elif voltage <= battery_detail.low_voltage:
            new_status = 1  # Low
        else:
            new_status = 2  # Normal

        _LOGGER.debug(
            "Adjusting state based on battery chemistry %s: "
            "critical=%s, low=%s, float=%s, charging=%s, voltage=%s, "
            "raw=%s, adjusted=%s",
            battery_detail.battery_chemistry,
            battery_detail.critical_voltage,
            battery_detail.low_voltage,
            battery_detail.floating_voltage,
            battery_detail.charging_voltage,
            voltage,
            raw_status,
            new_status,
        )
        return new_status