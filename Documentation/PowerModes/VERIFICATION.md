# Documentation verification - 04 October 2026

Firmware baseline: `48e5e4b468e6e628feae1ad7ce14fe1942402b3d`.
Documentation branch: `feature/2026-10-04-power-mode-reference`.

## Completed checks

- Reviewed actual AppConfig power-policy guards and power-manager, MQTT,
  LoRa wake and server command-mailbox implementations.
- Confirmed all six reviewed runtime source files match the active FINAL
  snapshot by SHA-256. AppConfig.h has intentionally preserved local overrides.
- Preprocessed the real AppConfig header using existing Arduino fakes:
  155 cases passed, with 15 accepted and 140 rejected as expected. The complete
  case record is in `power_combination_verification.json`.
- Parsed both new Python scripts for valid syntax.
- Generated the PDF from its editable Markdown using ReportLab.
- Rendered all 10 final A4 pages with Poppler and visually inspected every page
  for readable text, complete tables, consistent headers/footers and clean
  section/page transitions. No clipping, overlap or orphan continuation page
  remained after layout repair.
- Extracted PDF text with pypdf; checked page count, five mode names, gateway
  WOR variants and verification counts. Markdown source uses ASCII text.
- Checked Git whitespace errors. Changes are documentation and documentation
  tooling only; no firmware/server runtime or alternate-port changes.

## Not performed for this documentation update

No ARM firmware rebuild, flashing, live broker command, serial/RF wake test,
sensor hardware test or electrical-current measurement. Existing release
build/host-test evidence is under FINAL `Documentation/ReleaseVerification_20261004`.
The reference's bench checklist describes the remaining physical tests.

The matrix normalizes unused radios to NORMAL and checks only active policy
combinations. Preprocessing does not check C++ static assertions or linking;
the timing values used are the valid defaults. An accepted profile is not
proof of correct board wiring or compatible real-radio wake behavior.
