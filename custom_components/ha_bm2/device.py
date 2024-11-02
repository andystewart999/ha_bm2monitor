import logging

from bluetooth_sensor_state_data import BluetoothData
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.helpers.service_info.bluetooth import BluetoothServiceInfo
from sensor_state_data import SensorLibrary
from sensor_state_data.enum import StrEnum
from sensor_state_data.units import Units
from victron_ble.devices import detect_device_type
from victron_ble.devices.battery_monitor import AuxMode, BatteryMonitorData
from victron_ble.devices.battery_sense import BatterySenseData
from victron_ble.devices.dc_energy_meter import DcEnergyMeterData
from victron_ble.devices.dcdc_converter import DcDcConverterData
from victron_ble.devices.solar_charger import SolarChargerData

_LOGGER = logging.getLogger(__name__)


class VictronSensor(StrEnum):
    AUX_MODE = "aux_mode"
    OPERATION_MODE = "operation_mode"
    EXTERNAL_DEVICE_LOAD = "external_device_load"
    YIELD_TODAY = "yield_today"
    INPUT_VOLTAGE = "input_voltage"
    OUTPUT_VOLTAGE = "output_voltage"
    OFF_REASON = "off_reason"
    CHARGER_ERROR = "charger_error"
    STARTER_BATTERY_VOLTAGE = "starter_battery_voltage"
    MIDPOINT_VOLTAGE = "midpoint_voltage"
    TIME_REMAINING = "time_remaining"


class VictronBluetoothDeviceData(BluetoothData):
    """Data for Victron BLE sensors."""

    def __init__(self, key) -> None:
        """Initialize the class."""
        super().__init__()
        self.key = key

    def _start_update(self, service_info: BluetoothServiceInfo) -> None:
        """Update from BLE advertisement data."""
        _LOGGER.error(
            "Parsing BM2 BLE advertisement data: %s", service_info.manufacturer_data
        )
        manufacturer_data = service_info.manufacturer_data
        service_uuids = service_info.service_uuids
        local_name = service_info.name
        address = service_info.address
        self.set_device_name(local_name)
        self.set_device_manufacturer("Victron")

        self.set_precision(2)

        _LOGGER.error(
            "About to process manufacturer_data.items"
        )
        for mfr_id, mfr_data in manufacturer_data.items():
"""            if mfr_id != 0x02E1 or not mfr_data.startswith(b"\x10"): """
"""                continue  """
            self._process_mfr_data(address, local_name, mfr_id, mfr_data, service_uuids)

    def _process_mfr_data(
        self,
        address: str,
        local_name: str,
        mfr_id: int,
        data: bytes,
        service_uuids: list[str],
    ) -> None:
        """Parser for Victron sensors."""
        """device_parser = detect_device_type(data)"""
        """parsed = device_parser(self.key).parse(data)"""
        _LOGGER.error(f"Handle BM2 BLE advertisement data: {data}")
        # self.set_device_type(parsed.get_model_name())

        # if isinstance(parsed, DcEnergyMeterData):
        #     self.update_predefined_sensor(
        #         SensorLibrary.VOLTAGE__ELECTRIC_POTENTIAL_VOLT, parsed.get_voltage()
        #     )
        #     self.update_predefined_sensor(
        #         SensorLibrary.CURRENT__ELECTRIC_CURRENT_AMPERE, parsed.get_current()
        #     )
        # elif isinstance(parsed, BatteryMonitorData):
        self.update_predefined_sensor(
            SensorLibrary.VOLTAGE__ELECTRIC_POTENTIAL_VOLT, 12.5
            )
            # self.update_predefined_sensor(
            #     SensorLibrary.CURRENT__ELECTRIC_CURRENT_AMPERE, parsed.get_current()
            # )
        self.update_predefined_sensor(
            SensorLibrary.BATTERY__PERCENTAGE, 55
        )

        return
