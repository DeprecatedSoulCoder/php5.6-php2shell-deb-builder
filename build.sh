#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -Eeuo pipefail
kit_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
target=""; jobs=2; output="$PWD/output"; work="$PWD/work"; extra=()
usage() {
  cat <<'EOF'
Usage: ./build.sh --ubuntu 16.04|18.04|20.04|all [options]
  --core-only          Build PHP and mod_php without external PECL extensions
  --extensions LIST    Comma-separated names (e.g. memcached,redis,imagick)
  --jobs N             Compiler jobs per package; default 2
  --output DIR         Results; default ./output
  --work DIR           Cached sources and build trees; default ./work
  --debug              Also build matching historical debug packages
  --full-tests         Run the original core PHPT suite; failures block release
  --plan               Print the plan without Docker, downloads or compilation

All targets REQUIRE A COMPILATION TEST. No target is pre-certified.
Requires Docker with Linux amd64 containers. Builds run only when invoked.
EOF
}
while (($#)); do
  case "$1" in
    --ubuntu|--jobs|--output|--work|--extensions)
      (($# >= 2)) || { usage >&2; exit 2; }
      case "$1" in
        --ubuntu) target="$2";; --jobs) jobs="$2";;
        --output) output="$2";; --work) work="$2";;
        --extensions) extra+=(--extensions "$2");;
      esac; shift 2;;
    --core-only|--debug|--full-tests|--plan) extra+=("$1"); shift;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2;;
  esac
done
case "$target" in 16.04|18.04|20.04) targets=("$target");; all) targets=(16.04 18.04 20.04);;
  *) usage >&2; exit 2;; esac
[[ "$jobs" =~ ^[1-9][0-9]*$ ]] || { echo 'Invalid --jobs' >&2; exit 2; }
if [[ " ${extra[*]} " == *" --plan "* ]]; then
  for version in "${targets[@]}"; do
    python3 "$kit_dir/scripts/build.py" --ubuntu "$version" --jobs "$jobs" "${extra[@]}"
  done
  exit
fi
command -v docker >/dev/null || { echo 'Install Docker first. See README.md.' >&2; exit 1; }
docker info >/dev/null
mkdir -p -- "$output" "$work/cache"
output="$(cd -- "$output" && pwd -P)"; work="$(cd -- "$work" && pwd -P)"
# Docker --mount treats commas as delimiters. Refuse ambiguous mount syntax.
[[ "$kit_dir$output$work" != *','* ]] || { echo 'Paths cannot contain commas.' >&2; exit 2; }
for version in "${targets[@]}"; do
  mkdir -p -- "$work/$version" "$output/$version"
  # No ports, host filesystem, Docker socket or credentials are exposed to the builder.
  docker run --rm --init --platform linux/amd64 \
    --mount "type=bind,src=$kit_dir,dst=/builder,readonly" \
    --mount "type=bind,src=$work/cache,dst=/cache" \
    --mount "type=bind,src=$work/$version,dst=/work" \
    --mount "type=bind,src=$output/$version,dst=/output" \
    --env "BUILDER_UID=$(id -u)" --env "BUILDER_GID=$(id -g)" \
    "ubuntu:$version" /bin/bash /builder/scripts/container.sh \
    --ubuntu "$version" --jobs "$jobs" "${extra[@]}"
done
