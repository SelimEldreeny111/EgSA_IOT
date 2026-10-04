# WIOT power-mode reference

The [editable reference](WIOT_Power_Modes_Reference.md) and
[printable PDF](output/pdf/WIOT_Power_Modes_Reference.pdf) describe the current
Arduino STM32 firmware's five power profiles, all 15 practical combinations,
rejected pairings, pins, timings, command behavior and bench acceptance tests.
The baseline is firmware commit `48e5e4b`. No firmware settings are changed.

The scripts use Python 3.10+; PDF generation requires `reportlab`. The guard
checker uses `g++` and existing Arduino fakes. Run from this repository root:

```powershell
python Documentation/PowerModes/verify_power_combinations.py --output Documentation/PowerModes/power_combination_verification.json
python Documentation/PowerModes/render_reference.py
```

Pass `--compiler <absolute-path-to-g++>` when needed. The checker preprocesses
the real header: 155 combinations, 15 accepted and 140 rejected as expected.
It is not an ARM compilation, hardware test or electrical-current measurement.

To visually validate a regenerated PDF, use Poppler:

```powershell
pdftoppm -r 110 -png Documentation/PowerModes/output/pdf/WIOT_Power_Modes_Reference.pdf <temporary-preview-prefix>
```

Review every page for wrapping, table clipping and page breaks. The delivered
PDF was rendered and visually reviewed; previews are not release files.

The source matrix normalizes unused radio policies to NORMAL. A powered but
unselected physical modem is not shut down by those macros. Gateway LoRa and
the selected IP modem are both active and must remain NORMAL; gateway WOR_TX
is a transmission option, not a gateway sleep policy.
