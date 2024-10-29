"""Constants for the BM2 Bluetooth integration."""

from __future__ import annotations

from typing import Final, TypedDict

DOMAIN = "bm2_ble"


CONF_DISCOVERED_EVENT_CLASSES: Final = "known_events"
CONF_EVENT_PROPERTIES: Final = "event_properties"
CONF_EVENT_CLASS: Final = "event_class"
CONF_SLEEPY_DEVICE: Final = "sleepy_device"
CONF_SUBTYPE: Final = "subtype"

EVENT_CLASS: Final = "event_class"
EVENT_TYPE: Final = "event_type"
EVENT_SUBTYPE: Final = "event_subtype"
EVENT_PROPERTIES: Final = "event_properties"
XIAOMI_BLE_EVENT: Final = "xiaomi_ble_event"
