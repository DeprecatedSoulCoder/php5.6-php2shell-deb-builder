# Native validation: 2026-10-22

Full native builds and bounded installation tests passed on Ubuntu 16.04 and 18.04 amd64. These runs used the actual Apache `libapache2-mod-php5.6` handler. Ubuntu 20.04 and Docker mode remain unverified by this report.

| Check | Ubuntu 16.04 | Ubuntu 18.04 |
| --- | --- | --- |
| Build mode / compiler jobs | Native / 2 | Native / 4 |
| Original signed source packages verified and built | 45 / PASS | 45 / PASS |
| Runtime packages produced | 82 | 82 |
| Matching debug packages produced | 78 | 78 |
| External extensions tested individually | 41 / PASS | 41 / PASS |
| Patch-specific PHPTs | 3 passed, 0 skipped/failed | 3 passed, 0 skipped/failed |
| Apache core regression checks at build time | 7 / PASS | 7 / PASS |
| Compatible runtime/support packages installed | 77 | 77 |
| Matching debug packages installed | 73 | 73 |
| External extensions tested together in CLI and Apache | 36 each / PASS | 36 each / PASS |
| Installed dynamic module directives present in CLI and Apache | 95 / PASS | 95 / PASS |
| Apache regression checks with the selected extensions loaded | 7 / PASS | 7 / PASS |
| System Apache HTTP handler and mapped module hash | PASS | PASS |
| APT simulation / package versions / dpkg audit | PASS | PASS |
| All output checksums | PASS | PASS |

The runtime output contains 39 core packages, 41 external extensions and two support packages (`php-common`, `libtidy5deb1`). The 78 debug packages include 77 packages with matching ELF Build IDs and the `php5.6-dbg` compatibility metapackage. Each target therefore produced 160 `.deb` files. The final compatible installation contains 150 of those files, including debug packages.

Machine-readable evidence: [Ubuntu 16.04](ubuntu-16.04.json), [Ubuntu 18.04](ubuntu-18.04.json). These files include runtime/debug package versions and hashes, source signature results, all extension check results, module lists, selected toolchain/library versions and the conflict reproduction. Raw build/install logs and failed-attempt logs are retained privately; host identifiers, addresses, private paths and credentials are not included in this evidence set. No binaries were published.

## Baselines and revisions

The 16.04 VM was reused. Existing PHP/helper packages were purged after package/configuration backups; build dependencies from previous work were retained. This was a PHP-clean baseline, not a fresh OS reinstall.

The newly supplied 18.04 VM initially had no PHP packages. A first attempt installed build dependencies and core packages before failing. PHP/helper packages were purged before the corrected successful build; build dependencies were retained.

Both successful builds used the build recipes at `84a43eaf09cf9e19baf01ea2a7db4fe4ec3d67ed`. Subsequent commits changed validation/documentation without changing `scripts/`, `tools/` or `assets/`. The final installation validator was `a7a17e2ddccc59fc78e27557c719c03777b14129`. Commands and build cache identities are recorded in each JSON file. Original sources and the community patch remain pinned as described in [PROVENANCE.md](../../../PROVENANCE.md).

Failed attempts exposed and led to fixes for the signed Tidy source epoch, a PECL build-dependency replacement that consumed the next control-field newline, Bash 4.3 empty arrays under `set -u`, evidence-directory creation on Python 3.5, and Apache test process-group isolation during shutdown. These were corrected before the final passing runs; failed-attempt logs were retained.

Source signature/hash checks passed for all 45 inputs. After compilation, the generated PHP source package was independently extracted and all 14 patched source-file hashes matched the pinned manifest. The known Sury session guard adjustment was retained.

## Compatible selection and observed conflicts

All 41 external extensions compiled and passed their individual bounded smoke checks. Five packages were excluded from the final concurrent installation:

| Excluded package | Selected alternative or reason |
| --- | --- |
| `php5.6-yac` | APCu selected; package conflict with the APCu virtual package. |
| `php5.6-xcache` | APCu and OPcache selected as the cache alternatives. |
| `php5.6-gmagick` | Imagick selected; package conflict with the Imagick virtual package. |
| `php5.6-smbclient` | MongoDB selected. The default MongoDB-then-SMBClient load order caused a shutdown SIGSEGV after creating/freeing an SMBClient state on both targets. |
| `php5.6-uploadprogress` | Core session upload progress selected. PECL Uploadprogress replaces the multipart callback; the core session progress-counter regression failed with it loaded on both targets. |

APT resolved the initial package-compatible selection without removals, but did not detect the two runtime conflicts. The final selection passed both CLI and Apache tests after SMBClient and PECL Uploadprogress were removed. Their packages remain available as separately built artifacts; they are not validated for the final concurrent selection.

The MongoDB/SMBClient minimal reproduction included the required JSON module. Either extension alone exited successfully. MongoDB followed by SMBClient reproduced signal 11; the reverse order exited successfully in that minimal test. A debugger trace on 16.04 reached SASL cleanup from MongoDB shutdown. This does not establish a validated load-order workaround or a complete root-cause fix.

For Uploadprogress, the counter regression failed with all 37 otherwise selected modules loaded, then passed with that PECL extension omitted. The final 36-extension installation repeated all seven Apache checks successfully on both targets. No check was waived to obtain PASS.

## Tests and remaining limits

The Apache checks verify the mapped `libphp5.6.so`, patch symbol, version/SAPI/configuration, multipart uploads and hashes, session object/custom payload round-trips and progress counters, reserved/corrupt session rejection, 40 uploads in one worker, chunked `post_max_size` enforcement, and worker recovery after a bounded PHP OOM. A separate HTTP request verified the ordinary system Apache service used the expected module file and hash. Temporary HTTP probes were removed.

Local Memcached round-trips passed with PHP, Igbinary, JSON, JSON-array and MessagePack serializers; Redis round-trips passed with Igbinary. The other extension checks cover selected functions, constructors and local operations. They do not provision external MongoDB/SMB/AMQP/SQL/Solr or other application backends.

Apache, PHP-FPM, Memcached and Redis services were active at completion. FPM configuration was checked; application requests through FPM/CGI were not covered. The complete historical PHP PHPT suite was not run. No representative application, independent PPA upgrade, production workload, snapshot restoration or rollback was tested. Neither run establishes complete CVE coverage or production readiness.

Repeat the compilation and installation checks for each target/environment and complete the application/upgrade/rollback work required by [VALIDATION.md](../../../VALIDATION.md). Responsibility for use remains with the operator under the repository disclaimer/license.
