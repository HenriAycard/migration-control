---
name: regulated-sourcing
description: House rules for sourcing versions, security patches and CVEs in a regulated estate — which sources count as official, how to record a CVE, when to tag UNVERIFIED, how to name components and raise alerts. Use whenever you state a version, a patch level, a CVE, an end-of-life date or an alert in a report or plan.
---

# Regulated sourcing

Approvers (tech leads, security, auditors) must be able to re-check every claim from its source. These rules apply to every version, patch level, CVE, end-of-life date and alert you write.

## 1. Which sources count

Use the most authoritative source available, in this order. Details per ecosystem: [sources.md](sources.md).

1. **Vendor / project official page** — release notes, security advisories, end-of-life policy (e.g. Oracle Critical Patch Update pages, spring.io, angular.dev, python.org, nodejs.org).
2. **Official package registry metadata** — Maven Central `maven-metadata.xml`, npm registry, PyPI JSON API.
3. **Vulnerability databases** — NVD (`nvd.nist.gov/vuln/detail/<CVE>`), GitHub Security Advisories, OSV (`osv.dev`).

Blogs, forums, Stack Overflow, vendor marketing pages and AI-generated summaries are **never** a source. If only those exist, the claim is UNVERIFIED.

## 2. UNVERIFIED

Tag a claim `UNVERIFIED` (and say why in a few words) when:
- the official source requires a login you do not have (e.g. My Oracle Support patch numbers),
- sources disagree and you cannot resolve which is authoritative,
- the advisory has no CVSS score (severity `UNSCORED`), or
- you inferred it rather than read it.

Never drop an UNVERIFIED claim silently and never promote it to a fact.

## 3. Recording a CVE

Every CVE entry carries: `id`, `cvss` (number, or null if unscored), `severity` (CRITICAL ≥ 9.0, HIGH ≥ 7.0, MEDIUM ≥ 4.0, LOW > 0, UNSCORED), `fixed_in` (the first fixed version, from the advisory), `url` (NVD or the vendor advisory), `verified` (true only if you read the advisory in this run).

Count CVEs as **unique IDs**; an advisory listing several CVEs counts each once. GHSA or MAL IDs without a CVE alias are listed but counted separately.

## 4. Naming components

`component_key` is the product name **without version**, kebab-case, identical across runs: `oracle-database`, `spring-boot`, `apache-tomcat`, `jackson-databind`, `jdk`, `python`, `pyyaml`, `angular`, `nodejs`, `ojdbc`, `oracle-linux`. Reuse the key from the previous scan when one exists. One alert per `component_key` — never group several products in one alert.

## 5. Raising an alert

Raise an alert when any of these holds, and put the rule in the message:
- a CVE with CVSS ≥ 9.0 affects the deployed version,
- the product is end of life (vendor policy date passed),
- a database or runtime is behind the latest security patch (state how far: e.g. "~29 quarterly RUs behind"),
- a required driver/runtime combination is outside the vendor's support matrix.

Each alert: `severity`, `component_key`, one-paragraph `message` (what, since when, impact), `fix` (target version and mandatory intermediate steps), `sources` (official links only).

## 6. Evidence

Quote real command output for builds and checks; cite `file:line` only for lines you have read in this run. Dates come from the sandbox clock, never from memory.
