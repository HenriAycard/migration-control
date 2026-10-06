# Official sources per ecosystem

| Ecosystem | Latest versions | Security patches / advisories | End of life |
|---|---|---|---|
| Java runtime | adoptium.net API (`api.adoptium.net/v3/info/available_releases`), oracle.com/java | Oracle Critical Patch Updates (`oracle.com/security-alerts/`) | oracle.com/java/technologies/java-se-support-roadmap.html, adoptium.net/support |
| Maven artifacts (Spring, Jackson, Tomcat, Hibernate, ojdbc…) | Maven Central `repo1.maven.org/maven2/<group>/<artifact>/maven-metadata.xml` | NVD, GitHub Security Advisories, OSV (`api.osv.dev/v1/query`, ecosystem `Maven`) | spring.io/projects/<project>#support (`api.spring.io/projects/<id>/generations`), tomcat.apache.org/whichversion.html |
| Oracle Database / JDBC | oracle.com/database, JDBC FAQ support matrix | Oracle Critical Patch Updates and Critical Security Patch Updates (`oracle.com/security-alerts/cpu<mon><yyyy>.html`, `cspu<mon><yyyy>.html`) | Oracle Lifetime Support Policy |
| Oracle Linux | oracle.com/linux | Oracle Linux errata (`linux.oracle.com/errata`) | Oracle Linux Extended Support datasheet |
| npm / Angular / Node.js | npm registry (`registry.npmjs.org/<pkg>`), angular.dev/reference/releases, nodejs.org/dist/index.json | GitHub Security Advisories, OSV (ecosystem `npm`) | angular.dev/reference/releases, github.com/nodejs/Release |
| Python / PyPI | python.org/downloads, PyPI JSON (`pypi.org/pypi/<pkg>/json`) | OSV (ecosystem `PyPI`), `pip-audit --vulnerability-service osv`, GitHub Security Advisories | devguide.python.org/versions |

When two official sources disagree (e.g. registry says a version exists but the vendor has not announced it), report the vendor statement and mention the discrepancy.
