"""The BM2 battery monitor integration.

Changes for advertisement fallback are marked with:
    # ADVERTISEMENT FALLBACK:
"""

from __future__ import annotations

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

from .bmx_ble import BMxBluetoothDeviceData, SensorUpdate

PLATFORMS: list[Platform] = [Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)

type BMxConfigEntry = ConfigEntry[ActiveBluetoothProcessorCoordinator]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BMxConfigEntry,
) -> bool:
    """Set up BMx BLE device from a config entry."""
    address = entry.unique_id
    assert address is not None

    device_data = BMxBluetoothDeviceData()
    device_data._entrydata = entry.data

    def _needs_poll(
        service_info: BluetoothServiceInfoBleak,
        last_poll: float | None,
    ) -> bool:
        """Return whether this advertisement should trigger a scheduled update."""
        # ADVERTISEMENT FALLBACK:
        # Do NOT require a connectable BLEDevice here.
        #
        # Previously this condition prevented the poll callback from running at
        # all when the BM2 could only be heard by a passive proxy/scanner.  The
        # updated poll callback can now publish cached advertisement telemetry
        # in that situation, so hearing the device is enough to proceed.
        return hass.state is CoreState.running and device_data.poll_needed(
            service_info, last_poll
        )

    async def _async_poll(
        service_info: BluetoothServiceInfoBleak,
    ) -> SensorUpdate:
        """Try to find a connectable path, otherwise use passive fallback."""
        connectable_device = None

        if service_info.connectable:
            connectable_device = service_info.device
        else:
            connectable_device = async_ble_device_from_address(
                hass,
                service_info.device.address,
                connectable=True,
            )

        # ADVERTISEMENT FALLBACK:
        # async_poll(None) is intentional.  BMxBluetoothDeviceData will treat
        # "no connectable path" exactly like a failed active connection and use
        # the cached advertisement if the newer telemetry packet was decoded.
        return await device_data.async_poll(connectable_device)

    coordinator = entry.runtime_data = ActiveBluetoothProcessorCoordinator(
        hass,
        _LOGGER,
        address=address,
        mode=BluetoothScanningMode.PASSIVE,
        update_method=device_data.update,
        needs_poll_method=_needs_poll,
        poll_method=_async_poll,
        # Accept advertisements from non-connectable scanners/proxies.  When a
        # connectable path is available it is still preferred for the GATT read.
        connectable=False,
    )

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


async def _async_update_listener(
    hass: HomeAssistant,
    entry: BMxConfigEntry,
) -> None:
    """Handle config options update."""
    _LOGGER.debug("Options have changed, reloading integration")
    await hass.config_entries.async_reload(entry.entry_id)
