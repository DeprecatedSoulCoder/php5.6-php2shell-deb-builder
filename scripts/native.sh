#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Explicit native mode is for disposable matching Ubuntu systems only.
set -Eeuo pipefail
[[ "$EUID" == 0 ]] || { echo 'Native mode requires root.' >&2; exit 1; }
. /etc/os-release
[[ "${ID}" == ubuntu && "$1" == --ubuntu && "${VERSION_ID}" == "$2" ]] || {
  echo 'The native target must match the installed Ubuntu release.' >&2; exit 2;
}
case "$VERSION_ID" in 16.04|18.04|20.04) ;; *) exit 2;; esac
export DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8 TZ=Etc/UTC
mkdir -p "$PHP56_OUTPUT/evidence" "$PHP56_WORK" "$PHP56_CACHE"
exec > >(tee -a "$PHP56_OUTPUT/evidence/bootstrap.log") 2>&1
# Serialize native runs before temporarily replacing the service-start policy.
exec 9>/var/lock/php56-native-build.lock
flock -n 9 || { echo 'Another native PHP build is active.' >&2; exit 1; }
policy_backup="$(mktemp -d)"
if [[ -e /usr/sbin/policy-rc.d || -L /usr/sbin/policy-rc.d ]]; then
  mv /usr/sbin/policy-rc.d "$policy_backup/original"
fi
restore_policy() {
  rm -f /usr/sbin/policy-rc.d
  if [[ -e "$policy_backup/original" || -L "$policy_backup/original" ]]; then
    mv "$policy_backup/original" /usr/sbin/policy-rc.d
  fi
  rmdir "$policy_backup"
}
trap restore_policy EXIT
printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
chmod 755 /usr/sbin/policy-rc.d
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl gnupg gpgv \
  python3 build-essential devscripts equivs dpkg-dev debhelper \
  quilt patch xz-utils bzip2 fakeroot binutils apt-utils
if [[ "$VERSION_ID" == 16.04 ]]; then
  apt-get install -y --no-install-recommends debhelper/xenial-backports
fi
python3 "$PHP56_KIT/scripts/build.py" "$@"
