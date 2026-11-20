# WIOT water planning and recovery

The **Water Planning** tab brings together per-line water budgets, soil moisture
advisory and recovery of retained samples after a reporting gap. All three run
on the web server with the existing node and gateway firmware.

## Configure a field plan

1. Restart `server_web.py` from the existing WIOT server directory. The server
   migrates existing SQLite databases in place when it opens them.
2. Sign in as an administrator, select the company and region, and open
   **Water Planning → Configure a field plan**. Enter the node ID, line name,
   and its normal **Status interval** in seconds.
3. Set the **Node time zone** to the firmware's calendar zone, usually
   `Africa/Cairo`. For meter-native totals, also align the meter's calendar.
4. Configure the budgets, soil advisory, or archive backfill you want for
   this node. Enter blank budget fields to leave those periods unbudgeted.
   Choose **Disabled** to leave soil advice off. Backfill is opt-in per node.

Administrators can edit settings from the line's **Edit** button. Monitor
accounts can read the results for their permitted company and region.
Back up `water_operations.db`, `flash_archive.db`, `command_lifecycle.db`, and
the existing tenant and main databases together to retain settings, history,
and recovery progress.

## Release B · Water budgets

Select the TUF or Supmea meter and the flow sensor ID carried in its report.
Enter targets in m³ per day, month, or year. The warning percentage is shared
across the three targets. Each comparison uses one reported period total for
the selected meter. Repeated Status reports and simultaneous readings from a
second meter leave that amount unchanged.

The table shows the reported volume, target, remaining allowance, and the
source and quality of the total. It gives a warning when the configured
percentage is reached, and shows **At or over budget** when use meets the
target. A confirmed zero is valid. Missing, stale, untrusted or partial totals
have their own conditions. Data from before this upgrade can lack sample
provenance, so wait for a new trusted report before using the budget for an
operating decision.

Month and year estimates extrapolate the current usage rate over the full
calendar period after at least two elapsed days. They require a fresh, valid
total. A seasonal or intermittent water schedule may differ from the estimate.

## Release C · Irrigation advisory

Select **HNDA** or **Sondas** and set dry and wet thresholds in the percent
units used by the installed probe. Verify thresholds against the soil and crop
at the site. Advice checks two distinct, valid readings with trusted timestamps
within three Status intervals. It reports the latest moisture and change in
percentage points per hour. A crossing remains **Waiting for confirmation**
until two readings agree. A missing sensor, stale sample, or untrusted clock
withholds advice.

The dry advisory asks the operator to review field conditions and shows when
a configured water budget is already reached. Irrigation decisions and valve
commands remain with the operator.

## Release D · Automatic archive backfill

When Status resumes after a gap of at least three configured reporting
intervals, an enabled plan queues `FLASH_STATUS` for a subsequent valid Status
window. The server checks the correlated reply for trusted time, flash readiness,
retention deadline, and estimated record count. If eligible, it queues
`FLASH_TODAY` scoped to that node and generation. Operator commands take
priority in the existing queue.

- Automatic recovery works on the current retained node day. Earlier-day or
  erased samples are outside the existing firmware's download window.
- The flash record threshold is checked before download. Samples committed
  between the probe and download may increase the actual total. If the probe
  exceeds the threshold, use the existing manual Flash Memory controls.
- The scheduler works on one automatic recovery at a time. It applies a
  four-hour cooldown per node after a completed or exhausted recovery and can
  retry a transient failure once after five minutes when time allows. A
  same-day, same-generation retry resumes after the verified saved prefix.
- Pausing backfill withdraws queued automatic requests. An already-published
  request may finish. Automatic requests are limited to the two read commands.
- Every history application ACK follows the existing durable archive commit.
  Recovered records keep their generation, sequence, and original sample
  time. The table shows the count inside the report gap separately from the
  transfer total. View the records in **Flash Memory** or download their CSV.
  Live charts, water alerts, and period totals use their normal live sources.

## Bench acceptance

| Release | Test | Expected result |
| --- | --- | --- |
| B | Configure a 100 m³ daily budget with an 80% warning. Send fresh valid day totals of 75, 80 and 100 m³. Repeat one report. | The condition advances from within budget to near limit to at or over budget. The repeated cumulative total leaves usage unchanged. When the local date changes, the previous day's total is withheld from the new day. |
| C | Configure dry at 20% and wet at 70% for the chosen probe. Send two distinct valid measurements of 19% and 18%, then test with a disconnected probe. | Two readings produce a dry advisory. A subsequent invalid reading shows sensor data unavailable and withholds advice. |
| D | On a test node with working, retained flash and trusted RTC, enable recovery. Establish a normal reporting baseline, interrupt delivery to the server for at least three Status intervals while local sampling continues, then restore delivery. Start with a small archive that is under the configured threshold. | The next report windows allow a flash probe and download. The archive records retain original sample times and the table shows how many fall inside the gap. Duplicate frames leave one record per generation and sequence. |
| D | With a test transfer in progress, interrupt delivery after the server commits some records, then recover before the node day and flash generation change. | The existing history protocol retries unacknowledged frames. If that transfer ends with a transient error, the bounded scheduler retry resumes after the verified prefix. |

The automated suite can be run from the project root with
`powershell -NoProfile -ExecutionPolicy Bypass -File Validate-Release.ps1 -UseFactoryConfigurationFixture`.
