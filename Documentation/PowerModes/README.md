# WIOT power-mode reference

29 October bench update: LoRa WOR using UART_RX wake reached the Stop-request
path and the user reported approximately **9 mA**, versus the earlier approximately
42-mA unsuccessful sleep attempt. See the [dated bench record and remaining
tests](../Validation/LORA_WOR_9MA_BENCH_RESULT_20261029.md) and the
[current RX wake guide](../../Node/IoT_Node_Encrypted/LORA_WOR_RX_WAKE_GUIDE.md).
The historical reference/PDF below has not been regenerated for this result.

5 October update: REMOTE_WAKE defaults to independent SRATE/STRAN scheduling.
See [new remote policy and tests](../../Node/IoT_Node_Encrypted/REMOTE_WAKE_APP_SCHEDULE_GUIDE.md).
The dated 4 October reference/PDF below describe the legacy fixed-interval
remote policy (APP_REMOTE_WAKE_USE_APP_SCHEDULE=false); all mode combinations
remain unchanged. The PDF has not been regenerated for this scheduling update.

The [editable reference](WIOT_Power_Modes_Reference.md) and
[printable PDF](output/pdf/WIOT_Power_Modes_Reference.pdf) describe the 4 October
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
