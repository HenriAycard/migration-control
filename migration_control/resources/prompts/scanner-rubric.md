# Rubric — whole-estate impact report

Grade the deliverables in /mnt/session/outputs/ ($deliverables). Each criterion is pass/fail.

1. **Full, sourced inventory.** Every component of every module ($module_list) appears with its current version → latest official stable version, each with a link to an official source. Every database or runtime that is behind its latest security patch or end of life has an explicit ALERT.
2. **Sourced CVEs.** Every CVE listed has its ID, severity (CVSS), fixed-in version and a link to NVD / a vendor or GitHub advisory. Any claim that cannot be sourced is tagged UNVERIFIED. No CVE is invented.
3. **Code-located impact.** Every major upgrade the report recommends lists the breaking changes that actually affect this code, each with a `file:line` reference that exists. A generic list of release notes does not pass.
4. **Cross-module dependencies.** The report identifies how modules constrain each other$dependency_minimum, and states the migration order these impose.
5. **Proven by a real build.** For every module with a build, a build on target versions was actually attempted in the sandbox. Real error output is quoted and each error is linked to an impact item, or the report states exactly why a build could not be attempted.
6. **Delta and consistency.** The report opens with a "New since last scan" section (on the first run, it says this run is the baseline). impact-report.json validates against the JSON Schema given in the task (schema_version "1.0", no extra or missing fields) and matches impact-report.md (same components, versions and CVE IDs).
7. **One-page summary for approvers.** impact-summary.md exists, fits on one page (about 60 lines or fewer), and contains: a one-line verdict, the top new items since last scan, the top 5 alerts with their fix, the decisions approvers must make, the migration order, and severity counts. Every alert and count in it matches impact-report.md.
$xlsx_criterion