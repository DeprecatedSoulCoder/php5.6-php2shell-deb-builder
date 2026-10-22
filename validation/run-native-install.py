#!/usr/bin/env python3
"""Install/test a built catalog on a disposable matching native Ubuntu VM.

Requires explicit --apply. This changes packages and services on that VM.
No credentials or host identity are written to the structured result.
SPDX-License-Identifier: MIT
"""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

EXCLUDED = {
    'php5.6-yac': 'APCu selected; YAC conflicts with the APCu virtual package.',
    'php5.6-xcache': 'APCu and OPcache selected; Xcache is an alternative cache.',
    'php5.6-gmagick': 'Imagick selected; Gmagick conflicts with the Imagick virtual package.',
    'php5.6-smbclient': 'MongoDB selected; SMBClient plus MongoDB crashed during SASL cleanup on native 16.04/18.04 tests.',
}


def save(path, data):
    temporary = Path(str(path) + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def run(command, evidence, label, env=None):
    print(label, flush=True)
    process = subprocess.Popen(list(map(str, command)), stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, env=env)
    data = process.communicate()[0]
    (evidence / (label + '.log')).write_bytes(data)
    if process.returncode:
        raise RuntimeError('%s failed with exit %d: %s' %
                           (label, process.returncode, data[-4000:].decode(errors='replace')))
    return data


def http_json(port, path):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
    try:
        connection.request('GET', path)
        response = connection.getresponse()
        data = response.read()
        if response.status != 200:
            raise RuntimeError('HTTP status %d: %s' % (response.status, data[:1000]))
        return json.loads(data.decode())
    finally:
        connection.close()


def apache_extensions(names, kit, evidence):
    temporary = Path(tempfile.mkdtemp(prefix='php56-installed-apache-'))
    temporary.chmod(0o755)
    document = temporary / 'www'
    document.mkdir(mode=0o755)
    shutil.copyfile(str(kit / 'tools/extension-smoke.php'), str(document / 'extension-smoke.php'))
    allowed = 'array(' + ','.join("'%s'=>true" % name for name in names) + ')'
    (document / 'probe.php').write_text('''<?php
header('Content-Type: application/json');
if (!isset($_GET['extension'])) {
 echo json_encode(array('version'=>PHP_VERSION,'sapi'=>PHP_SAPI,
  'ini'=>php_ini_loaded_file(),'extensions'=>get_loaded_extensions()));
 exit;
}
$allowed = ALLOWED;
$name = $_GET['extension'];
if (!isset($allowed[$name])) {http_response_code(400); exit;}
if (!defined('STDERR')) {define('STDERR', fopen('php://stderr', 'w'));}
$argv = array('extension-smoke', $name);
ob_start();
require __DIR__.'/extension-smoke.php';
$result = ob_get_clean();
echo json_encode(array('output'=>trim($result)));
'''.replace('ALLOWED', allowed))
    config = temporary / 'apache.conf'
    config.write_text('''ServerRoot /etc/apache2
ServerName localhost
PidFile {temporary}/apache.pid
Listen 127.0.0.1:18057
LoadModule mpm_prefork_module /usr/lib/apache2/modules/mod_mpm_prefork.so
LoadModule authz_core_module /usr/lib/apache2/modules/mod_authz_core.so
LoadModule php5_module /usr/lib/apache2/modules/libphp5.6.so
User www-data
Group www-data
StartServers 1
MinSpareServers 1
MaxSpareServers 1
ServerLimit 1
MaxRequestWorkers 1
MaxConnectionsPerChild 0
ErrorLog {temporary}/error.log
LogLevel warn
DocumentRoot {document}
<Directory {document}>
Require all granted
<FilesMatch "\\.php$">
SetHandler application/x-httpd-php
</FilesMatch>
</Directory>
php_admin_flag display_errors Off
'''.format(temporary=temporary, document=document))
    process = None
    results = []
    try:
        run(['apache2', '-f', config, '-t'], evidence, 'apache-installed-configtest')
        with (evidence / 'apache-installed-process.log').open('w') as log:
            process = subprocess.Popen(['apache2', '-f', str(config), '-DFOREGROUND'],
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                       env=dict(os.environ, MIBS=''))
            for attempt in range(50):
                try:
                    info = http_json(18057, '/probe.php')
                    break
                except (OSError, ValueError):
                    if process.poll() is not None:
                        raise RuntimeError('Installed-module Apache process exited')
                    time.sleep(.1)
            else:
                raise RuntimeError('Installed-module Apache did not become ready')
            if info['sapi'] != 'apache2handler' or 'php2shell' not in info['version']:
                raise RuntimeError('Wrong Apache PHP version/SAPI')
            save(evidence / 'apache-installed-info.json', info)
            for name in names:
                response = http_json(18057, '/probe.php?extension=' + name)
                if response.get('output') != 'PASS ' + name:
                    raise RuntimeError('Apache extension test failed: ' + name)
                results.append({'name': 'php5.6-' + name, 'status': 'PASS'})
                save(evidence / 'apache-installed-extensions.json', results)
                print('Apache extension PASS ' + name, flush=True)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if (temporary / 'error.log').exists():
            shutil.copyfile(str(temporary / 'error.log'), str(evidence / 'apache-installed-error.log'))
        shutil.rmtree(str(temporary))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.apply or os.geteuid() != 0:
        raise RuntimeError('Use explicit --apply as root on a disposable matching VM')
    release, evidence = args.release.resolve(), args.evidence
    evidence.mkdir(parents=True, exist_ok=True)
    evidence = evidence.resolve()
    kit = Path(__file__).resolve().parent.parent
    status = json.loads((release / 'build-status.json').read_text())
    if status.get('status') != 'PASS':
        raise RuntimeError('The compilation must have completed with PASS')
    installed_os = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    if installed_os.get('ID', '').strip('"') != 'ubuntu' or installed_os.get('VERSION_ID', '').strip('"') != status['ubuntu']:
        raise RuntimeError('The installed Ubuntu version does not match the release')
    records = json.loads((release / 'package-catalog.json').read_text())
    selected = [r for r in records if r['name'] not in EXCLUDED]
    expected_extensions = sorted(r['name'][len('php5.6-'):] for r in selected if r['role'] == 'extension')
    report = {'status': 'IN_PROGRESS', 'ubuntu': status['ubuntu'], 'mode': 'native',
              'excluded_conflicting_packages': EXCLUDED,
              'selected_runtime_packages': len(selected), 'selected_extensions': len(expected_extensions),
              'core_suite': status.get('full_core_suite'),
              'limits': ['No representative third-party application or production workload.',
                         'External service tests use local Memcached/Redis; other backend integrations are bounded smoke checks.']}
    save(evidence / 'installation-result.json', report)
    try:
        for name in EXCLUDED:
            state = subprocess.Popen(['dpkg-query', '-W', '-f', '${db:Status-Status}', name],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, unused = state.communicate()
            if state.returncode == 0 and stdout == b'installed':
                raise RuntimeError('Excluded extension is already installed: %s; review and remove it before this test' % name)
        files = []
        for record in selected:
            path = release / 'packages' / record['filename']
            if Path(record['filename']).name != record['filename'] or hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
                raise RuntimeError('Runtime checksum/path verification failed')
            files.append(path)
        selected_names = {r['name'] for r in selected}
        if args.debug:
            for record in json.loads((release / 'debug-catalog.json').read_text()):
                if record['name'] != 'php5.6-dbg' and record['name'][:-7] not in selected_names:
                    continue
                path = release / 'debug' / record['filename']
                if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
                    raise RuntimeError('Debug package checksum mismatch')
                files.append(path)
        report['selected_debug_packages'] = len(files) - len(selected)
        simulation = run(['apt-get', '-s', '--no-install-recommends', 'install'] + files,
                         evidence, 'apt-install-simulation')
        if any(line.startswith(b'Remv ') for line in simulation.splitlines()):
            raise RuntimeError('APT simulation proposes removals')
        run(['apt-get', '-y', '--no-install-recommends', 'install'] + files, evidence, 'apt-install')
        audit = run(['dpkg', '--audit'], evidence, 'dpkg-audit')
        if audit.strip():
            raise RuntimeError('dpkg audit reports incomplete package state')
        versions = {}
        for record in selected:
            current = subprocess.check_output(['dpkg-query', '-W', '-f', '${Version}', record['name']]).decode()
            if current != record['version']:
                raise RuntimeError('Installed version mismatch: ' + record['name'])
            versions[record['name']] = current
        save(evidence / 'installed-versions.json', versions)
        run(['systemctl', 'start', 'memcached', 'redis-server', 'php5.6-fpm'], evidence, 'start-services')
        for service in ['memcached', 'redis-server', 'php5.6-fpm']:
            active = run(['systemctl', 'is-active', service], evidence, 'service-' + service)
            if active.strip() != b'active':
                raise RuntimeError('Service is not active: ' + service)
        # An explicit generic server name also keeps private host addresses out of Apache diagnostics.
        Path('/etc/apache2/conf-available/php56-validation-servername.conf').write_text('ServerName localhost\n')
        run(['a2enconf', 'php56-validation-servername'], evidence, 'apache-servername')
        enabled = subprocess.check_output(['apache2ctl', '-M'], stderr=subprocess.STDOUT).decode()
        for name in ['mpm_event', 'mpm_worker']:
            if name + '_module' in enabled:
                run(['a2dismod', name], evidence, 'disable-' + name)
        run(['a2enmod', 'mpm_prefork', 'php5.6'], evidence, 'apache-enable-modules')
        run(['apache2ctl', 'configtest'], evidence, 'apache-system-configtest')
        run(['systemctl', 'restart', 'apache2'], evidence, 'apache-system-restart')
        run(['systemctl', 'is-active', 'apache2'], evidence, 'service-apache2')
        run(['php-fpm5.6', '-t'], evidence, 'fpm-configtest')
        libraries = run(['ldd', '/usr/lib/apache2/modules/libphp5.6.so'], evidence, 'apache-library-resolution')
        if b'not found' in libraries:
            raise RuntimeError('Apache PHP module has unresolved shared libraries')
        env = dict(os.environ, MIBS='')
        run(['php5.6', '-v'], evidence, 'php-version', env)
        run(['php5.6', '--ini'], evidence, 'php-ini', env)
        run(['php5.6', '-m'], evidence, 'php-modules', env)
        loaded = json.loads(subprocess.check_output(
            ['php5.6', '-r', 'echo json_encode(get_loaded_extensions());'], env=env).decode())
        loaded = {name.lower() for name in loaded}
        expected_modules = set()
        for record in selected:
            listing = subprocess.check_output(['dpkg-deb', '-c', str(release / 'packages' / record['filename'])]).decode()
            for line in listing.splitlines():
                relative = line.split()[-1].lstrip('./')
                if '/mods-available/' not in relative or not relative.endswith('.ini'):
                    continue
                for directive in (Path('/') / relative).read_text().splitlines():
                    match = re.match(r'\s*(?:zend_extension|extension)\s*=\s*([^;\s]+)', directive)
                    if match:
                        name = Path(match.group(1)).stem.lower()
                        expected_modules.add('zend opcache' if name == 'opcache' else name)
        missing = expected_modules - loaded
        if missing:
            raise RuntimeError('Installed module directives are not loaded in CLI: ' + ','.join(sorted(missing)))
        report['module_directives_verified_in_cli'] = sorted(expected_modules)
        results = []
        for name in expected_extensions:
            process = subprocess.Popen(['php5.6', '-d', 'apc.enable_cli=1',
                                        str(kit / 'tools/extension-smoke.php'), name],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            try:
                stdout, stderr = process.communicate(timeout=60)
            except subprocess.TimeoutExpired:
                process.kill(); process.communicate()
                raise RuntimeError('Installed CLI extension test timeout: ' + name)
            passed = process.returncode == 0 and stdout.strip() == ('PASS ' + name).encode() and not stderr.strip()
            results.append({'name': 'php5.6-' + name, 'status': 'PASS' if passed else 'FAIL',
                            'exit_code': process.returncode,
                            'stdout': stdout.decode(errors='replace'), 'stderr': stderr.decode(errors='replace')})
            save(evidence / 'cli-installed-extensions.json', results)
            if not passed:
                raise RuntimeError('Installed CLI extension test failed: ' + name)
            print('CLI extension PASS ' + name, flush=True)
        report['cli_extension_checks_passed'] = len(results)
        report['apache_extension_checks_passed'] = len(apache_extensions(expected_extensions, kit, evidence))
        # Re-run the seven security/upload checks with all selected modules enabled together.
        env.update(PHP56_WORK=str(evidence))
        run(['python3', kit / 'tools/apache-smoke.py'], evidence, 'apache-security-with-all-extensions', env)
        # Confirm the ordinary system Apache service, independently of the isolated test listener.
        probe = Path('/var/www/html/php56-installed-validation-probe.php')
        if probe.exists():
            raise RuntimeError('Refusing to replace an existing HTTP probe')
        try:
            probe.write_text('<?php header("Content-Type: application/json"); echo json_encode(array("version"=>PHP_VERSION,"sapi"=>PHP_SAPI,"pid"=>getmypid(),"extensions"=>get_loaded_extensions()));\n')
            info = http_json(80, '/' + probe.name)
            if info['sapi'] != 'apache2handler' or 'php2shell' not in info['version']:
                raise RuntimeError('System Apache serves an unexpected PHP runtime')
            pid = info.pop('pid')
            module = Path('/usr/lib/apache2/modules/libphp5.6.so')
            if str(module) not in Path('/proc/%d/maps' % pid).read_text():
                raise RuntimeError('System Apache is not using the expected module file')
            info['module_sha256'] = hashlib.sha256(module.read_bytes()).hexdigest()
            save(evidence / 'apache-system-info.json', info)
        finally:
            if probe.exists():
                probe.unlink()
        report.update(status='PASS', system_apache='PASS',
                      security_checks_with_all_extensions='PASS', dpkg_audit='PASS')
    except Exception as exc:
        report.update(status='FAIL', error=str(exc))
        raise
    finally:
        save(evidence / 'installation-result.json', report)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        sys.exit(1)
