# Flashing manual verification

8 November 2026

This release adds operator documentation. It does not change firmware, server
code, private credentials or the final folder's active build configuration.
The source baseline is 9800acc33a5654aff64c4d3ee858292a0c83270f.

## Content review

The manual defines six labelled profiles for direct Wi-Fi, direct SIM800L,
two LoRa leaves and the Wi-Fi or SIM gateway alternatives. Sample identities
are explicitly bench examples. The initial test uses NORMAL mode with sensor
polling and actuation disabled. Later procedures enable each feature.

Role, uplink, power, debug, watchdog and sensor macro names were checked against
AppConfig.h. Modem, radio, RS485, SPI, SWD and debug pins were checked against
the current configuration and radio guide. Arduino settings were checked against
the installed 2.12.0 board package and the release build records. SWD programming
and recovery were cross-checked with the official STM32duino installation guide
and STM32CubeProgrammer documentation cited in the manual.

The sensor values match stm32_four_sensor_config.json. The tests distinguish
the demo fleet from that fixture and warn against two masters on one physical
RS485 bus. The guide uses the current server port 8000 and explains that its
entry point does not load a .env file automatically.

Twenty test groups cover boot, direct links, two-node LoRa operation, all four
sensors, unavailable readings, command timing, RTC periods, SPI archive and
history, remote idle, WOR, Standby, queued work, reset counters, network
recovery, voltage, valve control, debug choices and a 48-hour soak. These are
expected procedures. Hardware results must be recorded by the tester.

## Document checks

The editable Word manual was built from the Markdown source using the bundled
Python runtime. Microsoft Word refreshed its contents and page fields and
exported a temporary PDF. The packaged documents renderer rasterized that PDF
to 25 page images. All pages were visually inspected at full page resolution.
The final test record occupies its own page. No table rows, code lines or
references are clipped. The title has no inherited decorative rule.

The build helper compiles, the document opens, all twenty test IDs are present,
and referenced local files resolve. No actual application key, password or
network credential is included. Temporary render outputs are ignored by Git.

No device was flashed and no live network, reset, valve, archive-clear or
hardware acceptance action was run while authoring this documentation.
