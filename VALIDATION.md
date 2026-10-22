# Required compilation tests

**A complete compilation test is required independently for Ubuntu 16.04, 18.04 and 20.04.** All three targets are currently unverified with this automation. Do not infer support from a static check, source preparation, another Ubuntu release, or a previous manual build.

For each target, run the script in a fresh matching Ubuntu container and record:

1. Repository commit, Ubuntu image digest, architecture, command/options, APT package versions and date.
2. Successful verified source downloads, original DSC signature checks and patch application.
3. Successful compilation of the full selected catalog. A core-only run validates only the core scope.
4. Three passing security PHPTs; successful actual mod_php Apache checks, including OOM worker replacement and multipart/session upload progress.
5. Passing load/functional smoke checks for all selected extensions. Record which external backends were actually exercised. Default checks use local Memcached/Redis; they do not provision MongoDB, AMQP, SMB, Solr, LDAP or application databases.
6. Package catalog completeness, matching target dependencies, source artifacts and checksum verification. If debug symbols are included, preserve the ELF Build ID checks.
7. Installation/upgrade and rollback tests on a separate clean matching VM with a representative application. Include an upgrade from the existing PPA packages and the extensions actually installed. Do not install mutually exclusive extensions together.

The build script covers source checks, compilation and bounded runtime smoke checks. It does not automatically perform the separate application-server upgrade/rollback test. Default success also does not claim a passing full historical PHPT suite; `--full-tests` is a separate stricter mode and legacy environmental failures must be investigated.

Publish evidence per target/scope, for example:

| Target | Catalog/scope | Builder commit | Result | Logs | Upgrade/application test |
| --- | --- | --- | --- | --- | --- |
| 16.04 amd64 | — | — | COMPILATION TEST REQUIRED | — | Required |
| 18.04 amd64 | — | — | COMPILATION TEST REQUIRED | — | Required |
| 20.04 amd64 | — | — | COMPILATION TEST REQUIRED | — | Required |

A PASS in `build-status.json` belongs only to that run and its selected checks. Update documentation manually with an evidence link; never turn it into an unconditional “secure” badge.

Initial release: scripts/documentation only, tagged as a preview. Binary/source release redistribution requires reviewing the respective upstream licenses first.
