Run this scan of the whole estate, as of today.

The estate has $module_count modules. Set them all up side by side under /workspace/ before anything else:

$module_setup

Treat these refs as what is deployed in production today. Do not upgrade anything in place outside your sandbox; experiments on target versions happen on throwaway copies inside the sandbox.

Deliverables in /mnt/session/outputs/:

- impact-summary.md — ONE page for tech leads and security approvers (max ~60 lines), written last, from the full report:
  1. Verdict in one line (how far the estate is from the target)
  2. New since last scan (top items only)
  3. Top 5 alerts, each: component, why it matters, the fix, link to its section in impact-report.md
  4. Decisions needed from approvers (e.g. target versions, intermediate steps, patch windows)
  5. Recommended migration order (one line per step)
  6. Counts: components scanned, outdated, CVEs by severity, builds attempted/passed
$xlsx_deliverable
- impact-report.md — sections, in this order:
  1. New since last scan (read /mnt/memory/; on the first run, state that this run is the baseline)
  2. Alerts (anything critical: CVSS >= 9, database or runtime behind the latest security patch, end-of-life runtimes)
  3. Inventory table: module | component | current | latest official | latest security patch | source
  4. CVEs table: component | CVE ID | CVSS | fixed in | link
  5. Upgrade impact per module: target version, mandatory intermediate steps, breaking changes with file:line, build attempt result with quoted errors
  6. Cross-module dependencies and the migration order they impose
- impact-report.json — same content, and it MUST validate against this JSON Schema (draft 2020-12). Validate it before finishing (`pip install jsonschema`; Draft202012Validator) and fix every error. Use the same component_key for a product in every section and in every scan; one alert per component_key.$toolchain_note

$schema

Finally, update the scan state in /mnt/memory/ as described in your instructions, keyed by component_key (if the previous state uses other keys, map them once and rewrite the state in the new shape).
