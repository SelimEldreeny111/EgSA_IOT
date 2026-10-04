# Server Phase 1 verification

4 October 2026. Baseline: `24b538846340d4d59c495b16004dd818d46f5e5f`.
Branch: `feature/2026-10-04-server-validation-phase1`.

The initial 15 targeted regression methods were added and run before runtime
fixes. They failed on the baseline for log/role isolation, filename aliasing,
topic routing, numeric validation, headers and subscription readiness, including
missing SUBACK handling. Tests were then expanded to 27 new methods covering
legacy preservation, mixed-owner rejection, timeout/multiple SUBACK, role-specific
dashboard controls, API input, company switching, broadcast echo, reverse flow
and actual firmware rate units (milliseconds in Telemetry, seconds in commands).

| Verification | Result / scope |
| --- | --- |
| Server Python regression suite | 78 passed: previous 51 plus 27 new methods; subtests include invalid topics/measurements/API values. Isolated temporary DBs and fake MQTT only. |
| Simulator Python suites | All existing 54 passed (24 + 20 + 10). Simulator implementation unchanged. |
| Release/protobuf contract | All 6 passed; field numbers/descriptors unchanged. |
| JavaScript | Four suites passed: sensor rendering, WAKE correlation, valve semantics and new safe-text/HTML suite. Actual log/user/popup functions and browser key purge exercised with DOM fixtures. |
| Node host suites | All seven passed: valve, MQTT priority, network recovery, WDT counter, sensor availability, RTC/Supmea, remote wake. Includes 39 policy and 8 valve configuration guards. |
| Python/JS syntax and Git whitespace | Passed through actual module imports, Node syntax check and git diff --check. |
| Real final-folder tenant preflight | Read-only: safe_to_start=true, no collision/ownership issue. No migrations or database writes. |

Full development and final-folder rerun evidence is copied beside this report in
the final copy's `Documentation/Validation/Phase1Evidence_20261004` directory.
The final delivery metadata records the commit, backup and private-data checks.
Evidence logs are local deliverables, not secret-bearing runtime logs in Git.

No fresh ARM build/Doxygen regeneration is required for this server-only change;
all node source/schema/configuration remains byte-unchanged. The preceding valve
release's 13 ARM profiles and zero-warning Doxygen remain baseline evidence,
not new firmware build results for this phase.

Limitations: no physical node/modem/valve tests, live broker/ACL/TLS test, full
interactive-browser rendering test, load/soak test or production migration.
The UI tests are DOM fixtures, not a claim of full browser acceptance. Existing
compiler/vendor warnings are not suppressed. The network subscription tests use
mock Paho callbacks, including rejection, unknown MID, timeout and disconnect.

See [operator guide and remaining phases](SERVER_PHASE1_USER_GUIDE.md).
