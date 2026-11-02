# Simple software visualization v2.0 - verification

Prepared on 2 November 2026. This edition simplifies the opening visualization for a general audience. It does not modify firmware, server, simulator, deployment settings or hardware.

## Presentation design

The first slide now has five main stages, one command return route, and four supporting services. It uses five flow arrows in total, without crossing paths. Native line icons, larger labels and short descriptions make the reading order explicit. Supporting services are grouped below the main flow; technical exceptions and implementation references are retained in Speaker Notes. Slide 2 preserves the existing realistic system illustration.

## Completed checks

- Content reviewed against the same active Arduino STM32 architecture, source baseline `6edb8f79691b5c8d5917c1112626f861b9271b2f`.
- The connection block explicitly covers LoRa through a gateway or direct WiFi/SIM, with MQTT exchange. The command line names the server return path; it is not a physical direct browser-to-node connection.
- Native XML verification passed for five stage blocks, four supporting-service blocks, all 30 text objects and five editable flow arrows. The overview slide contains no embedded raster diagram.
- Text width, height and slide bounds checked with the actual Arial fonts.
- Presentation finalizer passed package integrity, 3200 x 1800 layout, heading/font checks and first-party import with zero layout findings.
- Both final slides opened and rendered in Microsoft PowerPoint. Visually reviewed each complete slide for text fit, hierarchy, line routing, icon placement and image framing.
- In a temporary copy, edited native node text and a command-arrow path point, restored them, saved and reopened successfully. The delivered deck was not modified by this smoke check.
- PNG exported from the final PowerPoint at 6400 x 3600 pixels. SVG parsed successfully as XML and retains vector text/shapes.
- Confirmed the original illustration's exact bytes are embedded in slide 2; no new image was generated.

## Output SHA-256

| File | SHA-256 |
| --- | --- |
| WIOT_Software_Overview_Simple_v2.0.pptx | `3adbc790486ea808a0b23407b58a9f4632921fc72e7ad13d8dab7272605500b7` |
| WIOT_Software_Overview_Simple_v2.0.png | `cc6c8635109fc77018bf0ccf12e1c97be2ce7dcc7d2bf7e61753e6b68a7cf3c1` |
| WIOT_Software_Overview_Simple_v2.0.svg | `78a12628bdac931c2720e16f40bd64974ec202fa452715081d2d531fcef238f8` |

The original engineering overview and 30 detailed flowcharts remain available for implementation reviews. This simpler view intentionally does not expand protocol internals, every command or each power-state transition.
