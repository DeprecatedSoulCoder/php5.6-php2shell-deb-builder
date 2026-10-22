#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -Eeuo pipefail
[[ -f /.dockerenv ]] || { echo 'Run through build.sh in Docker.' >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8 TZ=Etc/UTC
export PHP56_KIT=/builder PHP56_WORK=/work PHP56_OUTPUT=/output
trap 'chown -R "${BUILDER_UID:-0}:${BUILDER_GID:-0}" /work /output' EXIT
# Package postinst scripts must not start services while building.
printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
chmod 755 /usr/sbin/policy-rc.d
mkdir -p /output/evidence
exec > >(tee -a /output/evidence/bootstrap.log) 2>&1
. /etc/os-release
case "${ID}:${VERSION_ID}" in ubuntu:16.04|ubuntu:18.04|ubuntu:20.04) ;; *) exit 2;; esac
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl gnupg gpgv \
  python3 build-essential devscripts equivs dpkg-dev debhelper \
  quilt patch xz-utils bzip2 fakeroot binutils apt-utils
if [[ "$VERSION_ID" == 16.04 ]]; then
  apt-get install -y --no-install-recommends debhelper/xenial-backports
fi
python3 /builder/scripts/build.py "$@"
