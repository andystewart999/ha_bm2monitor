"""The BM2 battery monitor integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.components.bluetooth import (
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
)
from homeassistant.components.bluetooth.active_update_processor import (
    ActiveBluetoothProcessorCoordinator,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .bmx_ble import BMxBluetoothDeviceData, SensorUpdate
from .const import CONF_BATTERY_TYPE, DEFAULT_BATTERY_TYPE, DOMAIN

PLATFORMS: list[Platform] = [Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)

ISSUE_CHEMISTRY_NO_EFFECT = "chemistry_has_no_effect"


@dataclass
class BMxRuntimeData:
    """Runtime data for a BM2 config entry."""

    coordinator: ActiveBluetoothProcessorCoordinator
    device_data: BMxBluetoothDeviceData


type BMxConfigEntry = ConfigEntry[BMxRuntimeData]


def _issue_id(entry: ConfigEntry) -> str:
    return f"{ISSUE_CHEMISTRY_NO_EFFECT}_{entry.entry_id}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BMxConfigEntry,
) -> bool:
    """Set up BMx BLE device from a config entry."""
    address = entry.unique_id
    assert address is not None

    device_data = BMxBluetoothDeviceData()
    device_data._entrydata = entry.data

    # The chemistry may have just been changed; re-evaluate from scratch.
    ir.async_delete_issue(hass, DOMAIN, _issue_id(entry))
    issue_raised = False

    def _connectable_device(service_info: BluetoothServiceInfoBleak):
        """Return a connectable BLEDevice for this BM2, or None."""
        if service_info.connectable:
            return service_info.device
        return async_ble_device_from_address(hass, address, connectable=True)

    def _update(service_info: BluetoothServiceInfoBleak) -> SensorUpdate:
        """Process an advertisement."""
        nonlocal issue_raised

        device_data.note_connectable_path(
            _connectable_device(service_info) is not None
        )
        update = device_data.update(service_info)

        # Tell the user if their chosen chemistry can't do anything.
        if device_data.chemistry_has_no_effect != issue_raised:
            issue_raised = not issue_raised
            if issue_raised:
                ir.async_create_issue(
                    hass,
                    DOMAIN,
                    _issue_id(entry),
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=ISSUE_CHEMISTRY_NO_EFFECT,
                    translation_placeholders={
                        "name": entry.title,
                        "battery_type": entry.data.get(
                            CONF_BATTERY_TYPE, DEFAULT_BATTERY_TYPE
                        ),
                    },
                )
            else:
                ir.async_delete_issue(hass, DOMAIN, _issue_id(entry))

        return update

    def _needs_poll(
        service_info: BluetoothServiceInfoBleak,
        last_poll: float | None,
    ) -> bool:
        """Return whether this advertisement should trigger an active read."""
        # device_data only asks for a read when the advertisement is missing
        # something AND a connectable path has recently been seen.
        return (
            hass.state is CoreState.running
            and device_data.poll_needed(service_info, last_poll)
            and _connectable_device(service_info) is not None
        )

    async def _async_poll(
        service_info: BluetoothServiceInfoBleak,
    ) -> SensorUpdate:
        """Read the BM2 over an active connection."""
        ble_device = _connectable_device(service_info)
        if ble_device is None:
            # The connectable path went away between deciding to poll and
            # polling.  Nothing new to publish.
            return device_data.last_update()

        try:
            return await device_data.async_poll(ble_device)
        except Exception:  # noqa: BLE001 - recorded and logged by device_data
            # The advertisement data already published stays in place.  Not
            # raising avoids a traceback in the log for every failed read on
            # a marginal connection.
            return device_data.last_update()

    coordinator = ActiveBluetoothProcessorCoordinator(
        hass,
        _LOGGER,
        address=address,
        mode=BluetoothScanningMode.PASSIVE,
        update_method=_update,
        needs_poll_method=_needs_poll,
        poll_method=_async_poll,
        # Accept advertisements from non-connectable scanners/proxies.  When a
        # connectable path is available it is used for active reads.
        connectable=False,
    )
    entry.runtime_data = BMxRuntimeData(coordinator, device_data)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Only start after all platforms have had a chance to subscribe.
    entry.async_on_unload(coordinator.async_start())

    # Reload if the options change.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: BMxConfigEntry,
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up when a config entry is removed."""
    ir.async_delete_issue(hass, DOMAIN, _issue_id(entry))


async def _async_update_listener(
    hass: HomeAssistant,
    entry: BMxConfigEntry,
) -> None:
    """Handle config options update."""
    _LOGGER.debug("Options have changed, reloading integration")
    await hass.config_entries.async_reload(entry.entry_id)
