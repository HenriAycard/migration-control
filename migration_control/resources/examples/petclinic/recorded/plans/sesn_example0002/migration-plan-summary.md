# Migration plan - approver summary (one page)

**Estate:** petclinic-rest v1.5.2, petclinic-angular 22935fc0, petclinic-infra (tarball sha256 1832fad9…). **Source:** impact-report.json schema 1.0, scan 2026-09-24, session sesn_example0001. The report verdict is RED: 164/164 components outdated, 24 EOL, 332 production CVEs (53 critical), Oracle 19.3 with no RU.
**Plan date:** 2026-09-24. Effort is sized S/M/L/XL only; the plan sets no dates. The plan was built and tested only; nothing was pushed and no PR was opened. Details: `migration-plan.md` / `migration-plan.json` (schema-valid).

## Waves in order

| # | Wave | Depends | Approvers | Risk / Effort | Status (evidence) |
|---|---|---|---|---|---|
| 1 | Oracle DB 19c: RU 19.32 + OJVM 19.32 + Aug/Sep 2026 CSPU (most urgent: 5 CRITICAL DB CVEs) | - | dba, security, platform-ops | medium / M | NOT_PROVABLE_IN_SANDBOX (X01) |
| 2 | Ops health check: Python 3.6.8 -> 3.14.7, latest libs, cx_Oracle -> python-oracledb | - | platform-ops, security, tech-lead | low / S | **PARTIALLY_PROVEN**: all sandbox gates PASS (P03-P16); live-Oracle gate open |
| 3 | Safety net: REST contract + UI smoke tests; Maven Wrapper 3.3.3 -> 3.9.16; remove jcenter | - | tech-lead, security | low / M | PARTIALLY_PROVEN (W3-P01/P02: 169/169 tests, 0 jcenter) |
| 4 | Backend: Boot 1.5.2 -> 2.7.18 -> 3.5.16 -> **4.1.1** (2.7/3.5 transit, not deployed) + Temurin 25 app server + Tomcat 11.0.26 + ojdbc17 + OracleDialect, ONE release, Jackson 2 bridge | 1, 3 | tech-lead, security, dba, platform-ops | high / XL | PARTIALLY_PROVEN (B12, B14, R05, R09; tests B13 and Oracle path open) |
| 5 | Front-end: Angular 6.1.6 -> 22.2.0 one major at a time, Node 24.21.0, Bootstrap 5 | 3, 4 | tech-lead, security | high / XL | PARTIALLY_PROVEN (B28, B30, R12; per-major path, tests, audit open) |
| 6 | Backend: port serializers to Jackson 3, drop spring-boot-jackson2 | 4, 5 | tech-lead, security | medium / M | UNPROVEN |
| 7 | Oracle Linux 7.6 -> 9/10 on petclinic-db01 (new host + switchover) | 1 | dba, platform-ops, security | high / L | NOT_PROVABLE_IN_SANDBOX (X01) |

Waves 1-3 can start in parallel. No wave depends on a later one. All 46 outdated production component_keys are covered exactly once (0 uncovered, 0 deferred). Each wave has measurable entry and exit gates, and each exit-gate set requires build green, the same 169 tests, an unchanged REST contract and a CVE count of 0 for the wave's components. Each wave also has a rollback that keeps the previous artifacts side by side.

## Blocking decisions (owner -> blocks)

- **D5** DB patch window with OJVM downtime; stay on 19c LTR (dba + security -> W1). *Recommend: approve first.*
- **D11 (new)** The literal `${ORACLE_RO_PASSWORD}` in healthcheck.yaml:5 is not expanded by the script. Confirm how production substitutes it (platform-ops -> W2 rollout gate G9).
- **D7** Make the UI smoke test a release gate (tech-lead + security -> W3, W5). *Recommend: yes. In R10 a green build shipped an empty UI.*
- **D1** Java 25 (Temurin 25.0.4.1) · **D2** Boot path via non-deployed 2.7/3.5 · **D3** Tomcat 11.0.26 override (mandatory) and other overrides · **D4** temporary Jackson 2 bridge and the Content-Type change to `application/json` (tech-lead + security -> W4; D3 also blocks W6).
- **D9 (new)** Oracle profile: how the datasource URL is injected, IDENTITY columns vs the sequence-only DDL, and the missing users/roles tables (dba + tech-lead -> W4).
- **D6** Upgrade Angular one major at a time; keep Eager change detection + zone.js; Bootstrap 5; moment (tech-lead -> W5). **D8** OL7 Extended Support vs migration (platform-ops + dba -> W7).
- **D10 (new, optional)** Interim patch of the app-server JDK from 8u161 to Temurin 8u504. The report lists 8u504 as fixing all 32 JDK CVEs, and the current code passes 169/169 tests on it (P10).

## What was proven, and how

- **Proven wave:** Wave 2, the first wave that changes code (Wave 1 is an operational DB patch). Exactly its 11 edits in 3 files were applied to a throwaway copy of the pinned petclinic-infra and saved as `wave-2.patch`. The patch passes `git apply --check` on a fresh extraction, both inside the directory and from its parent with `--directory` (P13). It rolls back byte-for-byte (P14).
- **Gates, all re-run on a tree built only from tarball + patch (P15):**
  - pip install on CPython 3.14.7 exits 0.
  - 21/21 offline checks pass: exact pins, `safe_load` rejects `!!python` tags, keyword `oracledb.connect`, `collections.abc`.
  - python-oracledb runs in Thin mode with no Oracle Client.
  - `api_counts` against the current v1.5.2 backend on JDK 8u504 returns `{'owners': 10, 'vets': 6}`, the same REST contract.
  - pip-audit (OSV) finds 0 vulnerabilities in the pins and in all transitive packages.
- **Negative controls:** the as-is pins fail to install on 3.14 (P03). The as-is script fails with the new libraries (P16). The as-is pins report CVEs (P09). The Maven CVE tool reports 225 advisories on 1.5.2 (T01).
- **Still open for Wave 2 (why it is not PROVEN):** W2-G9, the end-to-end health check against Oracle PETCLINIC (API count == DB count). The sandbox has no Oracle database (X01).
- **Supporting baselines:** as-is backend on JDK 8u504 passes 169/169 tests (P10), and its REST contract snapshot was captured (P12). Maven 3.9.16 with no jcenter passes 169/169 tests using an empty local repository (W3-P01).
- **UNVERIFIED:** Oracle MOS patch numbers and certifications, runtime behaviour against Oracle, the PostgreSQL driver version managed by Boot 4.1.1, the springdoc version for Boot 3.5, and the OL9/10 target minor release.

Evidence: `evidence/<id>.log` (every proof command with its output and exit code). Tools: `tools/` (plan generator, schema validator, OSV gate, report CVE lister).
