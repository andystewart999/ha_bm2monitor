"""Constants for the BM2 battery monitor integration."""

DOMAIN = "ha_bm2monitor"

CONF_BATTERY_TYPE = "battery_type"
DEFAULT_BATTERY_TYPE = "Automatic (via BM2)"
DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 30
CONF_SCAN_MODE = "scan_mode"
DEFAULT_SCAN_MODE = "Always rate limit sensor updates"

GATT_TIMEOUT = 20

BM_NAMES = [
    "Battery Monitor",
    "Li Battery Monitor",
    "ZX-1689"
]


SCAN_MODES = [
    "Always rate limit sensor updates",
    "Never rate limit sensor updates",
    "Only rate limit when not charging"
]


BATTERY_TYPES = [
    "Automatic (via BM2)",
    "AGM",
    "Deep-cycle",
    "Lead-acid",
    "LiFePO4",
    "Lithium-ion"
]

BATTERY_STATUS_LIST = {
    0: "Critical",
    1: "Low",
    2: "Normal",
    4: "Charging",
    8: "Floating"
}

BATTERY_STATUS_ICON = {
    "Critical" : "mdi:battery-remove-outline",
    "Low" : "mdi:battery-arrow-down-outline",
    "Normal" : "mdi:battery-check",
    "Floating" : "mdi:battery-sync",
    "Charging" : "mdi:battery-charging-100"
}
