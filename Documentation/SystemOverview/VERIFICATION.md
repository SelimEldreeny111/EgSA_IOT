# Overview verification - 2 November 2026

Scope: documentation and illustrations only. Firmware, server, simulator, secrets and hardware settings were not modified.

## Completed checks

- Reviewed the architecture against the active source baseline `b4fc108519d870491c5fd97b3aaef808378e3928` and the existing detailed flow definitions. Every referenced source file exists.
- Confirmed separate compiled node/gateway roles, alternative direct-IP/LoRa routing, command priority, sensor validity, flash retention, RTC period totals, reset counters and power/wake distinctions.
- The PPTX finalizer passed package integrity, declared 3200 x 1800 slide geometry, Arial font policy, heading/layout checks and first-party import, with zero layout findings.
- XML/content checks verified 30 native architecture blocks, their complete headings/body text, and 32 native editable routed arrows. Slide 1 contains no embedded diagram image; slide 2 contains one embedded illustration.
- Measured every block's title/body lines with Arial and checked available width, height and slide bounds.
- Microsoft PowerPoint opened and rendered both final slides. The architecture export is 6400 x 3600 pixels; the separate generated illustration is 1672 x 940 pixels.
- Visually reviewed the actual PowerPoint renders. Corrected storage-block outlines so they do not cross headings. Checked text, routing, legend, margins and illustration placement.
- In a separate deck copy, edited native text and an arrow path point, restored the values, saved and reopened successfully. The delivered deck was not changed by that test.
- Parsed the SVG as XML and confirmed source-reference paths. The SVG uses vector shapes/text, while the PNG is a PowerPoint render of the editable slide.
- Reviewed the generated image for system topology: two field nodes connect through one LoRa gateway and MQTT broker to the Python server/dashboard. Representative hardware appearance is explicitly labelled in the image and in slide notes.

## Output SHA-256

| File | SHA-256 |
| --- | --- |
| WIOT_System_Architecture_Overview_v1.0.pptx | `fc0c07d68546ccded316931dcff01f6d7d0220bb20879e1f30065da8d05a3b08` |
| WIOT_Software_Architecture.png | `5d6af4a2aca4841d82dd5472868f83f40bacefb95d6b9e55dd197d985a3cae13` |
| WIOT_Software_Architecture.svg | `23c7825e5f8f0ba43f4abf51a6ae786f895e25dbbdb5a2fc9140d8be792ff367` |
| WIOT_Node_Gateway_Server_Illustration.png | `1361d629743dd09c62d42a30aec240e417fe4abbe31d3b6878653a4a19fbc321` |

The realistic image was made with the built-in Image Generation tool. Its complete final prompt and provenance are in `image_prompt.txt`. No fallback CLI or external image API was used.

This is one functional architecture overview. It does not replace the detailed state-machine diagrams, hardware schematic, sensor datasheets or a physical acceptance test.
