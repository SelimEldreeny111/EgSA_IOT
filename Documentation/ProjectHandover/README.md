# WIOT project handover

Open [the handover index](index.html) from this folder in the final WIOT working copy. It links the project implementation, editable design and flowcharts, flashing manual, verification evidence and illustrated walkthrough.

- [System design implementation and test report](WIOT_System_Design_Implementation_and_Test_Report.docx)
- [Flashing and test manual](../FlashingAndTesting/WIOT_STM32_Flashing_and_Test_Manual_V1.0.docx)
- [Interactive flowcharts](../Flowcharts/WIOT_Project_Flowcharts.html) and [editable PowerPoint](../Flowcharts/output/pptx/WIOT_Project_Flowcharts_Editable_20261107.pptx)
- [Verification results](VERIFICATION.md)
- [Narrated walkthrough](WIOT_System_Walkthrough.mp4) and [transcript](WIOT_System_Walkthrough_Transcript.md)

The video includes English narration and captions. The repository carries the storyboard, caption and chapter files, transcript and render scripts. Rebuild it with the bundled Python runtime, Pillow, Windows SAPI and FFmpeg.

```powershell
python Documentation/ProjectHandover/build_walkthrough.py
python Documentation/ProjectHandover/build_report.py
```

Refresh the generated report's page fields and export a QA PDF with Documentation/NodeSoftwareDesign/refresh_word.ps1. The report uses the existing system overview artwork and the verified results in results.json.
