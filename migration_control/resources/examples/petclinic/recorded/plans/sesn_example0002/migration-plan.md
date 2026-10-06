# Migration plan - Petclinic estate

- **Plan date:** 2026-09-24 (planner run of migration-planner; plan only - nothing was pushed, no PR opened, no repository outside the sandbox modified)
- **Source of truth:** `impact-report.json` schema 1.0, scan date 2026-09-24, scan session `sesn_example0001` (sha256 `415dfc78cee0...3f53121`)
- **Code, pinned exactly as the report describes:** `spring-petclinic-rest` tag `v1.5.2` (`6479aaa4b3b4`), `spring-petclinic-angular` `22935fc04933e4dec3b20bcfb8720f56b09f170d`, `petclinic-infra` from `petclinic-infra.tar.gz` (sha256 `1832fad909c6...94c48c5`) - verified in proof step P00.
- **Report verdict:** RED — far from "latest version, latest patch, no CVEs": 164/164 components outdated, 24 end-of-life, 332 unique CVEs in production scope (53 critical) + 278 in the build toolchain, and the Oracle database is 19.3 with no Release Update (behind the Jul 2026 CPU and Aug/Sep 2026 CSPUs).
- **Machine-readable twin:** `migration-plan.json` (validates against the task schema, Draft 2020-12 + FormatChecker: `python3 tools/validate_plan.py` -> `schema errors: 0`, `invariant failures: 0`). One-page approver view: `migration-plan-summary.md`.

## Conventions

- **Effort** is S/M/L/XL. No calendar durations or migration dates are given anywhere in this plan.
- **Evidence ids:** `Bxx`/`Rxx`/`Sxx`/`X01` are build/run/scan ids from the source report (`builds[]`); `Pxx`, `W3-Pxx`, `T01` are proof steps run by this planner in the sandbox (logs in `evidence/<id>.log`).
- **Status:** PROVEN = every exit gate executed and passed; PARTIALLY_PROVEN = some exit gates executed/passed (report builds or proof steps), others still open; UNPROVEN = no execution evidence; NOT_PROVABLE_IN_SANDBOX = needs systems that do not exist in the sandbox (Oracle DB, MOS patches, production hosts - report X01).
- **impact_ref:** `impacts[].id` of the source report, or `NEW` for items found while planning. Every integer file:line cited below was re-checked against the pinned code (`tools/validate_plan.py` checks existence/range; content was compared line by line during planning).
- **Inventory records:** `petclinic-infra/oracle/db-inventory.yaml` is a DBA-maintained record of the *actual* state. It is updated after a wave is deployed (listed as the last intermediate step of Waves 1, 2, 4, 7) and is deliberately not part of any wave patch.
- **UNVERIFIED** marks anything that could not be verified (MOS patch numbers, OS certification, Oracle runtime behaviour, versions not recorded in the report).

## Wave order and dependencies

| Wave | Title | Depends on | Approvers | Risk | Effort | Status |
|---|---|---|---|---|---|---|
| 1 | Oracle Database 19c security patching on petclinic-db01 (RU 19.32 + OJVM 19.32 + Aug/Sep 2026 CSPU) | - | dba, security, platform-ops | medium | M | **NOT_PROVABLE_IN_SANDBOX** |
| 2 | Ops health check: CPython 3.6.8 -> 3.14.7, latest libraries, cx_Oracle -> python-oracledb (Thin) | - | platform-ops, security, tech-lead | low | S | **PARTIALLY_PROVEN** |
| 3 | Safety net and build toolchain: REST contract + UI smoke tests, Maven Wrapper 3.3.3 -> 3.9.16, remove jcenter | - | tech-lead, security | low | M | **PARTIALLY_PROVEN** |
| 4 | petclinic-rest: Spring Boot 1.5.2 -> 2.7.18 -> 3.5.16 -> 4.1.1 on Temurin 25, with app-server JDK, Tomcat 11.0.26, ojdbc17 and OracleDialect in ONE release (Jackson 2 bridge) | 1, 3 | tech-lead, security, dba, platform-ops | high | XL | **PARTIALLY_PROVEN** |
| 5 | petclinic-angular: Angular 6.1.6 -> 22.2.0 one major at a time, Node 10.10 -> 24.21.0 LTS, Bootstrap 3 -> 5 | 3, 4 | tech-lead, security | high | XL | **PARTIALLY_PROVEN** |
| 6 | petclinic-rest: port custom (de)serializers to Jackson 3 and drop the deprecated spring-boot-jackson2 bridge | 4, 5 | tech-lead, security | medium | M | **UNPROVEN** |
| 7 | Platform: Oracle Linux 7.6 -> 9/10 on petclinic-db01 (dedicated window; 26ai evaluated separately) | 1 | dba, platform-ops, security | high | L | **NOT_PROVABLE_IN_SANDBOX** |

```
W1 Oracle DB patch ───────────────┬──────────────► W7 Oracle Linux 7.6 -> 9/10
W2 Ops script Python 3.14 (indep.)│
W3 Safety net + Maven 3.9.16 ─────┴► W4 Boot 4.1.1 + JDK 25 + ojdbc17 ──► W5 Angular 22 ──► W6 Jackson 3 (drop bridge)
                                           (W5 may be developed in parallel; deployed after W4)
```

Mapping to the report's `migration_order`: step 1 -> W1, step 2 -> W2, steps 3+4 -> W3 (CI JDK and CI Node move with the code in W4/W5 because the current code cannot build on them: B01/B02, B15/B17), steps 5+6+7 -> W4 (5 and 6 are the non-deployed transit gates T1/T2 of W4, so each component_key is covered exactly once), step 8 -> W5, step 9 -> W6, step 10 -> W7. No wave depends on a later wave (checked by `tools/validate_plan.py`). Waves 1, 2 and 3 have no dependencies and can run in parallel; Wave 1 is the most urgent (5 CRITICAL DB CVEs, ALERT-01).

## Cross-module constraints -> where they are enforced

| # | constraint (report `cross_module`) | enforced in |
|---|---|---|
| 1 | **petclinic-angular -> petclinic-rest**: REST contract: base URL http://&lt;host>:9966/petclinic/api/ (environment.prod.ts:25, environment.ts:26) + owners/pets/vets/visits/pettypes/specialties (e.g. owner.service.ts:35); nested owner<->pets JSON and dates "yyyy/MM/dd" (pet-... | W3 contract tests + UI smoke (frozen from v1.5.2); W4 exit gates 'REST contract unchanged' (context path /petclinic/, anonymous, Jackson 2 bridge, CORS) and 'Current Angular 6 UI still works'; W5 UI smoke vs Boot 4 + bridge; W6 contract re-run without bridge |
| 2 | **petclinic-infra (ops/healthcheck.py) -> petclinic-rest**: Same REST contract: healthcheck.yaml:1 -> /petclinic/api/, len() of the JSON lists from /owners and /vets (healthcheck.py:28-29), no credentials. | W2-G8 (api_counts vs current backend, P11); W3 ops contract test; W4 exit gate 'Ops script still works'; W6 exit gate 'UI and ops consumers' |
| 3 | **petclinic-infra (ops/healthcheck.py) -> Oracle DB PETCLINIC**: cx_Oracle 6.4.1 cannot be imported on Python 3.14 (B25); python-oracledb Thin mode needs no Oracle Client and supports Oracle Database 12.1+ (python-oracledb docs), so it works with 19c before and after patching; queries PETCLINIC... | W2 (python-oracledb Thin, works with 19c before and after patching - P07); W1 exit gate 5 (health check after patching); W2-G9 at rollout |
| 4 | **petclinic-rest (oracle profile from petclinic-infra) -> Oracle DB PETCLINIC 19c**: JDBC driver must be listed for DB 19.x in the Oracle interoperability matrix (JDBC 23.x/21.x/19.x; 11.2 not listed) and match the JDK (ojdbc6 = JDK 6-8; ojdbc17 = JDK 17+ incl. 25). Dialect must be Hibernate-7-compatible (OracleDi... | W4 (ojdbc17 23.26.3.0.0 + OracleDialect, oracle-profile.xml:6-13) - depends on W1; W4 exit gate 'Oracle path (staging)' |
| 5 | **petclinic-rest -> petclinic-infra (app-server JDK)**: db-inventory.yaml:13 declares JDK 1.8.0_161 for the WAR; Boot 4.1.1 needs Java 17+ (B09) and runs on Temurin 25.0.4.1 (B14). The app-server JDK must be upgraded in the same release as the Boot 4 WAR; the current WAR is not viable ... | W4 deploys the Boot 4.1.1 WAR and the Temurin 25.0.4.1 app-server JDK in ONE release (intermediate step 4); JDK-only upgrade rejected (B01/B02/R01) |
| 6 | **petclinic-infra (app-server Python) -> petclinic-infra (ops script)**: db-inventory.yaml:14 declares Python 3.6.8 while current requests/urllib3/oracledb require >= 3.10 -> host Python and requirements.txt move together. | W2 moves host Python and requirements.txt together (intermediate step 2; W2-G1) |
| 7 | **petclinic-rest (JPA entities) -> petclinic-infra/oracle/schema.sql**: Entities use IDENTITY generation (BaseEntity.java:34) and the HSQLDB DDL uses IDENTITY columns (initDB.sql:13), but the Oracle DDL uses sequences without identity/triggers and lacks users/roles tables — pre-existing mismatch to fi... | W4 blocking decision D9 + W4 exit gate 'Oracle path (staging)' (IDENTITY vs sequences, users/roles tables) |
| 8 | **petclinic-rest (build/CI) -> build toolchain**: Maven Wrapper 3.3.3 (.mvn/wrapper/maven-wrapper.properties:1) and CI oraclejdk8 (.travis.yml:2) must be upgraded (Maven >= 3.6.3, JDK 17+/25) before or with the Boot 3/4 steps. | W3 (Maven Wrapper 3.9.16 before the Boot steps, W3-P01) and W4 (CI JDK -> Temurin 25 with the code, .travis.yml:2) |
| 9 | **petclinic-angular (build) -> CI Node runtime**: .travis.yml:5 pins Node 10.10; Angular 22.2 requires ^22.22.3 \|\| ^24.15.0 \|\| >=26; the sandbox default Node 22.22.0 is below that floor (Node 24.21.0 used). | W5 (Node 24.21.0 LTS with Angular 22; .travis.yml:5 and :24) |

## Wave 1 - Oracle Database 19c security patching on petclinic-db01 (RU 19.32 + OJVM 19.32 + Aug/Sep 2026 CSPU)

- **Status:** **NOT_PROVABLE_IN_SANDBOX** - evidence: X01
- **Approvers:** dba, security, platform-ops  |  **Risk:** medium  |  **Effort:** M  |  **Depends on:** none
- **Modules:** petclinic-infra

### Targets

| component_key | from | to | report CVEs (current) |
|---|---|---|---|
| `oracle-database` | 19.3.0.0.0, no Release Update applied (db-inventory.yaml:6-7) | 19c RU 19.32 (Jul 2026 CPU) + Aug 2026 CSPU DB patch + Sep 2026 CSPU DB patch; MOS patch numbers UNVERIFIED (login required). Stays on 19c LTR unless decision D5 selects 26ai | 22 |
| `oracle-ojvm` | none applied (db-inventory.yaml:8) | OJVM RU 19.32 matching the DB RU (patch number UNVERIFIED, MOS) | 4 |

### Intermediate steps

1. OPatch / RU prerequisites per the RU readme (UNVERIFIED - MOS login required)
2. Prefer out-of-place patching: clone the 19.3 Oracle home, patch the clone, switch the database to it (keeps the unpatched home for rollback)
3. RU 19.32 (cumulative - intermediate RUs 19.4..19.31 are not required)
4. OJVM RU 19.32 (requires the database in upgrade mode / downtime - decision D5 patch window)
5. Aug 2026 CSPU DB patch
6. Sep 2026 CSPU DB patch
7. datapatch -verbose, then utlrp.sql
8. Follow-up cycle, same procedure and gates: the next quarterly Oracle CPU once published (the report lists the next CPU date; no migration date is set here)
9. Post-deployment record (not a code change, not part of any wave patch): DBA updates petclinic-infra/oracle/db-inventory.yaml:6-8 to the verified patch level

### Changes

_No repository code change in this wave (operational change on the target systems only)._

### Entry gates

| # | check | how (exact command / procedure) | pass criterion |
|---|---|---|---|
| 1 | Decision D5 approved (patch window, stay on 19c) | `Change ticket with DBA + security sign-off` | Ticket approved by dba and security |
| 2 | Full backup restorable | `RMAN> BACKUP DATABASE PLUS ARCHIVELOG; RMAN> RESTORE DATABASE VALIDATE;` | Both commands complete with 0 RMAN- errors |
| 3 | Guaranteed restore point | `SQL> CREATE RESTORE POINT pre_ru1932 GUARANTEE FLASHBACK DATABASE; SELECT name, guarantee_flashback_database FROM v$restore_point WHERE name='PRE_RU1932';` | 1 row, GUARANTEE_FLASHBACK_DATABASE = YES |
| 4 | No patch conflicts | `$ORACLE_HOME/OPatch/opatch prereq CheckConflictAgainstOHWithDetail -ph <each unzipped patch dir>` | Output 'Prereq "checkConflictAgainstOHWithDetail" passed.' for all four patches |
| 5 | OS certification of RU 19.32 on Oracle Linux 7.6 | `MOS certification matrix lookup by DBA (UNVERIFIED in the report)` | Certified = yes, recorded in the ticket; otherwise stop and escalate to decision D8 |
| 6 | Rehearsal on a non-production clone of PETCLINIC | `Run this wave's full procedure and exit gates on the clone` | All exit gates PASS on the clone |
| 7 | Baseline recorded | `SELECT COUNT(*) FROM dba_objects WHERE status='INVALID'; SELECT comp_id,status FROM dba_registry;` | Values recorded in the ticket as N0 / component list |

### Exit gates

| # | check | how (exact command / procedure) | pass criterion |
|---|---|---|---|
| 1 | SQL patches registered | `SELECT patch_id, action, status, description FROM dba_registry_sqlpatch ORDER BY action_time;` | Rows for RU 19.32, OJVM RU 19.32, Aug 2026 CSPU and Sep 2026 CSPU, all ACTION=APPLY and STATUS=SUCCESS; 0 rows with STATUS<>'SUCCESS' |
| 2 | Binary patches installed | `$ORACLE_HOME/OPatch/opatch lspatches` | Lists the 4 patches of this wave |
| 3 | Release level | `SELECT version_full FROM v$instance;` | 19.32.0.0.0 |
| 4 | Dictionary healthy | `@?/rdbms/admin/utlrp.sql; SELECT COUNT(*) FROM dba_objects WHERE status='INVALID'; SELECT comp_id,status FROM dba_registry;` | INVALID count <= N0; every component (incl. JAVAVM) VALID |
| 5 | Application regression (current clients) | `curl -s -o /dev/null -w '%{http_code}' http://petclinic-app01:9966/petclinic/api/owners ; run the nightly ops/healthcheck.py (Wave 2 version if already deployed)` | HTTP 200 and healthcheck exit 0 (api counts == db counts). The current ojdbc6 11.2 client is already an unsupported combination - UNVERIFIED until this gate runs |
| 6 | CVE count for the wave's components = 0 | `python3 tools/report_cves.py impact-report.json oracle-database,oracle-ojvm  (26 CVEs) and tick each fixed_in level against dba_registry_sqlpatch` | All 26 report CVEs have fixed_in <= RU 19.32 + Aug/Sep 2026 CSPU and those patches are STATUS=SUCCESS -> 0 open |
| 7 | Restore point released | `SQL> DROP RESTORE POINT pre_ru1932;  (only after all gates above PASS)` | Statement succeeds |

### Rollback

Before datapatch completes or on any failed exit gate: shut down, switch the instance back to the retained unpatched 19.3 Oracle home (out-of-place patching) and run datapatch from that home to roll back the SQL changes; for OJVM follow the rollback section of the patch readme (UNVERIFIED - MOS). Last resort (data changes after the patch are lost, needs business sign-off): FLASHBACK DATABASE TO RESTORE POINT pre_ru1932; ALTER DATABASE OPEN RESETLOGS. Re-run the entry-gate baseline queries to confirm the pre-patch state.

### Evidence

- `X01` (report, NOT_ATTEMPTED): Oracle Database 19c: apply RU 19.32 / connect ojdbc17 + python-oracledb to a live DB - failed to connect to the docker API at unix:///var/run/docker.sock ... no such file or directory (no Docker daemon); no Oracle DB image/licence in the sandbox; RU/CSPU patches require My Oracle Support credentials; no ne

## Wave 2 - Ops health check: CPython 3.6.8 -> 3.14.7, latest libraries, cx_Oracle -> python-oracledb (Thin)

- **Status:** **PARTIALLY_PROVEN** - evidence: B24, B25, B26, R07, R08, P02, P03, P05, P06, P07, P08, P09, P10, P11, P13, P14, P15, P16
- **Approvers:** platform-ops, security, tech-lead  |  **Risk:** low  |  **Effort:** S  |  **Depends on:** none
- **Modules:** petclinic-infra

### Targets

| component_key | from | to | report CVEs (current) |
|---|---|---|---|
| `python` | 3.6.8 (runtime.txt:1, db-inventory.yaml:14) | 3.14.7 | 0 |
| `requests` | 2.19.1 | 2.34.2 | 5 |
| `urllib3` | 1.23 | 2.8.0 | 11 |
| `pyyaml` | 3.12 | 6.0.3 | 2 |
| `jinja2` | 2.10 | 3.1.6 | 6 |
| `cx-oracle` | cx_Oracle 6.4.1 | python-oracledb (oracledb) 26.0.1, Thin mode | 0 |

### Intermediate steps

1. No mandatory intermediate versions (the new libraries install directly on 3.14.7, B26/P05)
2. platform-ops installs CPython 3.14.7 on petclinic-app01 side by side with 3.6.8 and creates a dedicated venv from ops/requirements.txt; the cron entry is switched to the new venv only after the exit gates pass
3. Post-deployment record (not a code change): DBA updates petclinic-infra/oracle/db-inventory.yaml:14 to python 3.14.7

### Changes

| # | file:line | change | impact_ref |
|---|---|---|---|
| 1 | `petclinic-infra/ops/runtime.txt:1` | Declared runtime python-3.6.8 (EOL) -> python-3.14.7 | IMP-INFRA-PY |
| 2 | `petclinic-infra/ops/requirements.txt:1` | requests==2.19.1 -> requests==2.34.2 (old pins cannot be imported on 3.14, B25) | IMP-INFRA-PY |
| 3 | `petclinic-infra/ops/requirements.txt:2` | urllib3==1.23 -> urllib3==2.8.0 (same breaking change as line 1: 'No module named urllib3.packages.six.moves', B25) | IMP-INFRA-PY |
| 4 | `petclinic-infra/ops/requirements.txt:3` | PyYAML==3.12 -> PyYAML==6.0.3 (3.12 does not build on 3.14, B24/P03) | IMP-INFRA-PY |
| 5 | `petclinic-infra/ops/requirements.txt:4` | cx_Oracle==6.4.1 -> oracledb==26.0.1 (python-oracledb, Thin mode, no Oracle Client) | IMP-INFRA-PY |
| 6 | `petclinic-infra/ops/requirements.txt:5` | Jinja2==2.10 -> Jinja2==3.1.6 | IMP-INFRA-PY |
| 7 | `petclinic-infra/ops/healthcheck.py:7` | import collections -> import collections.abc (needed by the :21 fix) | IMP-INFRA-PY |
| 8 | `petclinic-infra/ops/healthcheck.py:10` | import cx_Oracle -> import oracledb | IMP-INFRA-PY |
| 9 | `petclinic-infra/ops/healthcheck.py:20` | yaml.load(f) -> yaml.safe_load(f) (PyYAML 6 API; closes the CVE-2017-18342/CVE-2020-14343 call pattern) | IMP-INFRA-PY |
| 10 | `petclinic-infra/ops/healthcheck.py:21` | collections.Mapping -> collections.abc.Mapping (removed in Python 3.10) | IMP-INFRA-PY |
| 11 | `petclinic-infra/ops/healthcheck.py:34` | cx_Oracle.connect(user, password, dsn) -> oracledb.connect(user=..., password=..., dsn=...) (keyword-only API) | IMP-INFRA-PY |

### Entry gates

| # | check | how (exact command / procedure) | pass criterion |
|---|---|---|---|
| 1 | Target interpreter available on petclinic-app01 | `/opt/python-3.14.7/bin/python3.14 --version  (sandbox: P02)` | Prints 'Python 3.14.7' |
| 2 | Negative control: as-is pins do not work on 3.14.7 | `python3.14 -m venv v && v/bin/pip install -r ops/requirements.txt (as-is)  (sandbox: P03)` | Install fails (PyYAML 3.12 longintrepr.h) - confirms the wave is needed |
| 3 | Password substitution mechanism known (NEW finding, decision D11) | `Platform-ops documents how '${ORACLE_RO_PASSWORD}' in ops/healthcheck.yaml:5 is substituted in production (the script itself does no environment expansion, neither before nor after this wave)` | Mechanism documented in the change ticket |

### Exit gates

| # | check | how (exact command / procedure) | pass criterion |
|---|---|---|---|
| 1 | W2-G1 install | `python3.14 -m venv /tmp/venv-w2 && /tmp/venv-w2/bin/pip install -r ops/requirements.txt  (P05, P15)` | exit 0; 'Successfully installed ... oracledb-26.0.1 ... requests-2.34.2 urllib3-2.8.0 PyYAML-6.0.3 Jinja2-3.1.6' |
| 2 | W2-G2..G5 exact pins, import, config, DB call shape | `/tmp/venv-w2/bin/python evidence/w2_gate_tests.py offline  (run in petclinic-infra/; P06, P15)` | 21/21 checks PASS, 'SUMMARY: 0 failed check(s)', exit 0 |
| 3 | W2-G6 Thin mode without Oracle Client | `/tmp/venv-w2/bin/python evidence/w2_gate_tests.py thin 127.0.0.1:1/PETCLINIC  (P07)` | DPY-6005 network error and no DPI-1047 (Oracle Client) error; exit 0 |
| 4 | W2-G7 CVE count for the wave's components = 0 | `pip-audit --vulnerability-service osv -r ops/requirements.txt ; pip-audit --vulnerability-service osv --path <venv>/lib/python3.14/site-packages  (P08; negative control P09)` | 'No known vulnerabilities found' for both (pins and all transitive packages); 24/24 report CVEs of these keys closed |
| 5 | W2-G8 REST contract unchanged for the ops script | `/tmp/venv-w2/bin/python evidence/w2_gate_tests.py api http://<backend>:9966/petclinic/api/ <owners> <vets>  (sandbox: v1.5.2 on JDK 8u504, P11/P15)` | api_counts == counts of the current backend (sandbox: {'owners': 10, 'vets': 6}), exit 0 |
| 6 | W2-G9 end-to-end against Oracle PETCLINIC (production/staging only) | `cd petclinic-infra && /opt/petclinic-ops/venv/bin/python ops/healthcheck.py; echo $?` | exit 0 and api == db for owners and vets. NOT PROVABLE IN SANDBOX (no Oracle DB, X01) - to be run by platform-ops at rollout |
| 7 | Patch integrity | `cd petclinic-infra && git apply --check wave-2.patch  (fresh extraction of the pinned tarball; P13)` | exit 0; result byte-identical to the proven tree |

### Rollback

No data or schema change (read-only account). Re-point the cron entry to the retained Python 3.6.8 environment and revert the files with `git apply -R wave-2.patch` (rehearsed in P14: tree byte-identical to the pinned baseline). The old venv is kept until W2-G9 has passed on production.

### Evidence

- `B24` (report, FAIL): pip install pinned PyYAML==3.12 - ext/_yaml.c:49:12: fatal error: longintrepr.h: No such file or directory; ERROR: Failed building wheel for PyYAML
- `B25` (report, FAIL): install the other pinned libs + import - ModuleNotFoundError: No module named 'urllib3.packages.six.moves'; ImportError: cannot import name 'soft_unicode' from 'markupsafe'; ImportError: .../cx_Oracle.cpython-314-x86_64-linux-gnu.so: undefined symbol: PyUnicode
- `B26` (report, PASS): install latest libs (requests 2.34.2, urllib3 2.8.0, PyYAML 6.0.3, oracledb 26.0.1, Jinja2 3.1.6) - 
- `R07` (report, FAIL): run healthcheck.py with latest libs, fixing one error at a time - ModuleNotFoundError: No module named 'cx_Oracle'; TypeError: load() missing 1 required positional argument: 'Loader'; AttributeError: module 'collections' has no attribute 'Mapping'; TypeError: connect() takes from 0 to 
- `R08` (report, PARTIAL): healthcheck.api_counts() against 1.5.2 and three Boot 4 variants - 1.5.2: {'owners': 10, 'vets': 6}; Boot4 props unchanged: JSONDecodeError (char 0); Boot4 Jackson 3: JSONDecodeError (char 29157); Boot4 + jackson2 bridge: {'owners': 11, 'vets': 6}
- `P02` (this run, PASS): Install CPython 3.14.7 (target runtime of Wave 2) - `evidence/P02.log`
- `P03` (this run, PASS): Negative control (entry evidence): pinned AS-IS requirements (baseline commit) on CPython 3.14.7 must FAIL to install (reproduces B24); step passes when the install fails - `evidence/P03.log`
- `P05` (this run, PASS): Exit gate W2-G1: clean venv on CPython 3.14.7, pip install -r ops/requirements.txt exits 0 - `evidence/P05.log`
- `P06` (this run, PASS): Exit gates W2-G2..G5 (offline): exact pins, import on 3.14.7, safe_load, collections.abc, keyword connect, template render, Thin mode - `evidence/P06.log`
- `P07` (this run, PASS): Exit gate W2-G6: python-oracledb Thin mode reaches the network without an Oracle Client (no DB in sandbox, X01) - closed local port - `evidence/P07.log`
- `P08` (this run, PASS): Exit gate W2-G7: known-vulnerability count for the Wave 2 components (pins + full resolved transitive set) = 0 (pip-audit, OSV service) - `evidence/P08.log`
- `P09` (this run, PASS): Negative control for W2-G7: the as-is pins (baseline commit) DO report known vulnerabilities, so the gate discriminates - `evidence/P09.log`
- `P10` (this run, PASS): Baseline of the as-is backend (v1.5.2) with its own toolchain: Maven Wrapper (3.3.3) on JDK 8 (Temurin 8u504, sandbox CA bundle imported into cacerts), full test suite - measures the test count used in later gates - `evidence/P10.log`
- `P11` (this run, PASS): Exit gate W2-G8 (REST contract, cf. R08): healthcheck.api_counts() on CPython 3.14.7 + requests 2.34.2 against the CURRENT backend v1.5.2 WAR running on JDK 8u504 at the production URL shape http://&lt;host>:9966/petclinic/api/ - expect owners=10, vets=6 - `evidence/P11.log`
- `P13` (this run, PASS): Patch applicability: wave-2.patch passes git apply --check on a FRESH extraction of the pinned petclinic-infra.tar.gz (inside the dir and from the parent dir with --directory), applies, and the result is byte-identical to the proven tree - `evidence/P13.log`
- `P14` (this run, PASS): Rollback rehearsal: git apply -R restores the pinned baseline byte-for-byte - `evidence/P14.log`
- `P15` (this run, PASS): Re-run ALL Wave 2 exit gates on a tree produced only from the pinned tarball + wave-2.patch (fresh venv; set -eo pipefail): install, offline checks, Thin mode, api_counts vs v1.5.2 on JDK 8, pip-audit - `evidence/P15.log`
- `P16` (this run, PASS): Negative control for the code fixes: AS-IS ops/healthcheck.py (baseline commit) with the new libraries on 3.14.7 fails (reproduces R07 first error); step passes when it fails - `evidence/P16.log`

**Why PARTIALLY_PROVEN and not PROVEN:** every exit gate that can run without an Oracle database passed on a tree built only from the pinned tarball + `wave-2.patch` (P15: W2-G1, G2-G5, G6, G7, G8, plus patch integrity P13 and rollback P14). W2-G9 (the end-to-end run of `ops/healthcheck.py` against Oracle PETCLINIC, api == db) needs a live Oracle database, which does not exist in the sandbox (report X01); it is the only open gate and must be executed by platform-ops at rollout.

## Wave 3 - Safety net and build toolchain: REST contract + UI smoke tests, Maven Wrapper 3.3.3 -> 3.9.16, remove jcenter

- **Status:** **PARTIALLY_PROVEN** - evidence: B27, R01, P10, P12, W3-P01, W3-P02, T01
- **Approvers:** tech-lead, security  |  **Risk:** low  |  **Effort:** M  |  **Depends on:** none
- **Modules:** petclinic-rest, petclinic-angular, petclinic-infra

### Targets

| component_key | from | to | report CVEs (current) |
|---|---|---|---|
| `apache-maven` | 3.3.3 (Maven Wrapper, maven-wrapper.properties:1) | 3.9.16 | 1 |

### Intermediate steps

1. Freeze the REST contract from the as-is backend (report R01 capture + sandbox capture P12: 7 GETs, status, Content-Type, body) into contract tests shared by petclinic-rest, petclinic-angular and the ops script
2. Add a headless UI smoke test (R09-R12 style) and make it a release gate (decision D7)
3. Maven Wrapper -> 3.9.16 and removal of the jcenter repository (both work with the current Boot 1.5.2 code on JDK 8: W3-P01)
4. CI JDK and CI Node are NOT changed here: the current code does not build on JDK 17+ (B01/B02) and the current Angular 6 toolchain does not build on current Node (B15/B17); they move with Waves 4 and 5

### Changes

| # | file:line | change | impact_ref |
|---|---|---|---|
| 1 | `spring-petclinic-rest/.mvn/wrapper/maven-wrapper.properties:1` | distributionUrl apache-maven 3.3.3 -> 3.9.16 (Boot 4 plugins need Maven >= 3.6.3, B27; 3.3.3 has CVE-2021-26291) | IMP-REST-BOOT4 |
| 2 | `spring-petclinic-rest/pom.xml:38` | Remove the &lt;repositories> block with jcenter (lines 33-40); Maven Central resolves everything (W3-P01 with an empty local repo, 0 jcenter downloads) | IMP-REST-BOOT4 |
| 3 | `spring-petclinic-rest/src/test/java/org/springframework/samples/petclinic/contract/RestContractTests.java:new file` | Add REST contract tests: 7 GETs (owners, owners/1, pets, vets, visits, pettypes, specialties) JSON-equal to the frozen 1.5.2 snapshot, dates 'yyyy/MM/dd', context path /petclinic/, anonymous access, POST /api/owners -> 201 | NEW |
| 4 | `spring-petclinic-angular/e2e/smoke/owners.smoke.spec.ts:new file` | Add a headless UI smoke test: owners list rows == GET /owners count, owner 1 page shows '2010/09/07' (R09/R12 criteria) | NEW |
| 5 | `petclinic-infra/ops/test_contract.py:new file` | Add the ops-script contract check (healthcheck.api_counts over /owners and /vets at the URL of healthcheck.yaml:1, JSON lists, no credentials) as a CI test of petclinic-infra (same logic as evidence/w2_gate_tests.py 'api' mode) | NEW |

### Entry gates

| # | check | how (exact command / procedure) | pass criterion |
|---|---|---|---|
| 1 | As-is baseline measured | `JAVA_HOME=<JDK 8u504> ./mvnw -B clean package  (P10)` | BUILD SUCCESS, 'Tests run: 169, Failures: 0, Errors: 0, Skipped: 0' |
| 2 | Contract snapshot captured | `curl the 7 GETs against v1.5.2 (P12; report R01 evidence/contract-asis-1.5.2/)` | 7 x HTTP 200 application/json;charset=UTF-8; owner 1 pet birthDate '2010/09/07' |

### Exit gates

| # | check | how (exact command / procedure) | pass criterion |
|---|---|---|---|
| 1 | Wrapper version | `./mvnw -v` | First line 'Apache Maven 3.9.16' |
| 2 | Build green from Maven Central only | `JAVA_HOME=<JDK 8> ./mvnw -B -Dmaven.repo.local=$(mktemp -d) clean package \| tee build.log  (W3-P01)` | BUILD SUCCESS; 'Tests run: 169, Failures: 0, Errors: 0, Skipped: 0' (= baseline P10) |
| 3 | No jcenter | `grep -cE '(Downloading\|Downloaded) from jcenter' build.log ; grep -c jcenter pom.xml  (W3-P02)` | 0 and 0 |
| 4 | Contract tests green on the current backend | `./mvnw -B -Dtest=RestContractTests test` | All contract tests pass (7 GET + 1 POST), 0 failures |
| 5 | UI smoke green on the current front-end + backend | `npx playwright test e2e/smoke (Angular 6 bundle vs v1.5.2)` | All smoke checks pass; owner rows == GET /owners count |
| 6 | CVE count for the wave's components = 0 | `curl -s -X POST https://api.osv.dev/v1/query -d '{"package":{"name":"org.apache.maven:maven-core","ecosystem":"Maven"},"version":"3.9.16"}'  (W3-P02)` | Response {} (0 advisories); 3.3.3 returns GHSA-2f88-5hg8-9x2x (negative control) |

### Rollback

Build-time only, no runtime artifact changes: git revert of the wave commits restores maven-wrapper.properties and the &lt;repositories> block; contract/smoke tests are additive and can be disabled without affecting the product.

### Evidence

- `B27` (report, FAIL): Boot 4.1.1 variant built with the repo's ./mvnw (Maven 3.3.3) - The plugin org.apache.maven.plugins:maven-resources-plugin:3.5.0 requires Maven version 3.6.3
- `R01` (report, PARTIAL): run as-is WAR, capture REST contract (7 GETs) + POST + healthcheck - GET x7 -> 200 application/json;charset=UTF-8; POST /petclinic/api/owners -> 400 {"className":"javax.validation.ValidationException","exMessage":"HV000041: Call to TraversableResolver.isReachable() threw an exception."}
- `P10` (this run, PASS): Baseline of the as-is backend (v1.5.2) with its own toolchain: Maven Wrapper (3.3.3) on JDK 8 (Temurin 8u504, sandbox CA bundle imported into cacerts), full test suite - measures the test count used in later gates - `evidence/P10.log`
- `P12` (this run, PASS): Supporting (Wave 3 input): capture the as-is REST contract of v1.5.2 on JDK 8 - 7 GETs, status, Content-Type, body sha256 - `evidence/P12.log`
- `W3-P01` (this run, PASS): Supporting evidence for Wave 3 (partial): Maven Wrapper -> 3.9.16 + jcenter repository removed (pom.xml:33-40), JDK 8u504, EMPTY local repo (-Dmaven.repo.local=/tmp/m2-w3) so every artifact must resolve from Maven Central; full test suite - `evidence/W3-P01.log`
- `W3-P02` (this run, PASS): Supporting evidence for Wave 3: verify W3-P01 resolved nothing from jcenter and used Maven 3.9.16; OSV check of the Maven distribution (CVE-2021-26291 fixed in 3.8.1+) - `evidence/W3-P02.log`
- `T01` (this run, PASS): Gate-tool validation (negative control): tools/osv_maven.py on the AS-IS v1.5.2 dependency tree must report advisories (exit non-zero); step passes when it does - `evidence/T01.log`

## Wave 4 - petclinic-rest: Spring Boot 1.5.2 -> 2.7.18 -> 3.5.16 -> 4.1.1 on Temurin 25, with app-server JDK, Tomcat 11.0.26, ojdbc17 and OracleDialect in ONE release (Jackson 2 bridge)

- **Status:** **PARTIALLY_PROVEN** - evidence: B01, B02, B03, B04, B05, B06, B07, B08, B09, B10, B11, B12, B13, B14, B27, R01, R03, R04, R05, R06, R08, R09, S01, P10, P12, T01
- **Approvers:** tech-lead, security, dba, platform-ops  |  **Risk:** high  |  **Effort:** XL  |  **Depends on:** Wave 1, Wave 3
- **Modules:** petclinic-rest, petclinic-infra

### Targets

| component_key | from | to | report CVEs (current) |
|---|---|---|---|
| `spring-boot` | 1.5.2.RELEASE | 4.1.1 (via non-deployed transit steps 2.7.18 and 3.5.16) | 6 |
| `spring-framework` | 4.3.7.RELEASE | 7.0.9 (Boot 4.1.1-managed) | 36 |
| `spring-security` | 4.2.2.RELEASE | 7.1.1 (Boot 4.1.1-managed) | 12 |
| `spring-data-jpa` | 1.11.1.RELEASE | 4.1.1 (Boot 4.1.1-managed) | 2 |
| `spring-data-commons` | 1.13.1.RELEASE | 4.1.1 (Boot 4.1.1-managed) | 6 |
| `spring-retry` | 1.2.0.RELEASE (would resolve 1.0.3.RELEASE in the naive Boot 4 tree, S01) | removed from the tree together with spring-data-jdbc-core; 2.0.13 if a direct use is ever needed | 1 |
| `spring-data-jdbc-ext` | spring-data-jdbc-core 1.2.1.RELEASE (abandoned) | removed (extractor re-implemented in-repo) | 0 |
| `apache-tomcat` | 8.5.11 | 11.0.26 (&lt;tomcat.version> override of the Boot-managed 11.0.24, mandatory - 3 CRITICAL CVEs, decision D3) | 58 |
| `jackson-core` | 2.8.7 | Boot 4.1.1-managed Jackson 2 line via spring-boot-jackson2 (2.21.5 per report), or 2.22.3 if decision D3 overrides | 3 |
| `hibernate-orm` | 5.0.12.Final | 7.4.5.Final (Boot-managed) or 7.4.10.Final (decision D3) | 2 |
| `hibernate-validator` | 5.3.4.Final | 9.1.3.Final (Boot-managed) or 9.1.4.Final (decision D3) | 4 |
| `dom4j` | 1.6.1 | removed (not a dependency of Hibernate 6+) | 2 |
| `logback` | 1.1.11 | 1.5.38 (Boot-managed) or 1.6.3 (decision D3) | 9 |
| `snakeyaml` | 1.17 | 2.6 (Boot-managed; no advisory in S01) - latest 2.7 | 8 |
| `springfox` | 2.6.1 | springdoc-openapi-starter-webmvc-ui 3.1.1 | 1 |
| `guava` | 18.0 (transitive of springfox) | removed from the tree with springfox (gate: dependency:tree has 0 guava 18.0) | 3 |
| `hsqldb` | 2.3.3 | 2.7.3 (Boot-managed; no advisory in S01) - latest 2.7.4 | 1 |
| `mysql-connector-j` | mysql:mysql-connector-java 5.1.41 | com.mysql:mysql-connector-j 9.7.0 (Boot-managed) - latest 26.7.0 | 6 |
| `postgresql-jdbc` | 9.4.1212.jre7 | Boot 4.1.1-managed version (exact version not recorded in the report: UNVERIFIED) - latest 42.7.13 | 4 |
| `jaxb-api` | javax.xml.bind:jaxb-api 2.3.0 | jakarta.xml.bind:jakarta.xml.bind-api (latest 4.0.5) | 0 |
| `aspectj` | 1.8.9 (spring-boot-starter-aop) | spring-boot-starter-aspectj (AspectJ latest 1.9.25.1) | 0 |
| `jdk` | JDK 1.8.0_161 (petclinic-app01), java.version 1.8, CI oraclejdk8 | Temurin 25.0.4.1 on petclinic-app01, java.version 25, CI Temurin 25 (decision D1) | 32 |
| `ojdbc` | com.oracle:ojdbc6 11.2.0.4 | com.oracle.database.jdbc:ojdbc17 23.26.3.0.0 | 3 |
| `hibernate-oracle-dialect` | org.hibernate.dialect.Oracle10gDialect | org.hibernate.dialect.OracleDialect (auto-detected; spring.jpa.database-platform removed) | 0 |
| `junit` | 4.12 | JUnit Jupiter 6.1.3 (via spring-boot-starter-test 4.1.1) | 1 |
| `mockito` | 1.10.19 | Boot 4.1.1-managed Mockito 5.x (latest 5.24.0) | 0 |
| `assertj` | 2.6.0 | Boot 4.1.1-managed AssertJ 3.x (latest 3.27.7) | 1 |
| `json-path` | 2.2.0 | Boot 4.1.1-managed (latest 3.0.0) | 1 |
| `json-smart` | 2.2.1 | Boot 4.1.1-managed (latest 2.6.0) | 2 |

### Intermediate steps

1. T1 - transit, NOT deployed: Spring Boot 2.7.18 on JDK 17 (last 2.x; the Boot 3.0 guide requires 2.7 first): parent 2.7.18, com.mysql:mysql-connector-j, spring-boot-starter-validation, org.springframework.boot.web.servlet.support, remove the orm.hibernate3 import, server.servlet.context-path, spring.sql.init.*, explicit permitAll security config replacing security.ignored. Gate T1 below. Status: UNPROVEN (B05 drop-in FAIL only)
2. T2 - transit, NOT deployed (3.5.x OSS ended): Spring Boot 3.5.16 on JDK 17: javax -> jakarta, WebSecurityConfigurerAdapter -> SecurityFilterChain + @EnableMethodSecurity, springfox -> springdoc (springdoc version for Boot 3.5 UNVERIFIED in the report), JUnit 4 -> JUnit Jupiter. Gate T2 below. Status: UNPROVEN (B06/B07 FAIL - partial)
3. T3 - release: Spring Boot 4.1.1 on Temurin 25.0.4.1: spring-boot-starter-aspectj, MediaType.APPLICATION_JSON_VALUE (33 usages), @MockitoBean, spring-boot-jackson2 + preferred-json-mapper=jackson2, &lt;tomcat.version>11.0.26&lt;/tomcat.version>, java.version 25, spring-data-jdbc-core removed, springdoc 3.1.1, jakarta.xml.bind-api (proven variant B12/B14/R05)
4. Deploy T3 as ONE release: Boot 4.1.1 WAR + petclinic-infra oracle profile (ojdbc17, no dialect) + petclinic-app01 JDK switch to Temurin 25.0.4.1 (cross-module: db-inventory.yaml:13 JDK must move with the WAR)
5. Post-deployment record (not a code change): DBA updates petclinic-infra/oracle/db-inventory.yaml:12-13 (runs: Boot 4.1.1 / jdk: 25.0.4.1)

### Changes

| # | file:line | change | impact_ref |
|---|---|---|---|
| 1 | `spring-petclinic-rest/pom.xml:17` | Parent 1.5.2.RELEASE must move through 2.7.18 and 3.5.16 before 4.1.1 | IMP-REST-BOOT4 |
| 2 | `spring-petclinic-rest/pom.xml:24` | java.version 1.8: Boot 4.1.1 compiler plugin aborts "Fatal error compiling: error: release version 1.8 not supported" (B09); Boot 3/4 need Java 17+ | IMP-REST-BOOT4 |
| 3 | `spring-petclinic-rest/pom.xml:45` | spring-boot-starter-aop has no managed version in Boot 4 (renamed spring-boot-starter-aspectj) -> POM invalid (B08); still needed because CallMonitoringAspect.java:38 uses @Aspect | IMP-REST-BOOT4 |
| 4 | `spring-petclinic-rest/pom.xml:73` | mysql:mysql-connector-java no longer managed (relocated to com.mysql:mysql-connector-j) -> POM invalid (B08) | IMP-REST-BOOT4 |
| 5 | `spring-petclinic-rest/pom.xml:85` | spring-data-jdbc-core 1.2.1 (abandoned) drags spring-retry 1.0.3.RELEASE (CVE-2026-41710) because Boot 4 removed Spring Retry management (S01); used by JdbcPetVisitExtractor.java:18,30 and JdbcOwnerRepositoryImpl.java:121 | IMP-REST-BOOT4 |
| 6 | `spring-petclinic-rest/pom.xml:127` | Springfox 2.6.1 is javax.servlet-based and has no Boot 3/4 support -> replaced by springdoc-openapi-starter-webmvc-ui 3.1.1 in the proven variant | IMP-REST-BOOT4 |
| 7 | `spring-petclinic-rest/src/main/java/org/springframework/samples/petclinic/util/ApplicationSwaggerConfig.java:40` | Springfox configuration (@EnableSwagger2, Docket) must be deleted/rewritten for springdoc | IMP-REST-BOOT4 |
| 8 | `spring-petclinic-rest/pom.xml:150` | javax.xml.bind:jaxb-api -> jakarta.xml.bind-api (Vets.java:21, Vet.java:30 import javax.xml.bind.annotation) | IMP-REST-BOOT4 |
| 9 | `spring-petclinic-rest/src/main/java/org/springframework/samples/petclinic/model/BaseEntity.java:18` | javax.persistence -> jakarta.persistence: 134 x "package javax.persistence does not exist" on Boot 3.5/4.1 (B06/B10), e.g. BaseEntity | IMP-REST-BOOT4 |
| 10 | `spring-petclinic-rest/src/main/java/org/springframework/samples/petclinic/rest/OwnerRestController.java:21` | javax.transaction.Transactional -> jakarta.transaction | IMP-REST-BOOT4 |
| 11 | `spring-petclinic-rest/src/main/java/org/springframework/samples/petclinic/rest/RootRestController.java:21` | javax.servlet.http.HttpServletResponse -> jakarta.servlet | IMP-REST-BOOT4 |
| 12 | `spring-petclinic-rest/src/main/java/org/springframework/samples/petclinic/rest/OwnerRestController.java:22` | Bean Validation no longer pulled by the web starter (Boot 2.3+): javax.validation missing (B05) -> add spring-boot-starter-validation | IMP-REST-BOOT4 |
| 13 | `spring-petclinic-rest/src/main/java/org/springframework/samples/petclinic/model/NamedEntity.java:21` | org.hibernate.validator.constraints.NotEmpty removed (Hibernate Validator 9) -> jakarta.validation.constraints.NotEmpty (also Owner.java:32, Person.java:21, Visit.java:28) (B05/B11) | IMP-REST-BOOT4 |
| 14 | `spring-petclinic-rest/src/main/java/org/springframework/samples/petclinic/PetClinicApplication.java:6` | org.springframework.boot.web.support.SpringBootServletInitializer moved to org.springframework.boot.web.servlet.support (B06/B10/B11) | IMP-REST-BOOT4 |
| 15 | `spring-petclinic-rest/src/main/java/org/springframework/samples/petclinic/repository/jpa/JpaOwnerRepositoryImpl.java:26` | Unused import of org.springframework.orm.hibernate3.support.OpenSessionInViewFilter (package removed in Spring 5) (B11) | IMP-REST-BOOT4 |
| 16 | `spring-petclinic-rest/src/main/java/org/springframework/samples/petclinic/rest/OwnerRestController.java:55` | MediaType.APPLICATION_JSON_UTF8_VALUE removed in Spring Framework 7 (33 usages; B11 "cannot find symbol"); Content-Type changes from application/json;charset=UTF-8 to application/json (R05) | IMP-REST-BOOT4 |
| 17 | `spring-petclinic-rest/src/main/java/org/springframework/samples/petclinic/security/BasicAuthenticationAdapter.java:18` | WebSecurityConfigurerAdapter / antMatchers removed (B07 on 3.5.16, B11 on 4.1.1): rewrite as SecurityFilterChain + JdbcUserDetailsManager; @EnableGlobalMethodSecurity (:16) -> @EnableMethodSecurity | IMP-REST-BOOT4 |
| 18 | `spring-petclinic-rest/src/main/resources/application.properties:24` | server.context-path renamed server.servlet.context-path and is silently ignored: app served at "/" (R03 "context path '/'") and /petclinic/api/* — the URL used by petclinic-angular and ops/healthcheck.py — disappears | IMP-REST-BOOT4 |
| 19 | `spring-petclinic-rest/src/main/resources/application.properties:36` | security.ignored=/** removed: every endpoint returns HTTP 401 with a generated password (R03); replace with an explicit permitAll SecurityFilterChain when basic.authentication.enabled=false (proven R04/R05) | IMP-REST-BOOT4 |
| 20 | `spring-petclinic-rest/src/main/resources/application-hsqldb.properties:4` | spring.datasource.schema/data removed -> use spring.sql.init.schema-locations/data-locations (also line 5); migrated in the proven variant R04/R05 | IMP-REST-BOOT4 |
| 21 | `spring-petclinic-rest/src/main/java/org/springframework/samples/petclinic/model/Owner.java:53` | Boot 4 uses Jackson 3 by default and ignores the Jackson 2 @JsonSerialize/@JsonDeserialize (Owner.java:53-54, Pet.java:55-56, Visit.java:44-45): "Document nesting depth (501) exceeds the maximum allowed" and ISO birthDate (R04); fixed by spring-boot-jackson2 + spring.http.converters.preferred-json-mapper=jackson2 (R05: 7/7 GETs identical) | IMP-REST-BOOT4 |
| 22 | `spring-petclinic-rest/src/test/java/org/springframework/samples/petclinic/model/ValidatorTests.java:11` | Tests: JUnit 4 (org.junit) not provided by spring-boot-starter-test 4.1.1 -> "package org.junit does not exist" (B13); migrate to JUnit Jupiter | IMP-REST-BOOT4 |
| 23 | `spring-petclinic-rest/src/test/java/org/springframework/samples/petclinic/rest/PetRestControllerTests.java:37` | Tests: @MockBean (org.springframework.boot.test.mock.mockito) removed -> @MockitoBean (B13) | IMP-REST-BOOT4 |
| 24 | `spring-petclinic-rest/src/test/java/org/springframework/samples/petclinic/model/ValidatorTests.java:42` | Tests: expected message "may not be empty" becomes "must not be empty" with Hibernate Validator 9 (not executed this run — tests do not compile, B13) | IMP-REST-BOOT4 |
| 25 | `spring-petclinic-rest/src/test/java/org/springframework/samples/petclinic/service/clinicService/ClinicServiceJdbcTests.java:32` | Tests: @ActiveProfiles("jdbc, hsqldb") is ONE profile name containing a comma (not executed this run — tests do not compile, B13); split into {"jdbc","hsqldb"} | IMP-REST-BOOT4 |
| 26 | `spring-petclinic-rest/pom.xml:21` | Boot 4.1.1 manages tomcat-embed-core 11.0.24 (3 CRITICAL CVEs, S01) -> add &lt;tomcat.version>11.0.26&lt;/tomcat.version> to the properties block | IMP-REST-BOOT4 |
| 27 | `spring-petclinic-rest/.travis.yml:2` | CI declares oraclejdk8 -> Temurin 25 | IMP-REST-BOOT4 |
| 28 | `spring-petclinic-rest/pom.xml:17` | Spring 4.3 CGLIB proxies need ClassLoader.defineClass: 168 of 169 tests error with InaccessibleObjectException on JDK 17 (B01) | IMP-REST-JDK |
| 29 | `spring-petclinic-rest/pom.xml:9` | maven-war-plugin 2.6 inherited from the Boot 1.5.2 parent fails on JDK 17 (XStream reflection on java.util.TreeMap) unless MAVEN_OPTS --add-opens (B02/B03) | IMP-REST-JDK |
| 30 | `spring-petclinic-rest/src/main/java/org/springframework/samples/petclinic/rest/OwnerRestController.java:89` | Hibernate Validator 5.3.4 on JDK 17: POST /api/owners with a valid body -> 400 "HV000041: Call to TraversableResolver.isReachable() threw an exception" (R01; Boot 4.1.1 returns 201). Root cause not isolated (UNVERIFIED) | IMP-REST-JDK |
| 31 | `petclinic-infra/maven/oracle-profile.xml:7` | com.oracle:ojdbc6:11.2.0.4 is not on Maven Central -> "Could not find artifact com.oracle:ojdbc6:jar:11.2.0.4" when the profile is merged (B04); ojdbc6 = JDK 6-8 only | IMP-INFRA-JDBC |
| 32 | `petclinic-infra/maven/oracle-profile.xml:13` | org.hibernate.dialect.Oracle10gDialect does not exist in Hibernate 7 -> StrategySelectionException at startup (R06) | IMP-INFRA-JDBC |
| 33 | `petclinic-infra/maven/oracle-profile.xml:11` | The profile sets spring.datasource.url / spring.jpa.database-platform as MAVEN &lt;properties>; application.properties has no @...@ placeholders, so they do not reach Spring at runtime (how production injects them is UNVERIFIED) | IMP-INFRA-JDBC |
| 34 | `spring-petclinic-rest/src/main/java/org/springframework/samples/petclinic/model/BaseEntity.java:34` | Entities use GenerationType.IDENTITY while the Oracle DDL defines sequences and plain NUMBER(10) keys (schema.sql:2-5, 8) -> JPA inserts on Oracle would fail unless triggers exist (static analysis; no Oracle DB in sandbox, UNVERIFIED) | IMP-INFRA-JDBC |
| 35 | `petclinic-infra/oracle/schema.sql:7` | Oracle schema has no users/roles tables but BasicAuthenticationAdapter.java:38-39 queries them -> enabling basic auth on Oracle would fail (static analysis, UNVERIFIED) | IMP-INFRA-JDBC |
| 36 | `spring-petclinic-rest/src/main/java/org/springframework/samples/petclinic/repository/jdbc/JdbcPetVisitExtractor.java:18` | Replace org.springframework.data.jdbc.core.OneToManyResultSetExtractor (spring-data-jdbc-core, abandoned; drags spring-retry 1.0.3 with CVE-2026-41710) by an in-repo ResultSetExtractor; also JdbcPetVisitExtractor.java:30 and JdbcOwnerRepositoryImpl.java:121 | IMP-REST-BOOT4 |
| 37 | `spring-petclinic-rest/src/main/resources/application.properties:37 (insert after)` | Add spring.http.converters.preferred-json-mapper=jackson2 next to the spring-boot-jackson2 dependency (R05: 7/7 GETs identical; removed again in Wave 6) | IMP-REST-BOOT4 |
| 38 | `spring-petclinic-rest/src/main/java/org/springframework/samples/petclinic/security/BasicAuthenticationAdapter.java:16` | @EnableGlobalMethodSecurity -> @EnableMethodSecurity (part of the SecurityFilterChain rewrite) | IMP-REST-BOOT4 |
| 39 | `spring-petclinic-rest/src/main/java/org/springframework/samples/petclinic/model/Vets.java:21` | javax.xml.bind.annotation -> jakarta.xml.bind.annotation (also Vet.java:30) | IMP-REST-BOOT4 |
| 40 | `spring-petclinic-rest/src/main/java/org/springframework/samples/petclinic/rest/OwnerRestController.java:47` | @CrossOrigin must stay effective after the SecurityFilterChain rewrite (cors() enabled in the chain) - Angular is served from another origin | IMP-REST-BOOT4 |
| 41 | `petclinic-infra/maven/oracle-profile.xml:6` | oracle profile: com.oracle:ojdbc6:11.2.0.4 -> com.oracle.database.jdbc:ojdbc17:23.26.3.0.0 (listed for DB 19c, JDK 17+ incl. 25); same line as IMP-INFRA-DB breaking change 2 | IMP-INFRA-JDBC |
| 42 | `spring-petclinic-rest/.travis.yml:2` | CI: jdk oraclejdk8 -> Temurin 25 (moves with the code: the current code does not build on JDK 17+, B01) | IMP-REST-BOOT4 |

### Entry gates

| # | check | how (exact command / procedure) | pass criterion |
|---|---|---|---|
| 1 | Wave 1 closed (DB patched) | `Wave 1 exit gates signed off` | All Wave 1 exit gates PASS |
| 2 | Wave 3 closed (safety net in place) | `Wave 3 exit gates signed off` | Contract tests + UI smoke green on v1.5.2; Maven 3.9.16 wrapper; no jcenter |
| 3 | Decisions D1, D2, D3, D4, D9 approved | `Decision log` | All five approved by the owners listed in blocking_decisions |
| 4 | Target JDK installed on staging app server | `/opt/temurin-25.0.4.1/bin/java -version` | Reports 25.0.4.1 |
| 5 | Oracle staging schema available | `SQL*Plus / sqlcl connect to a staging copy of PETCLINIC at RU 19.32` | Connection OK; schema changes from D9 applied there |

### Exit gates

| # | check | how (exact command / procedure) | pass criterion |
|---|---|---|---|
| 1 | T1 transit build (Boot 2.7.18, not deployed) | `JAVA_HOME=<JDK 17> ./mvnw -B clean verify` | BUILD SUCCESS; Tests run: 169, Failures: 0, Errors: 0 (baseline P10); contract tests unchanged |
| 2 | T2 transit build (Boot 3.5.16, not deployed) | `JAVA_HOME=<JDK 17> ./mvnw -B clean verify` | BUILD SUCCESS; Tests run: 169, Failures: 0, Errors: 0; contract tests unchanged |
| 3 | Release build on Java 25 | `JAVA_HOME=<Temurin 25.0.4.1> ./mvnw -B clean verify \| tee build.log` | BUILD SUCCESS; build.log contains 'release 25'; 'Tests run: 169, Failures: 0, Errors: 0, Skipped: 0' - every baseline test preserved (B13 currently FAILS: tests do not compile) |
| 4 | REST contract unchanged | `./mvnw -B -Dtest=RestContractTests test against the Boot 4.1.1 WAR (context path /petclinic/)` | 7/7 GET bodies JSON-identical to the 1.5.2 snapshot (R05), POST /petclinic/api/owners -> 201, no 401 for anonymous calls; only documented delta: Content-Type 'application/json' instead of 'application/json;charset=UTF-8' (R05) |
| 5 | Current Angular 6 UI still works | `UI smoke (Wave 3) with the Angular 6 bundle against the Boot 4.1.1 WAR` | owner rows == GET /owners count and owner 1 shows '2010/09/07' (R09) |
| 6 | Ops script still works | `evidence/w2_gate_tests.py api http://<staging>:9966/petclinic/api/ <owners> <vets>` | exit 0, no JSONDecodeError (R08 bridge variant) |
| 7 | Runtime versions | `grep -E 'Apache Tomcat/\|Java version\|release 25' app.log build.log; java -version on petclinic-app01` | 'Apache Tomcat/11.0.26' and Temurin 25.0.4.1 |
| 8 | Removed artifacts stay removed | `./mvnw -B dependency:tree \| grep -cE 'spring-data-jdbc-core\|springfox\|guava:jar:18.0\|dom4j:dom4j:jar:1.6.1\|spring-retry:jar:1.0.3\|com.oracle:ojdbc6'` | 0 |
| 9 | CVE count for the wave's components = 0 | `./mvnw -B -q dependency:list -DincludeScope=test -DoutputFile=target/deps.txt && python3 tools/osv_maven.py target/deps.txt --scope test  (tool validated by negative control T01: 225 advisories on 1.5.2)` | 'OSV advisories: 0', exit 0 (S01 failed only on spring-retry 1.0.3 and tomcat 11.0.24, both removed/overridden here); report CVEs of the jdk key closed by Temurin 25.0.4.1 |
| 10 | Oracle path (staging, not provable in sandbox) | `mvn -Poracle package; start with SPRING_DATASOURCE_URL=jdbc:oracle:thin:@<staging>:1521/PETCLINIC; POST /petclinic/api/owners; GET it back` | Startup log shows OracleDialect, no StrategySelectionException (R06); POST 201 and row persisted (validates the IDENTITY/sequence fix of D9) |

### Rollback

Atomic release, blue/green on petclinic-app01: keep the previous 1.5.2 WAR, the previous oracle-profile build and JDK 8 installed side by side. Rollback = stop the Boot 4.1.1 service, set JAVA_HOME back to JDK 8, start the retained 1.5.2 WAR (ojdbc6 build), re-run the Wave 3 contract tests and UI smoke. DB schema changes from D9 must be additive/backward compatible (e.g. identity defaults or triggers that the 1.5.2 WAR ignores) and ship with a DBA-owned reverse script. Source rollback: git revert of the release merge in petclinic-rest and petclinic-infra. Transit steps T1/T2 are never deployed, so they need no runtime rollback.

### Evidence

- `B01` (report, FAIL): as-is `mvn clean package` (v1.5.2) - Tests run: 169, Failures: 0, Errors: 168, Skipped: 0; java.lang.reflect.InaccessibleObjectException: Unable to make protected final java.lang.Class java.lang.ClassLoader.defineClass(...) accessible: module java.base does
- `B02` (report, FAIL): as-is `mvn package -DskipTests` - Unable to make field private final java.util.Comparator java.util.TreeMap.comparator accessible: module java.base does not "opens java.util" to unnamed module; [ERROR] Failed to execute goal org.apache.maven.plugins:mave
- `B03` (report, PARTIAL): as-is package with MAVEN_OPTS --add-opens (workaround) - [INFO] BUILD SUCCESS (only with --add-opens hacks)
- `B04` (report, FAIL): as-is with petclinic-infra oracle profile merged, -Poracle - [ERROR] dependency: com.oracle:ojdbc6:jar:11.2.0.4 (compile); [ERROR] Could not find artifact com.oracle:ojdbc6:jar:11.2.0.4 in central (https://repo.maven.apache.org/maven2)
- `B05` (report, FAIL): Spring Boot 2.7.18 drop-in (parent + mysql coordinates) - 37 compile errors (74 lines in -q log), e.g. NamedEntity.java:[21,43] package org.hibernate.validator.constraints does not exist; Owner.java:[30,36] package javax.validation.constraints does not exist
- `B06` (report, FAIL): Spring Boot 3.5.16 drop-in (+ java.version 17) - [INFO] 100 errors; PetClinicApplication.java:[6,44] package org.springframework.boot.web.support does not exist; model/BaseEntity.java:[18,25] package javax.persistence does not exist
- `B07` (report, FAIL): Boot 3.5.16 + jakarta + validation starter + web.servlet.support + NotEmpty + hibernate3 import removed - security/BasicAuthenticationAdapter.java:[12,72] cannot find symbol (WebSecurityConfigurerAdapter); BasicAuthenticationAdapter.java:[23,5] method does not override or implement a method from a supertype
- `B08` (report, FAIL): Spring Boot 4.1.1 drop-in (parent only) - 'dependencies.dependency.version' for org.springframework.boot:spring-boot-starter-aop:jar is missing. @ line 43, column 15; 'dependencies.dependency.version' for mysql:mysql-connector-java:jar is missing. @ line 72, col
- `B09` (report, FAIL): Boot 4.1.1 + POM coordinate fixes (aspectj starter, mysql-connector-j) - maven-compiler-plugin:3.15.0:compile ... Fatal error compiling: error: release version 1.8 not supported
- `B10` (report, FAIL): Boot 4.1.1 + java.version 17 - [INFO] 100 errors (134 x "package javax.persistence does not exist"); PetClinicApplication.java:[6,44] package org.springframework.boot.web.support does not exist
- `B11` (report, FAIL): Boot 4.1.1 + javax->jakarta + validation starter + jakarta.xml.bind-api - 52 errors: rest/*RestController.java cannot find symbol (APPLICATION_JSON_UTF8_VALUE); symbol: class WebSecurityConfigurerAdapter; package org.springframework.orm.hibernate3.support does not exist; package org.springfram
- `B12` (report, PASS): Boot 4.1.1 + all source/POM fixes (boot4_fix.py full): package without tests - [INFO] BUILD SUCCESS
- `B13` (report, FAIL): Boot 4.1.1 test-compile - ValidatorTests.java:[11,17] package org.junit does not exist; OwnerRestControllerTests.java:[36,50] package org.springframework.boot.test.mock.mockito does not exist
- `B14` (report, PASS): Boot 4.1.1 final variant, java.version 25: package + run + contract + healthcheck - [INFO] Compiling 82 source files with javac [debug parameters release 25]; [INFO] BUILD SUCCESS; Starting Servlet engine: [Apache Tomcat/11.0.26]; healthcheck {'owners': 11, 'vets': 6}
- `B27` (report, FAIL): Boot 4.1.1 variant built with the repo's ./mvnw (Maven 3.3.3) - The plugin org.apache.maven.plugins:maven-resources-plugin:3.5.0 requires Maven version 3.6.3
- `R01` (report, PARTIAL): run as-is WAR, capture REST contract (7 GETs) + POST + healthcheck - GET x7 -> 200 application/json;charset=UTF-8; POST /petclinic/api/owners -> 400 {"className":"javax.validation.ValidationException","exMessage":"HV000041: Call to TraversableResolver.isReachable() threw an exception."}
- `R03` (report, FAIL): run Boot 4.1.1 WAR with properties unchanged - TomcatWebServer - Tomcat started on port 9966 (http) with context path '/'; GET /petclinic/api/owners -> 401; healthcheck: requests.exceptions.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
- `R04` (report, FAIL): properties migrated + permitAll chain (Jackson 3 default) - "Could not write JSON: Document nesting depth (501) exceeds the maximum allowed (500, from `StreamWriteConstraints.getMaxNestingDepth()`)"; "birthDate":"2010-09-07T00:00:00.000Z" (baseline "2010/09/07"); healthcheck: JSO
- `R05` (report, PASS): + spring-boot-jackson2 + spring.http.converters.preferred-json-mapper=jackson2 - 7/7 GET responses JSON-identical to the 1.5.2 baseline; POST /petclinic/api/owners -> 201; Apache Tomcat/11.0.26
- `R06` (report, FAIL): Boot 4.1.1 WAR with the Oracle10gDialect from oracle-profile.xml:13 - org.hibernate.boot.registry.selector.spi.StrategySelectionException: Unable to resolve name [org.hibernate.dialect.Oracle10gDialect] as strategy [org.hibernate.dialect.Dialect]
- `R08` (report, PARTIAL): healthcheck.api_counts() against 1.5.2 and three Boot 4 variants - 1.5.2: {'owners': 10, 'vets': 6}; Boot4 props unchanged: JSONDecodeError (char 0); Boot4 Jackson 3: JSONDecodeError (char 29157); Boot4 + jackson2 bridge: {'owners': 11, 'vets': 6}
- `R09` (report, PASS): UI smoke test: as-is Angular 6.1.6 bundle (B18) vs Boot 4.1.1 + Jackson 2 bridge - owner_rows: 23; owner 1 page shows "2010/09/07"
- `S01` (report, FAIL): OSV scan of the Boot 4.1.1 target dependency tree (137 artifacts) + Boot-managed default Tomcat 11.0.24 - org.springframework.retry:spring-retry:1.0.3.RELEASE -> GHSA-2827-2mxx-j8pv/CVE-2026-41710; tomcat-embed-core:11.0.24 -> CVE-2026-65905, CVE-2026-65182, CVE-2026-68525
- `P10` (this run, PASS): Baseline of the as-is backend (v1.5.2) with its own toolchain: Maven Wrapper (3.3.3) on JDK 8 (Temurin 8u504, sandbox CA bundle imported into cacerts), full test suite - measures the test count used in later gates - `evidence/P10.log`
- `P12` (this run, PASS): Supporting (Wave 3 input): capture the as-is REST contract of v1.5.2 on JDK 8 - 7 GETs, status, Content-Type, body sha256 - `evidence/P12.log`
- `T01` (this run, PASS): Gate-tool validation (negative control): tools/osv_maven.py on the AS-IS v1.5.2 dependency tree must report advisories (exit non-zero); step passes when it does - `evidence/T01.log`

## Wave 5 - petclinic-angular: Angular 6.1.6 -> 22.2.0 one major at a time, Node 10.10 -> 24.21.0 LTS, Bootstrap 3 -> 5

- **Status:** **PARTIALLY_PROVEN** - evidence: B15, B16, B17, B18, B19, B20, B21, B22, B23, B28, B30, R09, R10, R11, R12, R13, S02
- **Approvers:** tech-lead, security  |  **Risk:** high  |  **Effort:** XL  |  **Depends on:** Wave 3, Wave 4
- **Modules:** petclinic-angular

### Targets

| component_key | from | to | report CVEs (current) |
|---|---|---|---|
| `angular` | 6.1.6 | 22.2.0 | 17 |
| `angular-material` | dist-tag 'next' -> 7.0.0-beta.0 (pre-release) | 22.2.0 (+ @angular/cdk 22.2.0), pinned | 0 |
| `angular-material-moment-adapter` | 6.4.7 | 22.2.0 | 0 |
| `angular-http` | 6.1.6 | removed (package discontinued after 7.2.16, not imported in src/) | 0 |
| `bootstrap` | 3.3.7 | 5.3.8 | 7 |
| `jquery` | 3.3.1 | removed (Bootstrap 5 needs no jQuery; angular.json:28-30 scripts dropped); 4.0.0 only if a remaining consumer is found | 3 |
| `moment` | 2.22.2 | 2.31.0 (or a maintained date library - decision D6) | 2 |
| `rxjs` | 6.3.1 | 7.8.2 | 0 |
| `rxjs-compat` | 6.3.1 | removed (after RxJS 6 import clean-up, before RxJS 7) | 0 |
| `zone-js` | 0.8.26 | 0.16.3 (kept: provideZoneChangeDetection() required, R10-R12) | 0 |
| `core-js` | 2.5.7 | removed (not needed by Angular 22) | 0 |
| `tether` | 1.4.4 | removed (only needed by Bootstrap 4 alpha) | 0 |
| `nodejs` | 10.10 (CI, .travis.yml:5) | 24.21.0 LTS | 0 |
| `typescript` | 2.9.2 | 6.0.3 (highest allowed by Angular 22.2 compiler-cli: >=6.0 <6.1) | 0 |

### Intermediate steps

1. ng update one major at a time: 6 -> 7 -> 8 -> 9 -> 10 -> 11 -> 12 -> 13 -> 14 -> 15 -> 16 -> 17 -> 18 -> 19 -> 20 -> 21 -> 22, so each version's automatic migrations run (v19 adds standalone:false; v22 adds ChangeDetectionStrategy.Eager); build + unit tests + UI smoke after every major
2. Switch Node per CLI major as the Angular version-compatibility table requires (report: 10 -> 12/14 -> 16/18 -> 20 -> 22.22.3+/24); finish on Node 24.21.0 LTS
3. Remove rxjs-compat after the RxJS 6 import clean-up, before moving to RxJS 7
4. Drop @angular/http, codelyzer/tslint/protractor/karma 2 when their peer ranges block the next major (B19)
5. Migrate the builder to @angular/build:application and TypeScript 6 settings (moduleResolution bundler, no baseUrl)
6. Bootstrap 3 -> 5 template migration (btn-default x43, glyphicon x21), remove jQuery/tether/core-js
7. Keep Eager change detection + zone.js (provideZoneChangeDetection() in main.ts) - required for a non-empty UI (R10-R12); OnPush/signals is a later, separate decision (D6)
8. Deploy after Wave 4 (validated against the Boot 4 + Jackson 2 bridge backend, R12); may be developed in parallel

### Changes

| # | file:line | change | impact_ref |
|---|---|---|---|
| 1 | `spring-petclinic-angular/package.json:37` | node-sass 4.9.3 (transitive of @angular-devkit/build-angular ~0.7.0) builds with node-gyp 3.x which requires python2 -> npm ci fails on Node 22 (B15) | IMP-NG-ASIS |
| 2 | `spring-petclinic-angular/package.json:37` | webpack 4 MD4 hashing -> "error:0308010C:digital envelope routines::unsupported" x24 on Node >= 17 while `ng build` still exits 0 — a false green in CI (B17); builds only with --openssl-legacy-provider (B18) | IMP-NG-ASIS |
| 3 | `spring-petclinic-angular/.travis.yml:5` | CI pins Node 10.10 (EOL 2021-04-30) | IMP-NG-ASIS |
| 4 | `spring-petclinic-angular/package.json:44` | codelyzer 4.x / tslint / protractor / karma 2 devDependencies have peer ranges < 7/8 -> npm ERESOLVE (B19); remove (TSLint/Protractor deprecated). They also carry most of the 91 dev-scope npm audit findings of the target tree (S02) | IMP-NG-22 |
| 5 | `spring-petclinic-angular/package.json:21` | @angular/http was removed after 7.2.16 (no 22.x exists); not imported in src/ -> drop dependency | IMP-NG-22 |
| 6 | `spring-petclinic-angular/package.json:16` | Material/CDK on dist-tag "next" (pre-release 7.0.0-beta.0 in the lockfile) -> pin 22.2.0 (also line 22) | IMP-NG-22 |
| 7 | `spring-petclinic-angular/package.json:32` | rxjs-compat is incompatible with RxJS 7 -> remove after fixing deep imports | IMP-NG-22 |
| 8 | `spring-petclinic-angular/angular.json:38` | Build option "extractCss" removed -> "Schema validation failed ... Unknown option extractCss" (B21) | IMP-NG-22 |
| 9 | `spring-petclinic-angular/angular.json:12` | @angular-devkit/build-angular:browser (webpack) builder is deprecated in v22 (B22 warning) -> migrate to @angular/build:application | IMP-NG-22 |
| 10 | `spring-petclinic-angular/angular.json:132` | "defaultProject" workspace option removed ("Workspace extension with invalid name (defaultProject) found", B21) | IMP-NG-22 |
| 11 | `spring-petclinic-angular/tsconfig.json:5` | TypeScript 6: baseUrl deprecated (TS5101, B22) — also src/tsconfig.app.json:6; imports relying on it break once removed (vet-add.component.ts:25) | IMP-NG-22 |
| 12 | `spring-petclinic-angular/tsconfig.json:8` | TypeScript 6: moduleResolution "node" (node10) deprecated (TS5107) and cannot resolve Angular 22 package exports -> 23 x TS2307 e.g. "Cannot find module '@angular/common/http'" (B22); use "bundler" | IMP-NG-22 |
| 13 | `spring-petclinic-angular/src/app/visits/visit-list/visit-list.component.ts:38` | TypeScript 6 strict defaults -> 31 x TS2564 "Property ... has no initializer" (B22), e.g. errorMessage here | IMP-NG-22 |
| 14 | `spring-petclinic-angular/src/app/owners/owners.module.ts:42` | Components are standalone by default (Angular 19+) -> NG6008 "Component OwnerListComponent is standalone, and cannot be declared in an NgModule" (15-19 x, B22/B23); add standalone:false or convert | IMP-NG-22 |
| 15 | `spring-petclinic-angular/src/app/owners/owner-list/owner-list.component.ts:26` | RxJS 7: side-effect import 'rxjs/Rx' removed -> TS2882 (also owner-detail.component.ts:27, owner-edit.component.ts:27) | IMP-NG-22 |
| 16 | `spring-petclinic-angular/src/app/pettypes/pettype.service.ts:28` | RxJS 7: deep import 'rxjs/internal/operators' -> TS2307 (also specialty.service.ts:27, vet.service.ts:29, visit.service.ts:29) | IMP-NG-22 |
| 17 | `spring-petclinic-angular/src/app/specialties/spec-resolver.ts:23` | RxJS 7: 'rxjs/Observable' / 'rxjs/BehaviorSubject' paths removed (also vet-resolver.ts:21, testing/router-stubs.ts:54) | IMP-NG-22 |
| 18 | `spring-petclinic-angular/src/app/error.service.ts:65` | RxJS 7: static Observable.throwError removed -> TS2339 (B23); use throwError(() => ...) | IMP-NG-22 |
| 19 | `spring-petclinic-angular/src/app/pets/pets.module.ts:34` | Angular Material root entry point removed: import {MatDatepickerModule} from '@angular/material' -> TS2305 (also visits.module.ts:33); use '@angular/material/datepicker' | IMP-NG-22 |
| 20 | `spring-petclinic-angular/src/app/pets/pet-add/pet-add.component.ts:33` | `import * as moment from 'moment'` then moment(...) -> TS2349 'This expression is not callable' (call at :73; also pet-edit.component.ts:74, visit-add.component.ts:74, visit-edit.component.ts:71) | IMP-NG-22 |
| 21 | `spring-petclinic-angular/src/app/vets/vet-resolver.ts:1` | Triple-slash reference to node_modules/@angular/router/src/interfaces.d.ts (file no longer exists) -> TS6053 | IMP-NG-22 |
| 22 | `spring-petclinic-angular/src/polyfills.ts:73` | zone.js 0.16: 'zone.js/dist/zone' removed -> TS2882; import 'zone.js'. core-js/es7/reflect (:46) no longer needed | IMP-NG-22 |
| 23 | `spring-petclinic-angular/src/main.ts:30` | Angular 21+/22: bootstrapModule() is zoneless unless provideZoneChangeDetection() is supplied as applicationProviders — the app builds but async subscribe() results are never rendered (R10/R11) | IMP-NG-22 |
| 24 | `spring-petclinic-angular/src/app/owners/owner-list/owner-list.component.ts:43` | Angular 22: components without changeDetection default to OnPush; mutable-field components like this one (owners assigned inside subscribe) render nothing (R10); add changeDetection: ChangeDetectionStrategy.Eager to all 24 @Component classes (what `ng update` to v22 would add) (R12) | IMP-NG-22 |
| 25 | `spring-petclinic-angular/angular.json:24` | Bootstrap 3 -> 5 (CVE-2024-6485 has no 3.x fix): templates use BS3-only classes (btn-default x43, glyphicon x21); jQuery/tether scripts (angular.json:28-30) become unnecessary | IMP-NG-22 |
| 26 | `spring-petclinic-angular/src/app/pets/pet-add/pet-add.component.ts:73` | REST date contract: the UI formats dates as "YYYY/MM/DD" (also pets.module.ts:39 dateInput) — depends on the backend keeping the Jackson 2 custom format (R09 vs R13) | IMP-NG-22 |
| 27 | `spring-petclinic-angular/.travis.yml:24` | CI: after the per-major ng update chain, pin Node 24.21.0 LTS and build with `ng build --configuration production`; add the UI smoke test (Wave 3) as a required CI step | IMP-NG-22 |

### Entry gates

| # | check | how (exact command / procedure) | pass criterion |
|---|---|---|---|
| 1 | Wave 4 released (backend Boot 4.1.1 + Jackson 2 bridge in production) | `Wave 4 exit gates signed off` | All Wave 4 exit gates PASS |
| 2 | UI smoke harness available (Wave 3) | `npx playwright test e2e/smoke on the Angular 6 bundle` | PASS |
| 3 | Decisions D6 and D7 approved | `Decision log` | Approved by tech-lead (+ security for D7) |

### Exit gates

| # | check | how (exact command / procedure) | pass criterion |
|---|---|---|---|
| 1 | Clean install on the target Node | `node --version && npm ci  (no --legacy-peer-deps)` | v24.21.0; exit 0; 0 ERESOLVE (B19 currently FAILS) |
| 2 | Production build with no hidden errors | `npx ng build --configuration production 2>&1 \| tee ng-build.log; grep -ciE 'error' ng-build.log` | exit 0 AND 0 error lines (guards against the false green of B17) |
| 3 | Unit tests | `npx ng test --watch=false` | All specs pass, 0 failures (28 spec files / 32 it() blocks in the current tree; count must not drop without tech-lead approval) |
| 4 | UI smoke against Boot 4.1.1 + Jackson 2 bridge (mandatory - a green build shipped an empty UI in R10) | `npx playwright test e2e/smoke` | owner rows == GET /owners count; owner 1 page shows '2010/09/07' (R12) |
| 5 | Legacy code gone | `grep -rcE "rxjs/Rx'\|rxjs/internal\|zone.js/dist\|glyphicon\|btn-default\|@angular/http" src \| awk -F: '{s+=$2} END {print s}'` | 0 |
| 6 | CVE count for the wave's components = 0 | `npm audit --omit=dev ; npm audit` | 'found 0 vulnerabilities' for both (S02: 94 total / 3 prod today); also closes the 113 build-toolchain npm components of the report that belong to the Angular 6 tree |

### Rollback

Static bundle: keep the previous Angular 6 dist/ artifact on the web server and switch the document root/symlink back. The Boot 4.1.1 + Jackson 2 bridge backend serves both front-ends (R09 and R12), so no backend rollback is needed. Source: git revert of the upgrade merge.

### Evidence

- `B15` (report, FAIL): as-is `npm ci` - npm error path /tmp/builds/ng-asis/node_modules/node-sass; gyp verb `which` failed  python2 Error: not found: python2; gyp ERR! configure error
- `B16` (report, PASS): as-is `npm ci --ignore-scripts` - 
- `B17` (report, FAIL): as-is `ng build --prod` - Error: error:0308010C:digital envelope routines::unsupported (x24) ... EXIT 0 (false green)
- `B18` (report, PARTIAL): as-is build with NODE_OPTIONS=--openssl-legacy-provider (insecure workaround) - chunk {3} main.f60d80369bfb6edaf775.js (main) 1.42 MB [initial] [rendered]
- `B19` (report, FAIL): Angular 22.2.0 `npm install` (package.json bumped, lockfile removed) - npm error ERESOLVE unable to resolve dependency tree; npm error peer @angular/compiler@">=2.3.1 <7.0.0 \|\| >6.0.0-beta <7.0.0" from codelyzer@4.4.4
- `B20` (report, PASS): Angular 22.2.0 `npm install --legacy-peer-deps` (@angular/http dropped) - 
- `B21` (report, FAIL): `ng build --configuration production` drop-in - Workspace extension with invalid name (defaultProject) found.; Error: Schema validation failed with the following errors: Unknown option "extractCss".
- `B22` (report, FAIL): after removing extractCss - 164 errors: NG8002 38, TS2564 31, TS2307 23, NG6008 15, NG8001 14 ...; error TS5101: Option 'baseUrl' is deprecated and will stop functioning in TypeScript 7.0.; error TS5107: Option 'moduleResolution=node10' is deprecat
- `B23` (report, FAIL): after tsconfig fixes (bundler, no baseUrl, strict off, module es2022) - 104 errors; src/app/owners/owner-list/owner-list.component.ts:26:8 - error TS2882: Cannot find module or type declarations for side-effect import of 'rxjs/Rx'.; src/app/pettypes/pettype.service.ts:28:26 - error TS2307: C
- `B28` (report, PASS): after mechanical codemod (standalone:false, RxJS 7 imports, Material entry point, moment default import, zone.js, relative import, tsconfig.app baseUrl) - 0 errors; Initial total 1.65 MB; EXIT 0
- `B30` (report, PASS): + provideZoneChangeDetection() in main.ts + changeDetection: Eager on 24 components - EXIT 0
- `R09` (report, PASS): UI smoke test: as-is Angular 6.1.6 bundle (B18) vs Boot 4.1.1 + Jackson 2 bridge - owner_rows: 23; owner 1 page shows "2010/09/07"
- `R10` (report, FAIL): UI smoke test: B28 bundle vs Boot 4.1.1 + Jackson 2 bridge backend (headless Chromium) - api_calls: 200 /petclinic/api/owners, 200 /petclinic/api/owners/1; owner_rows: 0, owner1_has_Leo: false (no console errors)
- `R11` (report, FAIL): UI smoke test: + Eager change detection but WITHOUT provideZoneChangeDetection() - owner_rows: 0
- `R12` (report, PASS): UI smoke test: B30 bundle vs Boot 4.1.1 + Jackson 2 bridge - owner_rows: 23; first_row "George Franklin 110 W. Liberty St. Madison 6085551023 Leo"; owner 1 page shows "2010/09/07"
- `R13` (report, FAIL): UI smoke test: as-is Angular 6.1.6 bundle vs Boot 4.1.1 with default Jackson 3 - OwnerService::getOwners failed: server returned code 200 with body "[object Object]"; owner_rows: 0
- `S02` (report, FAIL): npm audit of the Angular 22.2.0 target tree (legacy devDependencies still present) - 94 vulnerabilities (2 low, 18 moderate, 44 high, 30 critical); --omit=dev: 3 vulnerabilities (bootstrap <=3.4.1, jquery, moment) -> bump bootstrap 5.3.8 / jquery 4.0.0 / moment 2.31.0 and drop karma 2/protractor/codelyze

## Wave 6 - petclinic-rest: port custom (de)serializers to Jackson 3 and drop the deprecated spring-boot-jackson2 bridge

- **Status:** **UNPROVEN** - evidence: none
- **Approvers:** tech-lead, security  |  **Risk:** medium  |  **Effort:** M  |  **Depends on:** Wave 4, Wave 5
- **Modules:** petclinic-rest

### Targets

| component_key | from | to | report CVEs (current) |
|---|---|---|---|
| `jackson-databind` | 2.8.7 (scan); Boot-managed Jackson 2 via spring-boot-jackson2 after Wave 4 | tools.jackson.core:jackson-databind 3.x as managed by Boot 4.1.1 (3.1.5 per report) or 3.2.3 (decision D3) | 56 |

### Intermediate steps

1. Port the 6 custom (de)serializers to tools.jackson and switch the model annotations
2. Remove spring-boot-jackson2 and spring.http.converters.preferred-json-mapper
3. Re-run contract tests, UI smoke (Angular 22) and the ops script against the result

### Changes

| # | file:line | change | impact_ref |
|---|---|---|---|
| 1 | `spring-petclinic-rest/src/main/java/org/springframework/samples/petclinic/rest/JacksonCustomOwnerSerializer.java:37` | Port JacksonCustomOwnerSerializer from the Jackson 2 StdSerializer to tools.jackson (same for JacksonCustomPetSerializer.java:37, JacksonCustomVisitSerializer.java:37, JacksonCustomOwnerDeserializer.java:34, JacksonCustomPetDeserializer.java:40, JacksonCustomVisitDeserializer.java:39) | IMP-REST-BOOT4 |
| 2 | `spring-petclinic-rest/src/main/java/org/springframework/samples/petclinic/model/Owner.java:53` | @JsonSerialize/@JsonDeserialize -> tools.jackson.databind.annotation (also Pet.java:55-56, Visit.java:44-45) | IMP-REST-BOOT4 |
| 3 | `spring-petclinic-rest/pom.xml:111` | Remove the explicit com.fasterxml.jackson.core jackson-core/jackson-databind dependencies (pom.xml:111-118) and spring-boot-jackson2 | NEW |
| 4 | `spring-petclinic-rest/src/main/resources/application.properties:37` | Remove spring.http.converters.preferred-json-mapper=jackson2 added in Wave 4 | IMP-REST-BOOT4 |

### Entry gates

| # | check | how (exact command / procedure) | pass criterion |
|---|---|---|---|
| 1 | Waves 4 and 5 released | `Exit gates of Waves 4 and 5 signed off` | All PASS |

### Exit gates

| # | check | how (exact command / procedure) | pass criterion |
|---|---|---|---|
| 1 | Build + tests | `JAVA_HOME=<Temurin 25.0.4.1> ./mvnw -B clean verify` | BUILD SUCCESS; Tests run: 169, Failures: 0, Errors: 0 |
| 2 | REST contract unchanged without the bridge | `./mvnw -B -Dtest=RestContractTests test` | 7/7 GETs JSON-identical to the frozen snapshot; birthDate 'yyyy/MM/dd'; no 'nesting depth (501)' error (R04 failure mode) |
| 3 | UI and ops consumers | `npx playwright test e2e/smoke (Angular 22) ; evidence/w2_gate_tests.py api ...` | Both PASS (R12 criteria; R08 counts) |
| 4 | Bridge removed | `./mvnw -B dependency:tree \| grep -c spring-boot-jackson2` | 0 (com.fasterxml jackson may remain only as a transitive of third-party libraries - UNVERIFIED which) |
| 5 | CVE count for the wave's components = 0 | `python3 tools/osv_maven.py target/deps.txt --scope test` | 'OSV advisories: 0' |

### Rollback

Redeploy the Wave 4 WAR (Jackson 2 bridge) - contract-identical for both front-end versions (R05, R09, R12); git revert of the port.

### Evidence

- none (UNPROVEN)

## Wave 7 - Platform: Oracle Linux 7.6 -> 9/10 on petclinic-db01 (dedicated window; 26ai evaluated separately)

- **Status:** **NOT_PROVABLE_IN_SANDBOX** - evidence: X01
- **Approvers:** dba, platform-ops, security  |  **Risk:** high  |  **Effort:** L  |  **Depends on:** Wave 1
- **Modules:** petclinic-infra

### Targets

| component_key | from | to | report CVEs (current) |
|---|---|---|---|
| `oracle-linux` | 7.6 (Extended Support only; db-inventory.yaml:9) | Oracle Linux 9 or 10 (target minor release and Oracle DB 19c certification UNVERIFIED - MOS/ULN login required) | 0 |

### Intermediate steps

1. Decision D8: fund OL7 Extended Support until migration, or schedule OL9/OL10
2. Build a new host on OL9/OL10 with Oracle 19c at the Wave 1 patch level (or newer), certification checked on MOS (UNVERIFIED)
3. Move the database by RMAN duplicate or Data Guard standby + switchover (no in-place OS upgrade)
4. Post-deployment record (not a code change): DBA updates petclinic-infra/oracle/db-inventory.yaml:9

### Changes

_No repository code change in this wave (operational change on the target systems only)._

### Entry gates

| # | check | how (exact command / procedure) | pass criterion |
|---|---|---|---|
| 1 | Decision D8 approved | `Decision log` | Approved by platform-ops + dba + security |
| 2 | Certification | `MOS certification matrix: Oracle Database 19c at the Wave 1 RU on the chosen OL release` | Certified (UNVERIFIED today) |
| 3 | Wave 1 closed | `Wave 1 exit gates signed off` | All PASS |

### Exit gates

| # | check | how (exact command / procedure) | pass criterion |
|---|---|---|---|
| 1 | OS release | `cat /etc/os-release on the new petclinic-db01` | VERSION_ID 9.x or 10.x |
| 2 | Database gates | `Repeat the Wave 1 exit gates (dba_registry_sqlpatch, version_full, INVALID count, dba_registry)` | Same results as after Wave 1 |
| 3 | Application regression | `Wave 3 contract tests + UI smoke + ops/healthcheck.py against the new host` | All PASS, healthcheck exit 0 |

### Rollback

Data Guard switchover back to the retained OL7.6 primary (or keep the old host untouched until the new one passes all gates); DNS/service name switched back.

### Evidence

- `X01` (report, NOT_ATTEMPTED): Oracle Database 19c: apply RU 19.32 / connect ojdbc17 + python-oracledb to a live DB - failed to connect to the docker API at unix:///var/run/docker.sock ... no such file or directory (no Docker daemon); no Oracle DB image/licence in the sandbox; RU/CSPU patches require My Oracle Support credentials; no ne

## Coverage

All **46** outdated production component_keys of the report are covered exactly once; `uncovered` = [] and `deferred` = [] (checked by `tools/validate_plan.py`).

| component_key | module | current | wave | EOL | report CVEs |
|---|---|---|---|---|---|
| `oracle-database` | petclinic-infra | 19.3.0.0.0, Release Update applied: none (base release, Apri | 1 | no | 22 |
| `oracle-ojvm` | petclinic-infra | none applied | 1 | no | 4 |
| `oracle-linux` | petclinic-infra | 7.6 | 7 | no | 0 |
| `python` | petclinic-infra | 3.6.8 | 2 | yes | 0 |
| `requests` | petclinic-infra | 2.19.1 | 2 | no | 5 |
| `urllib3` | petclinic-infra | 1.23 | 2 | no | 11 |
| `pyyaml` | petclinic-infra | 3.12 | 2 | no | 2 |
| `cx-oracle` | petclinic-infra | 6.4.1 | 2 | yes | 0 |
| `jinja2` | petclinic-infra | 2.10 | 2 | no | 6 |
| `ojdbc` | petclinic-infra | com.oracle:ojdbc6 11.2.0.4 | 4 | yes | 3 |
| `hibernate-oracle-dialect` | petclinic-infra | org.hibernate.dialect.Oracle10gDialect | 4 | no | 0 |
| `jdk` | petclinic-rest | JDK 1.8.0_161 (app server); java.version 1.8 (build); oracle | 4 | no | 32 |
| `spring-boot` | petclinic-rest | 1.5.2.RELEASE | 4 | yes | 6 |
| `spring-framework` | petclinic-rest | 4.3.7.RELEASE | 4 | yes | 36 |
| `spring-security` | petclinic-rest | 4.2.2.RELEASE | 4 | yes | 12 |
| `spring-data-jpa` | petclinic-rest | 1.11.1.RELEASE | 4 | yes | 2 |
| `spring-data-commons` | petclinic-rest | 1.13.1.RELEASE | 4 | yes | 6 |
| `spring-retry` | petclinic-rest | 1.2.0.RELEASE (Boot 4.1.1 target would resolve 1.0.3.RELEASE | 4 | no | 1 |
| `spring-data-jdbc-ext` | petclinic-rest | 1.2.1.RELEASE | 4 | yes | 0 |
| `apache-tomcat` | petclinic-rest | 8.5.11 | 4 | yes | 58 |
| `jackson-databind` | petclinic-rest | 2.8.7 | 6 | no | 56 |
| `jackson-core` | petclinic-rest | 2.8.7 | 4 | no | 3 |
| `hibernate-orm` | petclinic-rest | 5.0.12.Final | 4 | yes | 2 |
| `hibernate-validator` | petclinic-rest | 5.3.4.Final | 4 | yes | 4 |
| `dom4j` | petclinic-rest | 1.6.1 | 4 | yes | 2 |
| `logback` | petclinic-rest | 1.1.11 | 4 | no | 9 |
| `snakeyaml` | petclinic-rest | 1.17 | 4 | no | 8 |
| `springfox` | petclinic-rest | 2.6.1 | 4 | yes | 1 |
| `guava` | petclinic-rest | 18.0 | 4 | no | 3 |
| `hsqldb` | petclinic-rest | 2.3.3 | 4 | no | 1 |
| `mysql-connector-j` | petclinic-rest | mysql:mysql-connector-java 5.1.41 | 4 | no | 6 |
| `postgresql-jdbc` | petclinic-rest | 9.4.1212.jre7 | 4 | no | 4 |
| `jaxb-api` | petclinic-rest | javax.xml.bind:jaxb-api 2.3.0 | 4 | no | 0 |
| `aspectj` | petclinic-rest | 1.8.9 | 4 | no | 0 |
| `angular` | petclinic-angular | 6.1.6 | 5 | yes | 17 |
| `angular-material` | petclinic-angular | dist-tag 'next' -> 7.0.0-beta.0 (pre-release, per package-lo | 5 | yes | 0 |
| `angular-material-moment-adapter` | petclinic-angular | 6.4.7 | 5 | yes | 0 |
| `angular-http` | petclinic-angular | 6.1.6 | 5 | yes | 0 |
| `bootstrap` | petclinic-angular | 3.3.7 | 5 | yes | 7 |
| `jquery` | petclinic-angular | 3.3.1 | 5 | no | 3 |
| `moment` | petclinic-angular | 2.22.2 | 5 | no | 2 |
| `rxjs` | petclinic-angular | 6.3.1 | 5 | no | 0 |
| `rxjs-compat` | petclinic-angular | 6.3.1 | 5 | yes | 0 |
| `zone-js` | petclinic-angular | 0.8.26 | 5 | no | 0 |
| `core-js` | petclinic-angular | 2.5.7 | 5 | yes | 0 |
| `tether` | petclinic-angular | 1.4.4 | 5 | no | 0 |

**Test-scope keys** (5): `assertj`, `json-path`, `json-smart`, `junit`, `mockito` - all upgraded in Wave 4 (spring-boot-starter-test 4.1.1).

**Build-toolchain keys** (113): `apache-maven` -> Wave 3; `nodejs`, `typescript` -> Wave 5 (explicit targets). The other 110 keys (e.g. `angular-cli`, `angular-devkit-build-angular`, `node-sass`, `karma`, `webpack-dev-server`, `lodash`, ...) are npm packages of the Angular 6 build tree; they are replaced or removed when Wave 5 regenerates the lockfile, and Wave 5's exit gate `npm audit` = 0 vulnerabilities covers them. They are not production scope and therefore not listed in `coverage`.

## Blocking decisions

| # | decision | owner | blocks waves | recommendation |
|---|---|---|---|---|
| 1 | D1 - Java target: approve Java 25 LTS (Temurin 25.0.4.1) rather than 17 (Oracle Java 17 Premier Support ended Sep 2026), shipped in the same release as Spring Boot 4.1.1. | tech-lead + security | 4 | Approve Java 25 LTS (Temurin 25.0.4.1): proven build/run in B14; Java 17 Premier Support has ended per the report. |
| 2 | D2 - Spring Boot path: approve 1.5.2 -> 2.7.18 -> 3.5.16 -> 4.1.1 with 2.7/3.5 as non-deployed transit steps (both out of OSS support). | tech-lead | 4 | Approve 1.5.2 -> 2.7.18 -> 3.5.16 -> 4.1.1 with 2.7/3.5 as build-and-test-only transit gates (T1/T2), never deployed. |
| 3 | D3 - Version overrides: pin Tomcat 11.0.26 over the Boot-managed 11.0.24 (mandatory, 3 CRITICAL CVEs); decide whether to also override Hibernate 7.4.5 -> 7.4.10, Hibernate Validator 9.1.3 -> 9.1.4, Jackson 2.21.5/3.1.5 -> 2.22.3/3.2.3, Logback 1.5.38 -> 1.6.3. | tech-lead + security | 4, 6 | Mandatory: &lt;tomcat.version>11.0.26&lt;/tomcat.version>. Other overrides only if the Wave 4/6 OSV gate reports a finding; otherwise stay on Boot-managed versions to reduce drift. |
| 4 | D4 - Accept the deprecated spring-boot-jackson2 bridge as a temporary measure (proven contract-identical for Angular and ops) until serializers are ported to Jackson 3. | tech-lead + security | 4 | Accept the bridge for Wave 4 only (R05/R09 contract-identical); Wave 6 removes it. Also accept the documented Content-Type change application/json;charset=UTF-8 -> application/json (R05). |
| 5 | D5 - Oracle DB patch window for RU 19.32 + OJVM + Aug/Sep 2026 CSPU (OJVM/datapatch downtime) ahead of the next quarterly Oracle CPU; stay on 19c LTR vs plan 26ai. (report decisions_needed[4]; vendor date reference omitted so that the plan sets no migration date) | dba + security | 1 | Approve the OJVM-capable downtime window for Wave 1 as the first action (5 CRITICAL DB CVEs); stay on 19c LTR now, evaluate 26ai separately. |
| 6 | D6 - Angular: incremental ng update through 16 majors vs re-scaffold on Angular 22; keep Eager change detection + zone.js initially (required, R10-R12) vs invest in OnPush/signals; accept Bootstrap 3 -> 5 visual changes and a moment.js replacement. | tech-lead | 5 | Incremental ng update per major (runs the official migrations), keep Eager CD + zone.js initially (R10-R12), accept Bootstrap 5 visual changes; moment 2.31.0 now, replacement later. |
| 7 | D7 - Make a UI smoke test a release gate for the front-end upgrade (a green `ng build` shipped an empty UI in R10). | tech-lead + security | 3, 5 | Yes - UI smoke is a required gate from Wave 3 on (R10: green ng build, empty UI). |
| 8 | D8 - Oracle Linux 7.6: fund Extended Support until the OS migration, or schedule OL9/OL10. | platform-ops + dba | 7 | Fund Extended Support as a bridge and schedule OL9/OL10 via a new host (Wave 7). |
| 9 | D9 (NEW, from IMP-INFRA-JDBC) - Oracle profile: how spring.datasource.url reaches Spring in production (Maven &lt;properties> are not used at runtime), and how to reconcile GenerationType.IDENTITY with the sequence-only Oracle DDL and the missing users/roles tables (all UNVERIFIED at runtime) | dba + tech-lead | 4 | Inject the URL via environment/application-oracle.properties; add identity columns (or triggers) with an additive DBA script tested on the staging copy; add users/roles tables only if basic auth will be enabled. |
| 10 | D10 (NEW) - Interim security patch of the app-server JDK 8u161 -> Temurin 8u504 before Wave 4 (the report lists 8u504 as fixing all 32 jdk CVEs) | security + platform-ops | none (optional) | Recommended as an optional interim measure: the current code builds and passes 169/169 tests on 8u504 (P10) and serves the REST API (P11). The jdk component itself is covered by Wave 4 (Java 25). |
| 11 | D11 (NEW) - ops/healthcheck.yaml:5 contains the literal '${ORACLE_RO_PASSWORD}'; neither the current nor the upgraded script expands environment variables, so the production substitution mechanism must be confirmed before W2-G9 | platform-ops | 2 | Document the mechanism (e.g. templating at deploy time); if none exists, add explicit os.environ expansion in a follow-up change reviewed by security (not part of wave-2.patch). |

D1-D8 are the report's `decisions_needed` (verbatim except D5, where the vendor CPU date was replaced by "the next quarterly Oracle CPU" so that the plan contains no migration date); D9-D11 are NEW findings of this planning run.

## New findings during planning (not in the source report)

- **As-is backend is healthy on patched JDK 8:** v1.5.2 builds with its own wrapper (Maven 3.3.3) on Temurin 8u504 with `Tests run: 169, Failures: 0, Errors: 0` (P10) and serves the contract (P11/P12). The report's 169-test count (B01, on JDK 17) is thus a valid baseline for Waves 3, 4 and 6. It also backs D10 (interim JDK 8u504 patch).
- **Maven 3.9.16 + no jcenter work with the current code** (W3-P01: empty local repository, 169/169 tests, 0 downloads from jcenter, W3-P02).
- **`ops/healthcheck.yaml:5` password placeholder is never expanded by the script** (D11).
- **Explicit `com.fasterxml.jackson.core` dependencies at `pom.xml:111-118`** must be removed when leaving the bridge (Wave 6, impact_ref NEW).
- **`ops/healthcheck.py:28-29` uses `verify=False`** on the REST calls; harmless with the current `http://` URL, but should be removed if the endpoint moves to HTTPS (recommendation, no wave dependency).
- **Transitive Python packages are not pinned** (`ops/requirements.txt` pins only the 5 direct libraries; P05 resolved cryptography, certifi, MarkupSafe, ... freely). The CVE gate therefore also audits the resolved venv (P08: 0 advisories). A hash-locked constraints file is recommended as a follow-up.

## Items that remain UNVERIFIED

- Oracle MOS patch numbers for RU 19.32 / OJVM / Aug+Sep 2026 CSPU, the RU readme prerequisites and RU 19.32 certification on Oracle Linux 7.6 (MOS login).
- Runtime behaviour of anything that talks to Oracle: current ojdbc6 11.2 against a patched 19.32 DB, ojdbc17 + OracleDialect, IDENTITY vs sequences in `schema.sql`, how the production datasource URL is injected (no Oracle DB in the sandbox, X01).
- The Boot 4.1.1-managed version of the PostgreSQL driver (not recorded in the report) and the springdoc version for the Boot 3.5 transit step.
- Oracle Linux 9/10 target minor release and certification; errata level of OL 7.6 (ULN login).
- Root cause of HV000041 on JDK 17 (R01) - irrelevant after Wave 4 but noted in the report.

## Proof - Wave 2 (first wave that changes code)

Wave 1 changes no repository code (it is an operational DB patch and is NOT_PROVABLE_IN_SANDBOX), so the first wave that changes code is **Wave 2**. On a throwaway copy in the sandbox exactly the Wave 2 changes (11 edits in 3 files, table above) were applied, the exit gates were run, and the diff was saved as `wave-2.patch`.

**Base refs**

- `spring-petclinic-rest`: v1.5.2 (6479aaa4b3b47b646e3f4c7d6f4fa293ebd2791d) - unchanged by wave 2
- `spring-petclinic-angular`: 22935fc04933e4dec3b20bcfb8720f56b09f170d - unchanged by wave 2
- `petclinic-infra`: petclinic-infra.tar.gz sha256 1832fad909c689004d12c865bb59009d57fc43faf3bf18460b24f4bdf94c48c5 (patch paths relative to petclinic-infra/)
- `impact-report.json`: sha256 415dfc78cee094dbb3814a89cfc6f40b2aec85c4426a0552ac489ee4b3f53121

**Apply / check / roll back** (on a fresh extraction of the pinned tarball):

```bash
tar -xzf petclinic-infra.tar.gz && cd petclinic-infra
git apply --check ../wave-2.patch && git apply ../wave-2.patch     # or, from the parent dir: git apply --directory=petclinic-infra --check wave-2.patch
git apply -R ../wave-2.patch                                       # rollback (P14)
```

**Steps** (every command, full output in `evidence/<id>.log`; negative controls pass when the old state fails as expected):

| id | what | result |
|---|---|---|
| `P00` | Pin inputs: verify refs of the cloned repos and checksum of the infra tarball | PASS |
| `P01` | Create throwaway copy of pinned petclinic-infra and record a baseline commit (sandbox only, never pushed) | PASS |
| `P02` | Install CPython 3.14.7 (target runtime of Wave 2) | PASS |
| `P03` | Negative control (entry evidence): pinned AS-IS requirements (baseline commit) on CPython 3.14.7 must FAIL to install (reproduces B24); step passes when the install fails | PASS |
| `P04` | Wave 2 change set applied to the throwaway copy (git diff of the working tree vs baseline) | PASS |
| `P05` | Exit gate W2-G1: clean venv on CPython 3.14.7, pip install -r ops/requirements.txt exits 0 | PASS |
| `P06` | Exit gates W2-G2..G5 (offline): exact pins, import on 3.14.7, safe_load, collections.abc, keyword connect, template render, Thin mode | PASS |
| `P07` | Exit gate W2-G6: python-oracledb Thin mode reaches the network without an Oracle Client (no DB in sandbox, X01) - closed local port | PASS |
| `P08` | Exit gate W2-G7: known-vulnerability count for the Wave 2 components (pins + full resolved transitive set) = 0 (pip-audit, OSV service) | PASS |
| `P09` | Negative control for W2-G7: the as-is pins (baseline commit) DO report known vulnerabilities, so the gate discriminates | PASS |
| `P10` | Baseline of the as-is backend (v1.5.2) with its own toolchain: Maven Wrapper (3.3.3) on JDK 8 (Temurin 8u504, sandbox CA bundle imported into cacerts), full test suite - measures the test count used in later gates | PASS |
| `P11` | Exit gate W2-G8 (REST contract, cf. R08): healthcheck.api_counts() on CPython 3.14.7 + requests 2.34.2 against the CURRENT backend v1.5.2 WAR running on JDK 8u504 at the production URL shape http://&lt;host>:9966/petclinic/api/ - expect owners=10, vets=6 | PASS |
| `P12` | Supporting (Wave 3 input): capture the as-is REST contract of v1.5.2 on JDK 8 - 7 GETs, status, Content-Type, body sha256 | PASS |
| `P13` | Patch applicability: wave-2.patch passes git apply --check on a FRESH extraction of the pinned petclinic-infra.tar.gz (inside the dir and from the parent dir with --directory), applies, and the result is byte-identical to the proven tree | PASS |
| `P14` | Rollback rehearsal: git apply -R restores the pinned baseline byte-for-byte | PASS |
| `P15` | Re-run ALL Wave 2 exit gates on a tree produced only from the pinned tarball + wave-2.patch (fresh venv; set -eo pipefail): install, offline checks, Thin mode, api_counts vs v1.5.2 on JDK 8, pip-audit | PASS |
| `P16` | Negative control for the code fixes: AS-IS ops/healthcheck.py (baseline commit) with the new libraries on 3.14.7 fails (reproduces R07 first error); step passes when it fails | PASS |
| `W3-P01` | Supporting evidence for Wave 3 (partial): Maven Wrapper -> 3.9.16 + jcenter repository removed (pom.xml:33-40), JDK 8u504, EMPTY local repo (-Dmaven.repo.local=/tmp/m2-w3) so every artifact must resolve from Maven Central; full test suite | PASS |
| `W3-P02` | Supporting evidence for Wave 3: verify W3-P01 resolved nothing from jcenter and used Maven 3.9.16; OSV check of the Maven distribution (CVE-2021-26291 fixed in 3.8.1+) | PASS |
| `T01` | Gate-tool validation (negative control): tools/osv_maven.py on the AS-IS v1.5.2 dependency tree must report advisories (exit non-zero); step passes when it does | PASS |

**Key outputs**

`P03`:
```
      ext/_yaml.c:49:12: fatal error: longintrepr.h: No such file or directory
         49 |   #include "longintrepr.h"
  ERROR: Failed building wheel for PyYAML
as-is install rc=1 (non-zero expected)
# ----- exit code: 0 -----
(full log: evidence/P03.log)
```
`P06`:
```
PASS rest_api_url unchanged (REST contract): http://petclinic-app01:9966/petclinic/api/
PASS load_config rejects !!python tags
PASS oracledb.connect keyword-only: {'user': 'petclinic_ro', 'password': 'x', 'dsn': 'petclinic-db01:1521/PETCLINIC'}
SUMMARY: 0 failed check(s)
# ----- exit code: 0 -----
(full log: evidence/P06.log)
```
`P08`:
```
pip-audit 2.10.1
== pinned requirements (OSV) ==
No known vulnerabilities found
== full installed venv incl. transitive deps (OSV) ==
No known vulnerabilities found
rc_requirements=0 rc_env=0
# ----- exit code: 0 -----
(full log: evidence/P08.log)
```
`P11`:
```
INFO  TomcatEmbeddedServletContainer - Tomcat started on port(s): 9966 (http)
INFO  PetClinicApplication - Started PetClinicApplication in 6.43 seconds (JVM running for 6.887)
api_counts = {'owners': 10, 'vets': 6}
PASS api_counts owners: 10
PASS api_counts vets: 6
SUMMARY: 0 failed check(s)
# ----- exit code: 0 -----
(full log: evidence/P11.log)
```
`P13`:
```
Checking patch petclinic-infra/ops/healthcheck.py...
Checking patch petclinic-infra/ops/requirements.txt...
Checking patch petclinic-infra/ops/runtime.txt...
Checking patch ops/healthcheck.py...
Checking patch ops/requirements.txt...
Checking patch ops/runtime.txt...
IDENTICAL to proven tree (excluding .git and __pycache__)
# ----- exit code: 0 -----
(full log: evidence/P13.log)
```
`P15`:
```
[W2-G1] install rc=0
SUMMARY: 0 failed check(s)
SUMMARY: 0 failed check(s)
api_counts = {'owners': 10, 'vets': 6}
SUMMARY: 0 failed check(s)
No known vulnerabilities found
ALL WAVE 2 EXIT GATES PASS ON PATCH-ONLY TREE
# ----- exit code: 0 -----
(full log: evidence/P15.log)
```

Supporting tools shipped with the plan: `evidence/w2_gate_tests.py` (Wave 2 gate harness), `tools/osv_maven.py` (Maven CVE gate, validated by T01), `tools/report_cves.py` (lists report CVEs per wave), `tools/step.sh` (the logger used for every proof step), `tools/gen_plan.py` + `tools/gen_md.py` (generate the JSON and this document from one model), `tools/validate_plan.py` + `tools/migration-plan.schema.json` (schema and invariant validation).

