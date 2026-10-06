# Estate scan 2026-09-26 — one-page summary

**Verdict:** RED — far from "latest version, latest patch, no CVEs": 163/163 components outdated, 24 end-of-life, 332 unique CVEs in production scope (53 critical) + 276 in the build toolchain, and the Oracle database is 19.3 with no Release Update (behind the Jul 2026 CPU and Aug/Sep 2026 CSPUs).

## New since last scan (previous: 2026-09-24, run4) — [details](impact-report.md#new-since-last-scan)
- No newly published CVEs (OSV re-query of all 1,221 installed versions; the target versions are also clean except the known Tomcat 11.0.24/spring-retry items). No new Oracle CPU/CSPU/Alert.
- **Oracle Oct 2026 CPU lands 2026-10-20 (in 24 days)**: DB still 19.3 with no RU, so the patch window decision is now urgent.
- New GA release: Logback 1.6.4 (2026-09-24). The Boot 4.1.1 target still resolves 1.5.38 (no CVE). Override decision below.
- Pre-releases only (targets unchanged): Spring Boot 4.2.0-M2 / Framework 7.1.0-M2 / Security 7.2.0-M2, Hibernate 8.0.0.Beta3, Maven 4.0.0-rc-7.
- All 43 previous builds/runs were re-run from scratch in a fresh sandbox with identical results, plus 1 new build (B31). This includes the Angular 22 empty-UI trap (R10-R12) and the Jackson 2 bridge (R05/R09).

## Top 5 alerts
| # | component | why it matters | fix | details |
|---|---|---|---|---|
| 1 | Oracle Database 19.3.0.0.0 (PETCLINIC), no RU/OJVM | ALERT: behind Jul 2026 CPU + Aug/Sep 2026 CSPU; 26 DB/OJVM CVEs from 2026 advisories, 5 with CVSS >= 9 | RU 19.32 + OJVM RU + Aug/Sep 2026 CSPU; then CPU of 2026-10-20 | [#alert-oracle-database](impact-report.md#alert-oracle-database) |
| 2 | JDK 1.8.0_161 (petclinic-app01) | 32 Java SE CVEs from 2026 advisories alone; Boot 3/4 need Java 17+ | Temurin 25.0.4.1 in the Boot 4.1.1 release (proven B14) | [#alert-jdk](impact-report.md#alert-jdk) |
| 3 | Spring Boot 1.5.2 (petclinic-rest) | EOL since 2019; pins Spring 4.3 (Spring4Shell 9.8), Security 4.2, Jackson 2.8 (56 advisories) | Boot 4.1.1 via 2.7.18 -> 3.5.16 (main code + REST contract proven, B12/R05) | [#alert-spring-boot](impact-report.md#alert-spring-boot) |
| 4 | Apache Tomcat 8.5.11 embedded | EOL 2024; 58 advisories (13 CVSS >= 9); Boot 4.1.1 default 11.0.24 also has 3 CRITICAL | Boot 4.1.1 + pin tomcat.version 11.0.26 (proven R05/B14) | [#alert-apache-tomcat](impact-report.md#alert-apache-tomcat) |
| 5 | Python 3.6.8 (ops healthcheck) | EOL since 2021; blocks every patched library; PyYAML 3.12 yaml.load RCE (9.8) at healthcheck.py:20 | Python 3.14.7 + latest libs, 4 code fixes (B26/R07) | [#alert-python](impact-report.md#alert-python) |

Also CRITICAL: Angular 6.1.6 EOL ([#alert-angular](impact-report.md#alert-angular)), Node 10 CI, PyYAML 3.12, jackson-databind 2.8.7, Spring Framework 4.3.7, Spring Security 4.2.2, PostgreSQL JDBC (10.0), HSQLDB, Logback, dom4j, Springfox, Maven Wrapper 3.3.3, 27 build-toolchain packages — [all 49 alerts](impact-report.md#alerts). HIGH: ojdbc6 11.2 unsupported with DB 19c/JDK 17+ ([#alert-ojdbc](impact-report.md#alert-ojdbc)).

## Decisions needed from approvers — [details](impact-report.md#decisions)
1. Java 25 LTS (not 17) on petclinic-app01, in the same release as Spring Boot 4.1.1.
2. Boot path 1.5.2 -> 2.7.18 -> 3.5.16 -> 4.1.1 (2.7/3.5 = non-deployed transit steps).
3. Mandatory override Tomcat 11.0.26; optional overrides Hibernate 7.4.10, Jackson 2.22.3/3.2.3, Logback 1.6.4 (new).
4. Temporary deprecated spring-boot-jackson2 bridge until serializers are ported to Jackson 3.
5. Oracle patch window (RU 19.32 + OJVM + CSPUs, downtime) before 2026-10-20; 19c LTR vs 26ai; OL7 Extended Support vs OS move.
6. Angular: ng update per major vs re-scaffold; keep Eager CD + zone.js first; UI smoke test as release gate; Bootstrap 5 visuals.

## Recommended migration order — [details](impact-report.md#migration-order)
1. Oracle DB: RU 19.32 + OJVM + Aug/Sep 2026 CSPU now; Oct 2026 CPU next (no code change).
2. Ops script: Python 3.14.7 + latest libs + python-oracledb (independent of backend).
3. Freeze REST contract (1.5.2 captures) + UI smoke tests as shared gates.
4. Toolchain: Maven Wrapper 3.9.16, CI JDK 25, CI Node 24 LTS, drop jcenter.
5. petclinic-rest -> Boot 2.7.18 (transit, not deployed). (after 3, 4)
6. petclinic-rest -> Boot 3.5.16: jakarta, SecurityFilterChain, springdoc, JUnit 5 (transit). (after 5)
7. ONE release: Boot 4.1.1 + Temurin 25 on app server + ojdbc17 + Tomcat 11.0.26 + Jackson 2 bridge. (after 1, 6)
8. petclinic-angular -> 22.2.0 on Node 24 (Eager CD + zone.js, Bootstrap 5); deploy after step 7. (after 4, 7)
9. Port serializers to Jackson 3, drop the bridge; re-run contract/UI tests. (after 7, 8)
10. Oracle Linux 7.6 -> 9/10 (and 26ai evaluation) in its own window. (after 1)

## Counts
- Components scanned: 163 (46 production, 5 test, 112 build-toolchain) — outdated 163, EOL 24.
- CVEs production: 332 (CRITICAL 53 / HIGH 129 / MEDIUM 124 / LOW 26 / unscored 0); test 5; build toolchain 276 (CRITICAL 32 / HIGH 119 / MEDIUM 100 / LOW 11 / unscored 14).
- Builds/runs attempted: 44, passed: 11 (Boot 4.1.1 on JDK 17/25 with identical REST contract; Angular 22 build + UI; Python 3.14 latest libs). Oracle DB live test not attempted (no Docker daemon, MOS login).
