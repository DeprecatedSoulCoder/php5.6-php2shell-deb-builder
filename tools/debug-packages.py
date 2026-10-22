# SPDX-License-Identifier: MIT
import os
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

root=Path(os.environ['PHP56_WORK'])
release=Path(os.environ['PHP56_OUTPUT'])
debug=release/'debug'
debug.mkdir(exist_ok=True)
work=root/'debug-build'
work.mkdir(exist_ok=True)
catalog=json.loads((Path(os.environ['PHP56_KIT'])/'assets/packages.lock.json').read_text())
records=json.loads((release/'package-catalog.json').read_text())

def build_id(path):
    output=subprocess.check_output(['readelf','-n',str(path)],stderr=subprocess.DEVNULL).decode()
    match=re.search(r'Build ID: ([a-f0-9]+)',output)
    assert match,str(path)
    return match.group(1)

def elf(path):
    if not path.is_file():
        return False
    with path.open('rb') as stream:
        return stream.read(4)==b'\x7fELF'

candidates=[]
core=root/'build/php5.6/source'
for tree in core.glob('*-build'):
    candidates+=list((tree/'modules').glob('*.so'))+list((tree/'libs').glob('*.so'))
    for relative in ['sapi/cli/php','sapi/cgi/php-cgi','sapi/fpm/php-fpm','sapi/phpdbg/phpdbg']:
        candidate=tree/relative
        if candidate.exists():
            candidates.append(candidate)
for source in (root/'build').glob('*/source'):
    candidates+=list((source/'build-5.6/modules').glob('*.so'))
by_id={}
for candidate in candidates:
    if elf(candidate):
        by_id.setdefault(build_id(candidate),candidate)

output=[]
for record in records:
    name=record['name']+'-dbgsym'
    if name not in catalog:
        continue
    stage=work/(record['name']+'-runtime')
    stage.mkdir(exist_ok=True)
    subprocess.check_call(['dpkg-deb','-x',str(release/'packages'/record['filename']),str(stage)])
    package=work/name
    (package/'DEBIAN').mkdir(parents=True,exist_ok=True)
    identifiers=set()
    for binary in stage.rglob('*'):
        if not elf(binary):
            continue
        identifier=build_id(binary)
        if identifier in identifiers:
            continue
        assert identifier in by_id,(name,str(binary),identifier)
        original=by_id[identifier]
        symbol=package/'usr/lib/debug/.build-id'/identifier[:2]/(identifier[2:]+'.debug')
        symbol.parent.mkdir(parents=True,exist_ok=True)
        subprocess.check_call(['objcopy','--only-keep-debug',str(original),str(symbol)])
        assert build_id(symbol)==identifier
        sections=subprocess.check_output(['readelf','-S',str(symbol)]).decode()
        assert '.debug_info' in sections,(name,str(original))
        identifiers.add(identifier)
    assert identifiers,name
    arch=subprocess.check_output(['dpkg','--print-architecture']).decode().strip()
    control=('Package: '+name+'\nVersion: '+record['version']+'\nArchitecture: '+arch+'\n'
             'Source: '+record['source'].split(' ')[0]+'\nSection: debug\nPriority: optional\n'
             'Maintainer: Local PHP Builds <root@localhost>\n'
             'Depends: '+record['name']+' (= '+record['version']+')\n'
             'Auto-Built-Package: debug-symbols\nBuild-Ids: '+' '.join(sorted(identifiers))+'\n'
             'Description: debug symbols for '+record['name']+' php2shell build\n'
             ' Symbols are selected from the matching unstripped binaries by ELF Build ID.\n')
    (package/'DEBIAN/control').write_text(control)
    filename=name+'_'+record['version'].split(':')[-1]+'_'+arch+'.deb'
    destination=debug/filename
    subprocess.check_call(['dpkg-deb','-Zxz','-z3','--build',str(package),str(destination)],stdout=subprocess.DEVNULL)
    output.append({'name':name,'version':record['version'],'filename':filename,
                   'build_ids':sorted(identifiers),'sha256':hashlib.sha256(destination.read_bytes()).hexdigest()})
    print(name,len(identifiers),'matching ELF Build IDs',flush=True)

common=next(record for record in records if record['name']=='php5.6-common')
version=common['version']
compat=work/'php5.6-dbg'
(compat/'DEBIAN').mkdir(parents=True,exist_ok=True)
(compat/'DEBIAN/control').write_text(
    'Package: php5.6-dbg\nVersion: '+version+'\nArchitecture: all\nSource: php5.6\n'
    'Section: debug\nPriority: optional\nMaintainer: Local PHP Builds <root@localhost>\n'
    'Depends: php5.6-cli-dbgsym (= '+version+'), php5.6-common-dbgsym (= '+version+')\n'
    'Description: compatibility package for PHP 5.6 CLI and common debug symbols\n'
    ' Other SAPIs and extensions have individual matching -dbgsym packages.\n')
filename='php5.6-dbg_'+version+'_all.deb'
subprocess.check_call(['dpkg-deb','--build',str(compat),str(debug/filename)],stdout=subprocess.DEVNULL)
output.append({'name':'php5.6-dbg','version':version,'filename':filename,
               'sha256':hashlib.sha256((debug/filename).read_bytes()).hexdigest(),
               'compatibility_metapackage':True})
expected={r['name']+'-dbgsym' for r in records if r['name']+'-dbgsym' in catalog} | {'php5.6-dbg'}
assert {record['name'] for record in output}==expected
(release/'debug-catalog.json').write_text(json.dumps(output,indent=2))
print('Built',len(output),'debug packages, covering every historical debug package name')
