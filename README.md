# PHP 5.6.40 php2shell Debian package builder — preview

**USE AT YOUR OWN RISK.** Supplied as is, without warranties or certification. Verification, backups, compilation, installation, operation and distribution are the user's responsibility. Authors/contributors disclaim liability to the maximum extent permitted by applicable law. Read [DISCLAIMER.md](DISCLAIMER.md) and [LICENSE](LICENSE); no disclaimer guarantees absolute legal immunity.

Build Ubuntu `.deb` packages for PHP 5.6.40, **including Apache `libapache2-mod-php5.6`**, with the pinned community php2shell patch. Optional external extensions include Memcached, Redis, Imagick and the historical Ondřej PHP 5.6 extension catalog for Xenial.

**Every supported target requires a compilation test before use or publication. No target has been validated with this automation yet.**

| Target | Architecture | Status of this automation |
| --- | --- | --- |
| Ubuntu 16.04 / Xenial | amd64 | **COMPILATION TEST REQUIRED** |
| Ubuntu 18.04 / Bionic | amd64 | **COMPILATION TEST REQUIRED** |
| Ubuntu 20.04 / Focal | amd64 | **COMPILATION TEST REQUIRED** |

An earlier manual Xenial build is not a validation of this script. Passing Python/shell checks or source preparation is not a successful PHP compilation. Please keep these labels until complete build logs and runtime results exist for each target.

[Validation and release criteria](VALIDATION.md) · [Source provenance](PROVENANCE.md)

## Quick start

Requirements: Bash, a working Docker installation with Linux amd64 containers, internet access, and sufficient disk/RAM for a full PHP and C++ extension build. Start with 2 compiler jobs; gRPC can consume substantial RAM. Python 3 is needed on the host only for `--plan`.

Inspect the plan without downloads, package installation or compilation:

```bash
./build.sh --ubuntu all --plan
```

Build core PHP packages, including mod_php:

```bash
./build.sh --ubuntu 16.04 --core-only
```

Build core PHP plus Memcached, Redis and Imagick, automatically adding required extension dependencies:

```bash
./build.sh --ubuntu 18.04 --extensions memcached,redis,imagick
```

Build the full historical catalog separately for all three Ubuntu releases:

```bash
./build.sh --ubuntu all --jobs 2
```

Optional matching debug packages:

```bash
./build.sh --ubuntu 20.04 --debug
```

Run the original full core PHPT suite in addition to the required checks:

```bash
./build.sh --ubuntu 20.04 --core-only --full-tests
```

This option is deliberately strict: any unexpected PHPT failure stops the run. Legacy tests can fail for environmental reasons; investigate those failures instead of labeling them as passes. The default runs the three patch-specific PHPTs, Apache checks and the selected extension smoke checks. External PECL suites are logged by their historical recipes; they are **not** a complete passing integration suite. Some extensions need external services for deeper tests.

The first real build downloads the Ubuntu image and installs build dependencies **inside the container**. No PHP packages are installed on the host. No credentials or access to a private VM are needed. A target uses its own distribution's libraries; a Xenial `.deb` must not be reused on Bionic/Focal.

## What it does

1. Downloads pinned original signed Debian sources, including Sury's historical security patches.
2. Checks SHA-256, component sizes and original DSC signatures against the bundled public key.
3. Downloads the community patch at an exact Git commit and checks its SHA-256.
4. Applies it to the pinned Sury tree. Handles one known existing session guard difference; all fourteen resulting source files must match pinned hashes. Any other reject stops the run.
5. Builds native support packages, the PHP core and the requested PECL extensions in dependency order.
6. Pins each external extension to the exact patched `php5.6-common` version. Selects only the historical versioned runtime packages, excluding unrelated generic metapackages.
7. Runs the security PHPTs and an isolated Apache instance using the actual installed `libphp5.6.so`, including upload progress and OOM worker recovery checks. Tests external extensions in separate PHP processes; starts local Memcached/Redis only in the container.
8. Writes packages, rebuildable source packages, logs, an APT index, checksums and machine-readable status.

Default catalog: 39 core packages and 41 external extension packages. `--debug` adds matching historical debug package names. This is the **Xenial catalog rebuilt for each target**, not a claim that every package ever offered by the Bionic/Focal PPA is covered.

## Output and failures

```text
output/16.04/
  build-status.json       PASS only after the required checks complete
  package-catalog.json    Package names, versions, dependencies and hashes
  packages/               Runtime .debs and a flat Packages index
  sources/                Modified sources and original signed provenance
  debug/                  Optional matching debug .debs
  evidence/               Build, dependency, signature and runtime-test logs
  SHA256SUMS
```

Each target has an independent directory. `--output DIR` and `--work DIR` change the defaults. Use a dedicated output directory: the script replaces its previous package/source directories on a new run.

Build failures exit nonzero and record `FAIL`; partial packages can remain for diagnosis. **Only a completed `PASS` run is a candidate for further validation.** A PASS covers the checks listed in that run, not general application compatibility or all known vulnerabilities. The bootstrap log records early APT failures before the Python status file can be written; absence of PASS means incomplete/failed.

Completed package builds can be reused on rerun after verifying checksums and the script/options identity. Failed/stale builds start again from verified sources. Preserve `work/` for the cache, source trees and unstripped binaries; delete it to force a fresh build. A full matrix stops at the first failing target.

Before using artifacts, check their checksums:

```bash
cd output/16.04
sha256sum -c SHA256SUMS
```

Select the core/SAPI packages and extensions actually in use. Do not install every `.deb` indiscriminately: APCu/YAC/Xcache and Imagick/Gmagick include historical alternatives/conflicts. APT still needs matching Ubuntu repositories for system-library dependencies. Existing PHP extensions may need updating together because of exact `php5.6-common` dependencies. Validate an upgrade and rollback on a clone of the application server first.

The generated local APT index is unsigned. Publishing a production APT repository, signing releases, and automatic deployment are separate work; this project does not perform them.

## Build, verify and install: operator procedure

These steps belong to the operator. **Test on an isolated disposable VM matching the target before considering an application server.** All three Ubuntu versions still require real compilation tests. Commands below are examples for Ubuntu 20.04; substitute 16.04/18.04 consistently for those targets. Use Bash. No command in this documentation has been executed against your application server.

### 1. Obtain the scripts and compile

Clone the repository and inspect the build plan before starting a compilation:

```bash
git clone https://github.com/DeprecatedSoulCoder/php56-php2shell-deb-builder.git
cd php56-php2shell-deb-builder
./build.sh --ubuntu 20.04 --plan
./build.sh --ubuntu 20.04 --jobs 2
```

This builds the full runtime catalog. Use `--core-only` or `--extensions memcached,redis,imagick` for a narrower catalog; this must still include rebuilt counterparts for existing PHP 5.6 extensions you will upgrade. Check the process exit status, `output/20.04/build-status.json`, and all relevant logs in `evidence/`. A missing status or anything other than `PASS` is not an installable release. Preserve the exact builder commit and image/dependency identities. See [VALIDATION.md](VALIDATION.md).

### 2. Check the files on a matching isolated test VM

Transfer the repository and the complete `output/20.04/` directory to the test VM. Install Python 3 there if necessary. From the repository directory:

```bash
cat /etc/os-release
dpkg --print-architecture
php56_release="$PWD/output/20.04"
(cd "$php56_release" && sha256sum -c SHA256SUMS)
python3 -m json.tool "$php56_release/build-status.json"
```

Require matching Ubuntu **20.04 amd64** for this example. Checksums detect changes relative to the manifest; they are not an independent digital signature or proof that code is safe. Obtain the scripts/manifests through a trusted channel and review source provenance.

Select the Apache SAPI, CLI and Memcached, plus any PHP 5.6 packages already installed:

```bash
php56_selection="$PWD/php56-selected-debs.txt"
python3 scripts/check-debs.py "$php56_release" \
  --packages libapache2-mod-php5.6 php5.6-cli php5.6-memcached \
  --include-installed --selection-file "$php56_selection"
```

**Stop if this command fails.** It checks completed build status, OS/architecture, runtime package hashes and embedded package name/version/architecture. It adds local dependencies and currently installed PHP 5.6 packages to the selection. Missing rebuilt extensions, installed debug packages or conflicts require a reviewed upgrade plan; the checker never removes or installs anything. It preserves a newer installed support package instead of forcing a downgrade. Full dependency/alternative resolution remains APT's job.

Inspect the selection, metadata and package file lists:

```bash
mapfile -t php56_debs < "$php56_selection"
printf '%s\n' "${php56_debs[@]}"
for php56_deb in "${php56_debs[@]}"; do
  dpkg-deb --field "$php56_deb" Package Version Architecture Depends Pre-Depends Conflicts Breaks
  dpkg-deb --contents "$php56_deb"
done
```

Review maintainer scripts before installing; extraction does not execute them:

```bash
php56_controls="$(mktemp -d)"
for php56_deb in "${php56_debs[@]}"; do
  php56_name="$(dpkg-deb --field "$php56_deb" Package)"
  dpkg-deb --control "$php56_deb" "$php56_controls/$php56_name"
done
printf 'Review control/postinst/prerm files under: %s\n' "$php56_controls"
```

Refresh the test VM's matching Ubuntu repositories and **simulate** the chosen installation:

```bash
sudo apt-get update
sudo apt-get -s --no-install-recommends install "${php56_debs[@]}"
```

The simulation must resolve all dependencies without unplanned removals or downgrades. Do not force installation using `--force-depends`, `--allow-unauthenticated` or blanket `dpkg -i *.deb`. If APT proposes removing existing PHP extensions, rebuild/include them or consciously plan their replacement first. Never mix Ubuntu releases. A successful simulation does not run maintainer scripts or prove runtime/application compatibility.

### 3. Back up, then install on the test VM

Create a **restorable VM snapshot** and application/database backups before changing packages. Keep the old `.deb` versions and record the installed state. For a server already running PHP and Apache:

```bash
dpkg-query -W > php56-packages-before.txt
apt-mark showmanual > php56-manual-packages-before.txt
sudo tar -C / -czf "$PWD/php56-config-before.tgz" etc/php etc/apache2
```

The configuration archive is not a full system/database backup. Check that backups can be restored. With the same reviewed selection and a maintenance window:

```bash
sudo apt-get --no-install-recommends install "${php56_debs[@]}"
sudo dpkg --audit
php5.6 -v
php5.6 --ini
php5.6 -m
php5.6 --ri memcached
sudo apache2ctl configtest
sudo apache2ctl -M
```

Do not proceed after an error. Check exact installed package versions using `dpkg-query -W 'php5.6*' libapache2-mod-php5.6`, not just `php -v`, which may refer to another PHP version. `php5.6 --ri memcached` applies only when Memcached was selected. Check `ldd /usr/lib/apache2/modules/libphp5.6.so` for missing libraries.

For mod_php, Apache must load `php5_module` under `mpm_prefork_module`. Resolve any active conflicting PHP module/MPM on the clone. Where this deployment intentionally uses PHP 5.6 mod_php and `mpm_event` is the conflicting MPM, the usual change is:

```bash
sudo a2dismod mpm_event
sudo a2enmod mpm_prefork
sudo a2enmod php5.6
sudo apache2ctl configtest
```

Adapt this to the actual configuration; do not blindly disable modules serving other sites. Only after configuration validation succeeds:

```bash
sudo systemctl restart apache2
sudo systemctl status apache2 --no-pager
```

CLI checks alone do not prove Apache is using the new module. On the **isolated test VM only**, point `php56_docroot` and the HTTP Host to the actual test virtual host. Create a short-lived minimal probe, request it locally and remove it immediately:

```bash
php56_docroot=/var/www/html
php56_probe="$(sudo mktemp "$php56_docroot/php56-check-XXXXXX.php")"
printf '%s\n' '<?php header("Content-Type: application/json"); echo json_encode(array("version"=>PHP_VERSION,"sapi"=>PHP_SAPI,"memcached"=>extension_loaded("memcached")));' \
  | sudo tee "$php56_probe" >/dev/null
sudo chmod 644 "$php56_probe"
curl --fail --silent --show-error -H 'Host: localhost' "http://127.0.0.1/$(basename "$php56_probe")"
sudo rm -- "$php56_probe"
```

Require `sapi: apache2handler` and a PHP version containing the intended `php2shell` build revision. Require `memcached: true` if selected. A JSON response from another SAPI/version is not a pass; returned PHP source means the handler is not working. This probe is a basic runtime check, not a CVE test or a security certification. Inspect Apache/PHP logs and exercise real application uploads, sessions, database access, cache serialization and background jobs. Check FPM/CGI separately if those SAPIs are deployed.

### 4. Rehearse rollback and decide about deployment

Restore the VM snapshot and verify the old application and services recover. Package downgrades alone do not restore configuration, alternatives, module activation, databases or application state. If planning a package-based rollback, retain every previous package/dependency version, simulate the entire downgrade set and test it independently first; never rely on a single generic downgrade command.

Repeat the complete compilation, installation and rollback procedure independently for **16.04, 18.04 and 20.04**. Document the exact tested scope and evidence before changing the compatibility table. Only the operator can decide whether the observed results justify installing on their own servers; responsibility for that decision and its consequences remains with them, subject to applicable law.

## GitHub workflows

* `checks.yml`: shell/Python syntax, source-lock consistency, dependency selection and failure-path tests. Runs on pushes and pull requests; **does not compile PHP**.
* `build.yml`: explicitly manual (`workflow_dispatch`) Ubuntu matrix. It compiles only when a maintainer starts it. Each job uploads logs/status; it does not publish a binary release or mark the compatibility table as verified.

For initial publication use a preview tag such as `v0.1.0-preview`. Keep all three targets marked **compilation test required**. Follow [VALIDATION.md](VALIDATION.md) before making support claims or sharing compiled packages.

## Scope and licenses

This is a community emergency build tool for obsolete PHP/Ubuntu systems. It applies the selected patch; it is not an official PHP release, a complete security audit or a replacement for migration. The upstream repository describes additional uncovered attack chains; do not advertise this as fixing every PHP vulnerability.

The original automation in this repository is MIT licensed. PHP, extensions, Debian packaging and the downloaded patch retain their own terms. A standalone LICENSE was not present in the pinned patch repository snapshot. The patch is fetched at runtime and is **not vendored here**. Clarify its redistribution terms before publishing patch-bearing source or binary releases. See [PROVENANCE.md](PROVENANCE.md).
