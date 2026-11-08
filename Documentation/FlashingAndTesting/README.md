# STM32 flashing and testing

[Open the Word operator manual](WIOT_STM32_Flashing_and_Test_Manual_V1.0.docx)
or [read the Markdown edition](WIOT_STM32_Flashing_and_Test_Manual_V1.0.md).

The manual covers five board arrangements through six labelled profiles,
including a SIM or Wi-Fi gateway alternative. It includes Arduino IDE and
SWD programming, programmer recovery, server and simulator preparation,
and twenty test groups for the implemented features.

The source baseline is `9800acc33a5654aff64c4d3ee858292a0c83270f`.
The manual's sample identities are Wi-Fi node 1, SIM node 4, LoRa nodes 2 and 3,
and gateway build identity 100. Assign deployment identities before building.
The initial communication test uses NORMAL mode with sensor polling and the
valve disabled. Later sections enable each required feature explicitly.

## Regeneration

Run build_manual.py with the bundled Python runtime. Refresh the contents and
page fields with Microsoft Word, export a QA PDF and render the pages using
the documents skill. Inspect page images before publishing a revised edition.
Temporary PDFs and page images belong under the ignored tmp directory.

The listed tests are operator procedures. Record hardware results using the
manual's test record. The document does not supply completed bench results.
