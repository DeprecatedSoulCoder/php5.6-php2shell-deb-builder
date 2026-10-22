"""Reject incomplete/tampered/wrong-target packages without installing anything.

SPDX-License-Identifier: MIT
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location('checker', str(ROOT / 'scripts/check-debs.py'))
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class PackageChecksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        (self.directory / 'packages').mkdir()
        self.status = {'status': 'PASS', 'ubuntu': '20.04'}
        (self.directory / 'build-status.json').write_text(json.dumps(self.status))
        self.record = {'name': 'php5.6-common', 'version': '5.6.40-local',
                       'architecture': 'amd64', 'filename': 'common.deb', 'depends': '',
                       'sha256': hashlib.sha256(b'package-fixture').hexdigest()}
        (self.directory / 'packages/common.deb').write_bytes(b'package-fixture')
        (self.directory / 'package-catalog.json').write_text(json.dumps([self.record]))
        original_read = Path.read_text
        def read_text(path, *args, **kwargs):
            if str(path) == '/etc/os-release':
                return 'ID=ubuntu\nVERSION_ID="20.04"\n'
            return original_read(path, *args, **kwargs)
        patch = mock.patch.object(Path, 'read_text', read_text)
        patch.start()
        self.addCleanup(patch.stop)
        self.output = mock.patch.object(checker.subprocess, 'check_output', side_effect=self.command_output)
        self.output.start()
        self.addCleanup(self.output.stop)

    def command_output(self, command):
        if command == ['dpkg', '--print-architecture']:
            return b'amd64\n'
        if command[0] == 'dpkg-query':
            return b'php5.6-unknown-extension\tii \n'
        return b'Package: php5.6-common\nVersion: 5.6.40-local\nArchitecture: amd64\n'

    def test_matching_package_is_selected_without_installation(self):
        files = checker.check(self.directory, ['php5.6-common'], False)
        self.assertEqual(files, [str(self.directory / 'packages/common.deb')])

    def test_failed_build_is_rejected(self):
        (self.directory / 'build-status.json').write_text(json.dumps({'status': 'FAIL'}))
        with self.assertRaisesRegex(ValueError, 'PASS'):
            checker.check(self.directory, ['php5.6-common'], False)

    def test_other_ubuntu_release_is_rejected(self):
        self.status['ubuntu'] = '16.04'
        (self.directory / 'build-status.json').write_text(json.dumps(self.status))
        with self.assertRaisesRegex(ValueError, 'same Ubuntu'):
            checker.check(self.directory, ['php5.6-common'], False)

    def test_modified_deb_is_rejected(self):
        (self.directory / 'packages/common.deb').write_bytes(b'modified')
        with self.assertRaisesRegex(ValueError, 'Checksum mismatch'):
            checker.check(self.directory, ['php5.6-common'], False)

    def test_internal_version_mismatch_is_rejected(self):
        self.record['version'] = 'wrong-version'
        (self.directory / 'package-catalog.json').write_text(json.dumps([self.record]))
        with self.assertRaisesRegex(ValueError, 'metadata/architecture'):
            checker.check(self.directory, ['php5.6-common'], False)

    def test_missing_rebuild_of_installed_extension_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Missing rebuilt package'):
            checker.check(self.directory, ['php5.6-common'], True)


if __name__ == '__main__':
    unittest.main()
