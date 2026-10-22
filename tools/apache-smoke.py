#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run bounded regression checks against installed mod_php on localhost only."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import time
import urllib.request

build = Path(os.environ['PHP56_WORK'])
doc = Path('/var/www/php56-patched-smoke')
state = Path('/var/lib/php56-patched-smoke')
doc.mkdir(exist_ok=True)
state.mkdir(exist_ok=True)
www = pwd.getpwnam('www-data')
os.chown(str(state), www.pw_uid, www.pw_gid)
config = build / 'apache-smoke.conf'
config.write_text('''ServerRoot /etc/apache2
ServerName localhost
PidFile /tmp/apache2-php56-smoke.pid
Listen 127.0.0.1:18056
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
ErrorLog {work}/apache-smoke-error.log
LogLevel warn
DocumentRoot /var/www/php56-patched-smoke
<Directory /var/www/php56-patched-smoke>
Require all granted
<FilesMatch "\\.php$">
SetHandler application/x-httpd-php
</FilesMatch>
</Directory>
php_admin_value session.save_path /var/lib/php56-patched-smoke
php_admin_value session.upload_progress.enabled 1
php_admin_value session.upload_progress.cleanup 0
php_admin_value session.upload_progress.min_freq 0
php_admin_value error_log /var/lib/php56-patched-smoke/php-errors.log
php_admin_flag log_errors On
php_admin_flag display_errors Off
php_admin_value post_max_size 100K
'''.replace('{work}',str(build)))
(doc / 'info.php').write_text('''<?php
header('Content-Type: application/json');
echo json_encode(array('version'=>PHP_VERSION, 'sapi'=>PHP_SAPI,
 'pid'=>getmypid(), 'ini'=>php_ini_loaded_file(),
 'progress'=>ini_get('session.upload_progress.enabled'),
 'extensions'=>get_loaded_extensions()));
''')
(doc / 'upload.php').write_text('''<?php
header('Content-Type: application/json');
$f = isset($_FILES['file']) ? $_FILES['file'] : null;
echo json_encode(array('pre_session'=>array_key_exists('_SESSION', $GLOBALS),
 'field'=>isset($_POST['field']) ? $_POST['field'] : null,
 'uploaded'=>$f && $f['error']===0 && is_uploaded_file($f['tmp_name']),
 'sha256'=>$f && $f['error']===0 ? hash_file('sha256',$f['tmp_name']) : null,
 'name'=>$f ? $f['name'] : null, 'pid'=>getmypid()));
''')
(doc / 'session.php').write_text('''<?php
class W { public $a; function __wakeup() {} }
class Cust implements Serializable {
 public $x;
 function serialize() {return $this->x;}
 function unserialize($d) {$this->x=$d;}
}
$pre = array_key_exists('_SESSION', $GLOBALS);
session_start();
header('Content-Type: application/json');
echo json_encode(array('pre_session'=>$pre, 'id'=>session_id(),
 'a'=>$_SESSION['w']->a, 'custom'=>$_SESSION['c']->x,
 'progress'=>$_SESSION['upload_progress_key']['bytes_processed'],
 'file_progress'=>$_SESSION['upload_progress_key']['files'][0]['bytes_processed']));
''')
(doc / 'oom.php').write_text('''<?php
ini_set('memory_limit','16M');
register_shutdown_function(function() {
 file_put_contents('/var/lib/php56-patched-smoke/unsafe-shutdown','called');
});
$x=str_repeat('A', 64*1024*1024);
echo 'unexpected-success';
''')

def request(path, body=None, sid=None, chunked=False):
    conn = http.client.HTTPConnection('127.0.0.1', 18056, timeout=10)
    headers = {}
    if sid:
        headers['Cookie'] = 'PHPSESSID=' + sid
    if body is not None:
        headers['Content-Type'] = 'multipart/form-data; boundary=php56boundary'
        if not chunked:
            headers['Content-Length'] = str(len(body))
        else:
            headers['Transfer-Encoding'] = 'chunked'
    if chunked:
        conn.putrequest('POST', path)
        for name, value in headers.items():
            conn.putheader(name, value)
        conn.endheaders()
        for offset in range(0,len(body),8192):
            part=body[offset:offset+8192]
            conn.send(('%x\r\n' % len(part)).encode('ascii')+part+b'\r\n')
        conn.send(b'0\r\n\r\n')
    else:
        conn.request('POST' if body is not None else 'GET', path, body, headers)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    assert resp.status == 200, (resp.status, data)
    return json.loads(data.decode('utf-8'))

def multipart(payload=b'hello patched apache'):
    return (b'--php56boundary\r\nContent-Disposition: form-data; name="PHP_SESSION_UPLOAD_PROGRESS"\r\n\r\nkey\r\n'
            b'--php56boundary\r\nContent-Disposition: form-data; name="field"\r\n\r\nvalue\r\n'
            b'--php56boundary\r\nContent-Disposition: form-data; name="file"; filename="test.txt"\r\nContent-Type: text/plain\r\n\r\n'
            + payload + b'\r\n--php56boundary--\r\n')

def seed(sid, record):
    path = state / ('sess_' + sid)
    path.write_bytes(record)
    os.chown(str(path), www.pw_uid, www.pw_gid)
    return path

results = []
subprocess.check_call(['apache2', '-f', str(config), '-t'])
subprocess.check_call(['apache2', '-f', str(config), '-k', 'start'])
try:
    for attempt in range(20):
        try:
            info = request('/info.php')
            break
        except OSError:
            time.sleep(.1)
    assert info['version'].startswith('5.6.40-') and info['sapi'] == 'apache2handler', info
    assert info['ini'] == '/etc/php/5.6/apache2/php.ini', info
    required = {'openssl','curl','mbstring','mysqli','PDO','pdo_mysql','gd','intl','zip','session','Zend OPcache'}
    assert required.issubset(set(info['extensions'])), info
    module=Path('/usr/lib/apache2/modules/libphp5.6.so')
    assert str(module) in Path('/proc/%d/maps' % info['pid']).read_text()
    assert b'zend_mm_safe_error_ex' in subprocess.check_output(['nm','-D',str(module)])
    info['module_sha256']=hashlib.sha256(module.read_bytes()).hexdigest()
    results.append({'check':'Apache module, version, mapped binary, patch symbol, configuration and extensions', 'result':'PASS', 'info':info})

    body = multipart()
    data = request('/upload.php', body, 'uploadcontrol')
    assert data['uploaded'] and data['field']=='value' and not data['pre_session'], data
    assert data['sha256']==hashlib.sha256(b'hello patched apache').hexdigest(), data
    results.append({'check':'multipart fields, file upload, hash and session cleanup', 'result':'PASS'})

    record = b'w|O:1:"W":1:{s:1:"a";i:42;}c|C:4:"Cust":7:{payload}'
    path = seed('roundtrip', record)
    data = request('/upload.php', body, 'roundtrip')
    assert not data['pre_session'] and path.read_bytes().startswith(record), (data,path.read_bytes())
    data = request('/session.php', body, 'roundtrip')
    assert not data['pre_session'] and data['a']==42 and data['custom']=='payload', data
    assert data['progress']==len(body) and data['file_progress']>0, data
    results.append({'check':'upload progress object/custom payload round-trip and counters', 'result':'PASS'})

    for sid, record in [
        ('reservedname', b'x|O:8:"stdClass":1:{s:27:"__PHP_Incomplete_Class_Name";s:3:"foo";}'),
        ('reservedpayload', b'x|O:8:"stdClass":1:{s:33:"__PHP_Incomplete_Class_Serialized";s:3:"foo";}'),
        ('corruptrecord', b'x|not-serialized-at-all')]:
        path=seed(sid,record)
        data=request('/upload.php',body,sid)
        assert not path.exists() and data['uploaded'], (sid,data)
    results.append({'check':'reserved properties and corrupt session records rejected', 'result':'PASS'})

    pids=set()
    for i in range(40):
        data=request('/upload.php',body,'repeat'+str(i))
        assert data['uploaded'] and not data['pre_session'], data
        pids.add(data['pid'])
    assert len(pids)==1, pids
    results.append({'check':'40 consecutive uploads in the same Apache worker', 'result':'PASS'})

    # Test a real chunked Apache request without a Content-Length header.
    # Put the large content in a form field to inspect how much was accepted.
    large=(b'--php56boundary\r\nContent-Disposition: form-data; name="field"\r\n\r\n'
           + b'a'*1048576 + b'\r\n--php56boundary--\r\n')
    data=request('/upload.php',large,chunked=True)
    assert data['field'] is None or len(data['field'])<=102400, len(data['field'])
    results.append({'check':'post_max_size enforced on chunked multipart without Content-Length', 'result':'PASS'})

    before=request('/info.php')['pid']
    try:
        request('/oom.php')
    except (OSError, ValueError, AssertionError, http.client.HTTPException):
        pass
    else:
        raise AssertionError('OOM request unexpectedly completed')
    for attempt in range(30):
        info=request('/info.php')
        if info['pid']!=before:
            break
        time.sleep(.1)
    assert info['pid']!=before and not (state/'unsafe-shutdown').exists(), info
    cli=subprocess.Popen(['/usr/bin/php5.6','-n','-d','memory_limit=16M','-r',
        'register_shutdown_function(function(){echo "UNSAFE-SHUTDOWN";}); $x=str_repeat("A",64*1024*1024);'],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    out,err=cli.communicate(timeout=10)
    assert cli.returncode==1 and b'Allowed memory size' in err and b'UNSAFE-SHUTDOWN' not in out, (cli.returncode,out,err)
    (build/'cli-oom-stderr.log').write_bytes(err)
    results.append({'check':'OOM exits Apache worker before shutdown callbacks; server recovers', 'result':'PASS'})
    print(json.dumps(results, indent=2))
finally:
    subprocess.call(['apache2','-f',str(config),'-k','stop'])
    shutil.rmtree(str(doc))
    # Keep the error log as validation evidence; remove web-served test data.
    log=state/'php-errors.log'
    if log.exists():
        shutil.copyfile(str(log),str(build/'apache-smoke-php-errors.log'))
    shutil.rmtree(str(state))
