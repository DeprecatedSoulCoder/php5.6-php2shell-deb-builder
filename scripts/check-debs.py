#!/usr/bin/env python3
"""Read-only package checks on the matching target VM; never installs packages.

SPDX-License-Identifier: MIT
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


def check(directory, requested, include_installed):
    status = json.loads((directory / 'build-status.json').read_text())
    if status.get('status') != 'PASS':
        raise ValueError('No completed PASS build; do not use partial artifacts')
    release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    if release.get('ID', '').strip('"') != 'ubuntu' or release.get('VERSION_ID', '').strip('"') != status['ubuntu']:
        raise ValueError('This VM must run the same Ubuntu release as the packages')
    arch = subprocess.check_output(['dpkg', '--print-architecture']).decode().strip()
    records = json.loads((directory / 'package-catalog.json').read_text())
    by_name = {record['name']: record for record in records}
    if len(by_name) != len(records):
        raise ValueError('Duplicate package records')
    for record in records:
        filename = record['filename']
        if Path(filename).name != filename:
            raise ValueError('Unsafe package filename')
        path = directory / 'packages' / filename
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != record['sha256']:
            raise ValueError('Checksum mismatch: ' + filename)
        data = subprocess.check_output(['dpkg-deb', '-f', str(path), 'Package', 'Version', 'Architecture']).decode()
        fields = dict(line.split(': ', 1) for line in data.splitlines() if ': ' in line)
        if (fields.get('Package') != record['name'] or fields.get('Version') != record['version']
                or fields.get('Architecture') not in ('all', arch)
                or fields.get('Architecture') != record['architecture']):
            raise ValueError('Package metadata/architecture mismatch: ' + filename)
    selected = set(requested)
    if include_installed:
        data = subprocess.check_output(['dpkg-query', '-W', '-f', '${binary:Package}\t${db:Status-Abbrev}\n']).decode()
        for line in data.splitlines():
            name, state = line.split('\t', 1)
            name = name.split(':')[0]
            if state.startswith('ii') and (name.startswith('php5.6') or name in ('libapache2-mod-php5.6', 'libphp5.6-embed')):
                if name.endswith(('-dbg', '-dbgsym')):
                    raise ValueError('Installed debug packages need a matching separate upgrade plan: ' + name)
                selected.add(name)
    pending = list(selected)
    while pending:
        name = pending.pop()
        if name not in by_name:
            raise ValueError('Missing rebuilt package for the requested/installed set: ' + name)
        # Add local dependencies; APT is responsible for complete alternative/version resolution.
        relations = by_name[name].get('depends', '') + ', ' + by_name[name].get('pre_depends', '')
        for dependency in re.findall(r'(?:^|[,|])\s*([a-z0-9+.-]+)', relations):
            if dependency in by_name and dependency not in selected:
                if by_name[dependency].get('role') == 'support':
                    # Keep a newer installed support package instead of forcing a downgrade.
                    current = subprocess.run(['dpkg-query', '-W', '-f', '${db:Status-Abbrev}\t${Version}', dependency],
                                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                    if current.returncode == 0:
                        state, installed_version = current.stdout.decode().split('\t', 1)
                        if state.startswith('ii') and subprocess.call(
                                ['dpkg', '--compare-versions', installed_version, 'ge', by_name[dependency]['version']]) == 0:
                            continue
                selected.add(dependency)
                pending.append(dependency)
    return [str((directory / 'packages' / by_name[name]['filename']).resolve()) for name in sorted(selected)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--packages', nargs='+', required=True)
    parser.add_argument('--include-installed', action='store_true')
    parser.add_argument('--selection-file', type=Path, required=True)
    args = parser.parse_args()
    # Remove a stale selection so a failed check cannot accidentally reuse it.
    if args.selection_file.exists():
        args.selection_file.unlink()
    files = check(args.directory.resolve(), args.packages, args.include_installed)
    args.selection_file.write_text(''.join(path + '\n' for path in files))
    print('Integrity, metadata and target checks passed for the runtime catalog.')
    print('%d packages selected; APT simulation and real application tests are still required.' % len(files))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        sys.exit(1)
