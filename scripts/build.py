#!/usr/bin/env python3
"""Pinned PHP 5.6 Debian builds. Python 3.5+; Docker or explicit native mode.

SPDX-License-Identifier: MIT
"""
import argparse
import difflib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from email.utils import formatdate

KIT = Path(__file__).resolve().parent.parent
ASSETS = KIT / 'assets'
PATCH_COMMIT = 'add11c4715fbd62c2a7727136570b7e1d38a22cb'
PATCH_SHA256 = '35c8fb03fb6503d0182fa9964dad6c701a7797cb654593fcf7bd5183e8cee1ba'
PATCH_URL = ('https://raw.githubusercontent.com/Anton-Barinov/php2shell-patches/'
             + PATCH_COMMIT + '/patches/php-5.6-enhanced-universal.patch')
FINGERPRINT = '6A1AAD7AE5B401C6E259A7B257067BAA1314C7FC'
BUILD_REVISION = 'php2shell20261022.2'
SECURITY_TESTS = [
    'ext/session/tests/rfc1867_no_user_code.phpt',
    'ext/session/tests/rfc1867_incomplete_class_reserved_props.phpt',
    'ext/standard/tests/serialize/incomplete_class_raw_payload_markers.phpt',
]
SOURCES = {r['source']: r for r in json.loads((ASSETS / 'sources.lock.json').read_text())}
CATALOG = json.loads((ASSETS / 'packages.lock.json').read_text())
PATCHED_FILES = json.loads((ASSETS / 'patched-files.lock.json').read_text())
# Required headers/runtime modules; these edges also determine build order.
EDGES = {'php-igbinary': ['php-apcu'], 'php-memcached': ['php-igbinary', 'php-msgpack'],
         'php-redis': ['php-igbinary'], 'php-pecl-http': ['php-propro', 'php-raphf']}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save(path, data):
    temporary = Path(str(path) + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def run(command, cwd=None, log=None, env=None):
    print('+ ' + ' '.join(map(str, command)), flush=True)
    command = list(map(str, command))
    if log:
        with Path(log).open('w') as stream:
            code = subprocess.call(command, cwd=str(cwd) if cwd else None,
                                   stdout=stream, stderr=subprocess.STDOUT, env=env)
        if code:
            print(Path(log).read_text(errors='replace')[-12000:], file=sys.stderr)
            raise RuntimeError('Command failed (%d); see %s' % (code, log))
    else:
        subprocess.check_call(command, cwd=str(cwd) if cwd else None, env=env)


def fetch(url, path, digest, size=None):
    path = Path(path)
    if path.exists() and sha(path) == digest and (size is None or path.stat().st_size == size):
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(str(path) + '.part')
    run(['curl', '--fail', '--location', '--proto', '=https', '--tlsv1.2',
         '--retry', '3', '--connect-timeout', '30', '--max-time', '600',
         '--output', temporary, url])
    if sha(temporary) != digest or (size is not None and temporary.stat().st_size != size):
        temporary.unlink()
        raise RuntimeError('Checksum/size mismatch: ' + url)
    temporary.replace(path)
    return path


def download_source(name, cache, keyring, evidence):
    record = SOURCES[name]
    directory = cache / name
    dsc = fetch(record['url'] + record['dsc'], directory / record['dsc'], record['dsc_sha256'])
    run(['gpgv', '--keyring', keyring, dsc], log=evidence / (name + '-signature.log'))
    for component in record['files']:
        filename = component['filename']
        if Path(filename).name != filename or filename in ('.', '..'):
            raise RuntimeError('Unsafe source filename')
        fetch(record['url'] + filename, directory / filename,
              component['sha256'], component['size'])
    return dsc


def version(name, ubuntu):
    return SOURCES[name]['version'].replace('+ubuntu16.04.1', '+ubuntu' + ubuntu + '.1') + '+' + BUILD_REVISION


def changelog(tree, name, ubuntu):
    release = {'16.04': 'xenial', '18.04': 'bionic', '20.04': 'focal'}[ubuntu]
    path = tree / 'debian/changelog'
    path.write_text('%s (%s) %s; urgency=high\n\n'
                    '  * Local PHP 5.6 php2shell build; see build provenance.\n\n'
                    ' -- Local PHP Builder <builder@localhost>  %s\n\n%s' %
                    (name, version(name, ubuntu), release, formatdate(localtime=False), path.read_text()))


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Pinned recipe changed; expected one occurrence of: ' + repr(old))
    return text.replace(old, new, 1)


def apply_core_patch(tree, patch, evidence):
    """Resolve the single known Sury guard difference, then record a quilt patch.

    Every resulting file must match its independently pinned post-patch hash.
    An arbitrary reject or a missing test is a hard error.
    """
    originals = {name: (tree / name).read_bytes() if (tree / name).exists() else None
                 for name in PATCHED_FILES}
    log = evidence / 'patch-application.log'
    with log.open('w') as stream:
        code = subprocess.call(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)],
                               cwd=str(tree), stdout=stream, stderr=subprocess.STDOUT)
    rejects = list(tree.rglob('*.rej'))
    expected = tree / 'ext/session/session.c.rej'
    if code != 1 or rejects != [expected] or log.read_text().count('FAILED') != 2:
        # GNU patch reports both the failed hunk and its summary.
        raise RuntimeError('Unexpected patch result. See ' + str(log))
    session = tree / 'ext/session/session.c'
    old = '\t' * 6 + 'Z_LVAL_P(progress->post_bytes_processed) = data->post_bytes_processed;'
    new = '\t' * 6 + 'progress->post_bytes_processed = data->post_bytes_processed;'
    session.write_text(replace_once(session.read_text(), old, new))
    for name, digest in PATCHED_FILES.items():
        if sha(tree / name) != digest:
            raise RuntimeError('Unexpected patched source: ' + name)
    # Recreate a clean, applicable quilt patch while retaining all original Sury patches.
    diff = []
    for name, original in sorted(originals.items()):
        changed = (tree / name).read_bytes()
        before = (original or b'').decode('latin1').splitlines(True)
        after = changed.decode('latin1').splitlines(True)
        diff.extend(difflib.unified_diff(before, after, fromfile='a/' + name, tofile='b/' + name))
        if original is None:
            (tree / name).unlink()
        else:
            (tree / name).write_bytes(original)
    for backup in list(tree.rglob('*.orig')) + rejects:
        # Only patch-created backups, not source files named *.orig, are removed.
        if backup == expected or str(backup.relative_to(tree))[:-5] in PATCHED_FILES:
            backup.unlink()
    name = '0169-php2shell-enhanced.patch'
    (tree / 'debian/patches' / name).write_bytes(''.join(diff).encode('latin1'))
    with (tree / 'debian/patches/series').open('a') as stream:
        stream.write('\n' + name + '\n')
    run(['dpkg-source', '--before-build', tree], log=evidence / 'quilt-application.log')
    for name, digest in PATCHED_FILES.items():
        if sha(tree / name) != digest:
            raise RuntimeError('Quilt patch validation failed: ' + name)


def adapt_core(tree, patch, ubuntu, full_tests, evidence):
    apply_core_patch(tree, patch, evidence)
    rules = tree / 'debian/rules'
    text = rules.read_text()
    text = replace_once(text, '\t./buildconf --force\n',
                        '\tgrep -q zend_mm_safe_error_ex Zend/zend_alloc.c\n'
                        '\t./buildconf --force\n\ttouch ext/standard/var_unserializer.c\n')
    text = text.replace('cgi-build/sapi/php-cgi', 'cgi-build/sapi/cgi/php-cgi')
    gate = ('\ttest -x cli-build/sapi/cli/php\n\ttest -x cgi-build/sapi/cgi/php-cgi\n'
            + ''.join('\ttest -f ' + test + '\n' for test in SECURITY_TESTS))
    gate += ('\tTEST_PHP_EXECUTABLE=$(CURDIR)/cli-build/sapi/cli/php '
             'TEST_PHP_CGI_EXECUTABLE=$(CURDIR)/cgi-build/sapi/cgi/php-cgi '
             'NO_INTERACTION=1 REPORT_EXIT_STATUS=1 $(CURDIR)/cli-build/sapi/cli/php '
             '-n run-tests.php -n ' + ' '.join(SECURITY_TESTS)
             + ' > security-test-results.txt 2>&1 || { cat security-test-results.txt; exit 1; }\n'
             '\tcat security-test-results.txt\n'
             '\tgrep -Eq "^Tests passed[[:space:]]*:[[:space:]]*3[[:space:]]" security-test-results.txt\n'
             '\tgrep -Eq "^Tests skipped[[:space:]]*:[[:space:]]*0[[:space:]]" security-test-results.txt\n')
    text = replace_once(text, 'override_dh_auto_test-arch: test-results.txt\n',
                        'override_dh_auto_test-arch: test-results.txt\n' + gate)
    if not full_tests:
        text = replace_once(text, 'RUN_TESTS := yes', 'RUN_TESTS := no')
    else:
        text = 'export REPORT_EXIT_STATUS=1\n' + text
        text = replace_once(text, '$$extensions | \\\n\ttee test-results.txt',
                            '$$extensions > test-results.txt 2>&1 || { cat test-results.txt; exit 1; }\n'
                            '\tcat test-results.txt')
    rules.write_text(text)
    changelog(tree, 'php5.6', ubuntu)


def adapt_pecl(tree, name, ubuntu, core_version):
    rules = tree / 'debian/rules'
    text = re.sub(r'^\s*(?:export )?(?:DH_PHP_VERSIONS_OVERRIDE|PHP_DEFAULT_VERSION_OVERRIDE)\s*[:?+]?=.*\n',
                  '', rules.read_text(), flags=re.M)
    needle = 'include /usr/share/dh-php/pkg-pecl.mk'
    text = replace_once(text, needle, 'DH_PHP_VERSIONS_OVERRIDE := 5.6\n'
                        'PHP_DEFAULT_VERSION_OVERRIDE := 5.6\n' + needle)
    if name == 'php-zstd':
        text = text.replace('--with-libzstd', '--without-libzstd')
    rules.write_text(text)
    # Source templates must change together with generated control files.
    for control in [tree / 'debian/control', tree / 'debian/control.in']:
        if not control.exists():
            continue
        text = control.read_text()
        text = re.sub(r'\bphp-all-dev\s*(?:\([^)]*\))?', 'php5.6-dev', text)
        text = re.sub(r'\bphp-([a-z0-9-]+)-all-dev\s*(?:\([^)]*\))?', r'php5.6-\1', text)
        text = re.sub(r'\bphp-(mbstring|curl|xml)\b', r'php5.6-\1', text)
        if ubuntu == '16.04':
            text = text.replace('libidn2-dev', 'libidn2-0-dev')
        if name == 'php-zstd':
            text = re.sub(r'\s*libzstd-dev\s*(?:\([^)]*\))?\s*,', '', text)
        # A regular expression anchored to Depends: does not match Build-Depends or Pre-Depends.
        text = re.sub(r'^Depends: ', 'Depends: php5.6-common (= ' + core_version + '), ', text, flags=re.M)
        control.write_text(text)
    changelog(tree, name, ubuntu)


def select_sources(args):
    if args.core_only and args.extensions:
        raise ValueError('--core-only and --extensions are mutually exclusive')
    if args.core_only:
        selected = set()
    elif args.extensions:
        selected = set()
        for extension in args.extensions.split(','):
            name = extension.strip()
            if not name.startswith('php5.6-'):
                name = 'php5.6-' + name
            if name not in CATALOG or CATALOG[name]['source'] == 'php5.6' or name.endswith(('-dbg', '-dbgsym')):
                raise ValueError('Unknown external extension: ' + extension)
            selected.add(CATALOG[name]['source'])
    else:
        selected = {r['source'] for n, r in CATALOG.items()
                    if r['source'] != 'php5.6' and not n.endswith(('-dbg', '-dbgsym'))}
    ordered = []
    def add(name):
        if name not in ordered:
            for dependency in EDGES.get(name, []):
                add(dependency)
            ordered.append(name)
    for name in sorted(selected):
        add(name)
    return ['php-defaults', 'dh-php', 'tidy-html5', 'php5.6'] + ordered


def metadata(path):
    data = subprocess.check_output(['dpkg-deb', '-f', str(path)]).decode()
    result = {}
    key = None
    for line in data.splitlines():
        if line.startswith(' ') and key:
            result[key] += ' ' + line.strip()
            continue
        if line and not line[0].isspace() and ': ' in line:
            key, value = line.split(': ', 1)
            result[key] = value
    return result


def dependencies(tree, evidence, name):
    run(['mk-build-deps', '--install', '--remove', '--tool',
         'apt-get -y --no-install-recommends', 'debian/control'], cwd=tree,
        log=evidence / (name + '-dependencies.log'))
    run(['dpkg-checkbuilddeps'], cwd=tree)


def build_one(name, args, work, cache, keyring, patch, evidence, identity):
    parent = work / 'build' / name
    parent.mkdir(parents=True, exist_ok=True)
    stamp = parent / 'success.json'
    tree = parent / 'source'
    # Recheck signed inputs on every run, including cache reuse/provenance exports.
    dsc = download_source(name, cache, keyring, evidence)
    if stamp.exists():
        previous = json.loads(stamp.read_text())
        if previous.get('identity') == identity and all(
                (parent / filename).exists() and sha(parent / filename) == digest
                for filename, digest in previous.get('artifacts', {}).items()) and previous.get('artifacts'):
            # A new container still needs system libraries before cached .debs can be installed.
            dependencies(tree, evidence, name)
            print('Reusing verified completed build: ' + name, flush=True)
            return list(parent.glob('*.deb'))
    # Failed or stale builds are always extracted again from verified source files.
    if tree.exists():
        shutil.rmtree(str(tree))
    for item in list(parent.glob('*.deb')) + list(parent.glob('*.ddeb')):
        item.unlink()
    for component in SOURCES[name]['files']:
        original = dsc.parent / component['filename']
        shutil.copyfile(str(original), str(parent / original.name))
    run(['dpkg-source', '--no-check', '-x', dsc, tree], log=evidence / (name + '-extract.log'))
    # Signature was checked explicitly against the pinned dedicated keyring above.
    if name == 'php5.6':
        adapt_core(tree, patch, args.ubuntu, args.full_tests, evidence)
    elif name not in ('php-defaults', 'dh-php', 'tidy-html5'):
        adapt_pecl(tree, name, args.ubuntu, version('php5.6', args.ubuntu))
    else:
        if name == 'dh-php':
            # The helper contains scripts. Break its php-all-dev build dependency cycle;
            # php5.6-dev is built/installed before any extension uses it.
            path = tree / 'debian/control'
            path.write_text(re.sub(r',\s*php-all-dev\s*(?:\([^)]*\))?', '', path.read_text()))
        changelog(tree, name, args.ubuntu)
    dependencies(tree, evidence, name)
    env = dict(os.environ, NO_INTERACTION='1', REPORT_EXIT_STATUS='1' if name == 'php5.6' else '0',
               DH_PHP_VERSIONS_OVERRIDE='5.6', PHP_DEFAULT_VERSION_OVERRIDE='5.6',
               DEB_BUILD_OPTIONS='parallel=%d' % args.jobs)
    # The historical PECL test harness lacks some runtime dependencies. Dedicated
    # smoke tests below are mandatory; original PECL suite output is retained.
    run(['dpkg-buildpackage', '-us', '-uc', '-j%d' % args.jobs], cwd=tree,
        log=evidence / (name + '-build.log'), env=env)
    artifacts = list(parent.glob('*.deb')) + list(parent.glob('*.dsc'))
    if not list(parent.glob('*.deb')):
        raise RuntimeError('No Debian packages produced for ' + name)
    # The success stamp is written only after packaging exits successfully.
    save(stamp, {'identity': identity, 'artifacts': {p.name: sha(p) for p in artifacts}})
    return list(parent.glob('*.deb'))


def install(files):
    if not files:
        raise RuntimeError('Missing packages required to continue')
    run(['apt-get', '-y', '--no-install-recommends', 'install'] + [p.resolve() for p in files])


def publish_packages(name, files, output):
    support = {'php-defaults': {'php-common'}, 'dh-php': set(),
               'tidy-html5': {'libtidy5deb1'}}
    selected = []
    for path in files:
        info = metadata(path)
        package = info['Package']
        if package not in CATALOG and package not in support.get(name, set()):
            continue
        if package.endswith(('-dbg', '-dbgsym')):
            continue
        destination = output / 'packages' / path.name
        shutil.copyfile(str(path), str(destination))
        selected.append({'name': package, 'version': info['Version'],
                         'architecture': info['Architecture'], 'filename': path.name,
                         'source': info.get('Source', name), 'depends': info.get('Depends', ''),
                         'pre_depends': info.get('Pre-Depends', ''),
                         'sha256': sha(path), 'role': 'core' if name == 'php5.6' else
                         'support' if name in support else 'extension'})
    return selected


def validate_extensions(records, work, output):
    env = dict(os.environ, MIBS='')
    stage = work / 'extension-validation'
    stage.mkdir(exist_ok=True)
    installed = set(json.loads(subprocess.check_output(
        ['php5.6', '-r', 'echo json_encode(get_loaded_extensions());'], env=env).decode()))
    results = []
    for record in records:
        if record['role'] != 'extension':
            continue
        package = output / 'packages' / record['filename']
        run(['dpkg-deb', '-x', package, stage])
        command = ['php5.6', '-d', 'apc.enable_cli=1', '-d', 'yac.enable_cli=1']
        directives = []
        listing = subprocess.check_output(['dpkg-deb', '-c', str(package)]).decode()
        for line in listing.splitlines():
            relative = line.split()[-1].lstrip('./')
            if '/mods-available/' not in relative or not relative.endswith('.ini'):
                continue
            for directive in (stage / relative).read_text().splitlines():
                match = re.match(r'\s*(zend_extension|extension)\s*=\s*([^;\s]+)', directive)
                if match:
                    kind, filename = match.groups()
                    matches = list((stage / 'usr/lib/php').glob('*/' + Path(filename).name))
                    if len(matches) != 1:
                        raise RuntimeError('Missing/ambiguous extension: ' + filename)
                    directives.append((kind, matches[0]))
        if not directives:
            raise RuntimeError('Missing module directive: ' + record['name'])
        for kind, module in directives:
            if module.stem not in installed:
                command += ['-d', kind + '=' + str(module)]
        command += [str(KIT / 'tools/extension-smoke.php'), record['name'][len('php5.6-'):]]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        try:
            stdout, stderr = process.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise RuntimeError('Extension test timed out: ' + record['name'])
        passed = process.returncode == 0 and b'PASS ' in stdout and not stderr.strip()
        results.append({'name': record['name'], 'status': 'PASS' if passed else 'FAIL',
                        'stdout': stdout.decode(errors='replace'), 'stderr': stderr.decode(errors='replace')})
        save(output / 'evidence/extensions.json', results)
        if not passed:
            raise RuntimeError('Extension test failed: ' + record['name'])


def complete_output(args, work, output, records, selected):
    expected = {n for n, r in CATALOG.items() if r['source'] in selected and not n.endswith(('-dbg', '-dbgsym'))}
    if {r['name'] for r in records if r['role'] != 'support'} != expected:
        raise RuntimeError('The produced package catalog is incomplete')
    save(output / 'package-catalog.json', records)
    if args.debug:
        run(['python3', KIT / 'tools/debug-packages.py'])
    # A flat, local APT index for inspection/use on the matching Ubuntu release.
    with (output / 'packages/Packages').open('wb') as stream:
        subprocess.check_call(['dpkg-scanpackages', '--multiversion', '.', '/dev/null'],
                              cwd=str(output / 'packages'), stdout=stream)
    with (output / 'SHA256SUMS').open('w') as stream:
        for path in sorted(output.rglob('*')):
            if path.is_file() and path.name not in ('SHA256SUMS', 'build-status.json', 'bootstrap.log'):
                stream.write(sha(path) + '  ' + str(path.relative_to(output)) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ubuntu', choices=['16.04', '18.04', '20.04'], required=True)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--core-only', action='store_true')
    parser.add_argument('--extensions')
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--full-tests', action='store_true')
    parser.add_argument('--native', action='store_true')
    parser.add_argument('--plan', action='store_true')
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    selected = select_sources(args)
    if args.plan:
        print(json.dumps({'ubuntu': args.ubuntu, 'architecture': 'amd64',
                          'status': 'COMPILATION TEST REQUIRED', 'sources_in_order': selected,
                          'patch_commit': PATCH_COMMIT, 'core_version': version('php5.6', args.ubuntu),
                          'debug': args.debug, 'full_tests': args.full_tests}, indent=2))
        return
    os_release = dict(line.strip().split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    if (not args.native and not Path('/.dockerenv').exists()) or os_release.get('ID', '').strip('"') != 'ubuntu' or os_release.get('VERSION_ID', '').strip('"') != args.ubuntu:
        raise RuntimeError('Use the matching Ubuntu Docker image or explicit --native mode')
    if args.native and os.geteuid() != 0:
        raise RuntimeError('Native mode requires root')
    if subprocess.check_output(['dpkg', '--print-architecture']).strip() != b'amd64':
        raise RuntimeError('This catalog currently supports amd64 only')
    work = Path(os.environ.get('PHP56_WORK', '/work')).resolve()
    output = Path(os.environ.get('PHP56_OUTPUT', '/output')).resolve()
    cache = Path(os.environ.get('PHP56_CACHE', '/cache')).resolve()
    lock = (work / 'build.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    evidence = output / 'evidence'
    evidence.mkdir(parents=True, exist_ok=True)
    # Clean previous distributable output so a failed/incomplete run cannot look like a release.
    for name in ['packages', 'debug', 'sources']:
        if (output / name).exists():
            shutil.rmtree(str(output / name))
        (output / name).mkdir()
    for name in ['SHA256SUMS', 'package-catalog.json', 'debug-catalog.json']:
        if (output / name).exists():
            (output / name).unlink()
    status = {'ubuntu': args.ubuntu, 'status': 'IN_PROGRESS', 'patch_commit': PATCH_COMMIT,
              'execution_mode': 'native' if args.native else 'docker',
              'compilation_test_required_for_every_target': True,
              'full_core_suite': 'required' if args.full_tests else 'not_run',
              'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    save(output / 'build-status.json', status)
    try:
        identity_hash = hashlib.sha256()
        for directory in [KIT / 'scripts', ASSETS, KIT / 'tools']:
            for path in sorted(directory.rglob('*')):
                if path.is_file() and '__pycache__' not in path.parts:
                    identity_hash.update(str(path.relative_to(KIT)).encode())
                    identity_hash.update(path.read_bytes())
        identity_hash.update(json.dumps(vars(args), sort_keys=True).encode())
        identity = identity_hash.hexdigest()
        keyring = work / 'sury-keyring.gpg'
        # The ASCII public key is part of this reviewed repository, never obtained from the mirror.
        run(['gpg', '--batch', '--yes', '--dearmor', '--output', keyring, ASSETS / 'sury-signing-key.asc'])
        key_data = subprocess.check_output(['gpg', '--batch', '--no-default-keyring', '--keyring', str(keyring), '--with-colons', '--fingerprint'])
        if FINGERPRINT.encode() not in key_data:
            raise RuntimeError('Unexpected source signing key')
        patch = fetch(PATCH_URL, cache / 'php-5.6-enhanced-universal.patch', PATCH_SHA256)
        records = []
        header_sources = {dep for name in selected for dep in EDGES.get(name, [])}
        for name in selected:
            files = build_one(name, args, work, cache, keyring, patch, evidence, identity)
            records.extend(publish_packages(name, files, output))
            if name == 'php-defaults':
                install([p for p in files if metadata(p)['Package'] == 'php-common'])
            elif name == 'dh-php':
                install([p for p in files if metadata(p)['Package'] == 'dh-php'])
            elif name == 'tidy-html5':
                install([p for p in files if metadata(p)['Package'] in ('libtidy5deb1', 'libtidy-dev')])
            elif name == 'php5.6' or name in header_sources:
                install([p for p in files if metadata(p)['Package'] in CATALOG and
                         not metadata(p)['Package'].endswith(('-dbg', '-dbgsym'))])
            # Keep rebuildable modified DSCs and every listed source component.
            for dsc in (work / 'build' / name).glob('*.dsc'):
                text = dsc.read_text()
                section = re.search(r'^Checksums-Sha256:\n((?: .+\n)+)', text, re.M)
                if not section:
                    raise RuntimeError('Missing source checksums')
                for line in section.group(1).splitlines():
                    digest, size, filename = line.split()
                    original = dsc.parent / filename
                    if Path(filename).name != filename or sha(original) != digest or original.stat().st_size != int(size):
                        raise RuntimeError('Source artifact verification failed')
                    shutil.copyfile(str(original), str(output / 'sources' / filename))
                shutil.copyfile(str(dsc), str(output / 'sources' / dsc.name))
        provenance = output / 'sources/provenance'
        provenance.mkdir()
        for name in selected:
            original = cache / name / SOURCES[name]['dsc']
            shutil.copyfile(str(original), str(provenance / original.name))
        for filename in ['sources.lock.json', 'patched-files.lock.json', 'sury-signing-key.asc']:
            shutil.copyfile(str(ASSETS / filename), str(provenance / filename))
        run(['apt-get', '-y', '--no-install-recommends', 'install', 'apache2', 'memcached', 'redis-server'])
        processes = []
        try:
            processes.append(subprocess.Popen(['memcached', '-u', 'www-data', '-l', '127.0.0.1', '-p', '11211', '-U', '0']))
            processes.append(subprocess.Popen(['redis-server', '--bind', '127.0.0.1', '--port', '6379', '--save', '', '--appendonly', 'no'], stdout=subprocess.DEVNULL))
            time.sleep(1)
            if any(p.poll() is not None for p in processes):
                raise RuntimeError('Test backend failed to start')
            validate_extensions(records, work, output)
            run(['python3', KIT / 'tools/apache-smoke.py'], log=evidence / 'apache-smoke.log')
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        run(['dpkg-query', '-W'], log=evidence / 'installed-build-packages.txt')
        for path in [work / 'apache-smoke-error.log', work / 'apache-smoke-php-errors.log',
                     work / 'cli-oom-stderr.log', work / 'build/php5.6/source/security-test-results.txt']:
            if path.exists():
                shutil.copyfile(str(path), str(evidence / path.name))
        complete_output(args, work, output, records, selected)
        status.update(status='PASS', packages=len(records), checks=['compilation', '3 security PHPTs', 'Apache mod_php smoke', 'selected extension smoke'])
    except Exception as exc:
        status.update(status='FAIL', error=str(exc))
        raise
    finally:
        save(output / 'build-status.json', status)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        sys.exit(1)
