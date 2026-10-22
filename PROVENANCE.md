# Source provenance and patch scope

No PHP sources, third-party patch contents or generated binary packages are vendored in this repository.

* PHP baseline: `php5.6` source version `5.6.40-50+ubuntu16.04.1+deb.sury.org+1`, retaining the historical Sury patch stack. [Debian PHP packaging](https://salsa.debian.org/php-team/php) and [PHP 5.6.40 release](https://www.php.net/releases/5_6_40.php).
* Upstream PHP original tarball SHA-256: `1369a51eee3995d7fbd1c5342e5cc917760e276d561595b6052b21ace2656d1c`.
* Community patch: [Anton-Barinov/php2shell-patches at the pinned commit](https://github.com/Anton-Barinov/php2shell-patches/tree/add11c4715fbd62c2a7727136570b7e1d38a22cb), file `patches/php-5.6-enhanced-universal.patch`.
* Patch SHA-256: `35c8fb03fb6503d0182fa9964dad6c701a7797cb654593fcf7bd5183e8cee1ba`.
* Original DSC signing key fingerprint: `6A1AAD7AE5B401C6E259A7B257067BAA1314C7FC` (Ondřej Surý automated upload key). The public key is bundled; no private key is present.
* Original source descriptors/components: individually pinned in `assets/sources.lock.json` (45 source packages: core, 41 extensions, three bootstrap sources). Original descriptors have detached/cleartext signature verification via a dedicated GPG keyring. The source mirror's APT index is not used as a trust anchor.
* Historical package names: `assets/packages.lock.json`, derived from the deleted Xenial amd64 publications of [the Ondřej PHP PPA](https://launchpad.net/~ondrej/+archive/ubuntu/php). The same catalog is rebuilt natively on each target; this does not reconstruct every Bionic/Focal PPA package.

The enhanced patch was chosen to preserve upload progress. Its application has one documented Sury compatibility adjustment: retaining the pre-existing `if (progress->data)` guard while replacing the obsolete zval counter access. All fourteen final affected files are checked against `assets/patched-files.lock.json`; unexpected drift or any extra reject stops the build.

These pins identify the selected inputs; they do not imply bit-for-bit reproducible builds. Ubuntu base image tags and distro dependency repositories can change. Record the actual image digest and dependency versions for a release. The historical source mirror is a third-party availability dependency; checksum/signature failures are not bypassed.

The upstream patch describes CVE-2026-109618/CVE-2026-109619 backports and additional limitations, including uncovered attack chains. This builder checks a bounded set of regressions, not completeness of the security fix.

## Licenses

The MIT license in this repository covers its original scripts, tests and documentation. It does not relicense PHP, PECL sources, Debian packaging or the downloaded patch. Their copyright/license notices remain in the downloaded source packages.

A standalone LICENSE was not found at the pinned community patch snapshot. This project therefore fetches that patch at runtime instead of copying it into this repository. Confirm the applicable upstream terms before redistributing patch-bearing source or binary releases. [GitHub's licensing documentation](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository) explains why a public repository alone does not establish an open-source license.
