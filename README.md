# BM2 Battery Monitor
[![Last release version](https://img.shields.io/github/v/release/andystewart999/ha_bm2monitor)](https://github.com/andystewart999/ha_bm2monitor/releases)
[![Last release date](https://img.shields.io/github/release-date/andystewart999/ha_bm2monitor)](https://github.com/andystewart999/ha_bm2monitor/releases)
[![Contributors](https://img.shields.io/github/contributors/andystewart999/ha_bm2monitor)](https://github.com/andystewart999/ha_bm2monitor/graphs/contributors)
[![Project license](https://img.shields.io/github/license/andystewart999/ha_bm2monitor)](https://github.com/andystewart999/ha_bm2monitor/blob/master/LICENSE)
![hacs](https://img.shields.io/badge/hacs-standard_installation-darkorange.svg)
![type](https://img.shields.io/badge/type-custom_component-forestgreen.svg)


A custom integration to monitor the BM2 battery monitor via Bluetooth.

It discovers BM2 battery monitor devices and creates sensors based on battery voltage, percentage and general state via explicit connection rather than BLE broadcast, which is what most other BM2-supporting integrations do.  BLE broadcasts only contain the percentage unfortunately.

There is an option to explicitily define the battery chemistry type which affects the percentage and status calculations.  A number of sources have been used in the volts-to-percentage mapping function, which uses Numpy for interpolating the voltage vs percentage details.
  
With thanks to @KrystianD for his reverse-engineering of the BM2 data and app, and @bdraco and @Lash-L for the Oral-B integration that I, ah, leveraged.

