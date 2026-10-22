"""Offline tests for plan selection, integrity handling and recipe adaptation.

These tests do NOT compile PHP or certify any Ubuntu target.
SPDX-License-Identifier: MIT
"""
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location('builder', str(ROOT / 'scripts/build.py'))
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class BuilderTests(unittest.TestCase):
    def args(self, extensions=None, core_only=False):
        return argparse.Namespace(extensions=extensions, core_only=core_only)

    def test_complete_catalog_and_dependency_order(self):
        selected = builder.select_sources(self.args())
        self.assertEqual(len(selected), 45)
        runtime = [name for name in builder.CATALOG if not name.endswith(('-dbg', '-dbgsym'))]
        self.assertEqual(len(runtime), 80)
        self.assertEqual(sum(builder.CATALOG[n]['source'] == 'php5.6' for n in runtime), 39)
        for name, dependencies in builder.EDGES.items():
            for dependency in dependencies:
                self.assertLess(selected.index(dependency), selected.index(name))
        self.assertEqual(set(selected), set(builder.SOURCES))

    def test_memcached_selects_serializers_and_header_dependencies(self):
        self.assertEqual(builder.select_sources(self.args('memcached')),
                         ['php-defaults', 'dh-php', 'tidy-html5', 'php5.6',
                          'php-apcu', 'php-igbinary', 'php-msgpack', 'php-memcached'])

    def test_invalid_selection_fails(self):
        for name in ['unknown', '../x', 'php5.6-cli', 'memcached;false', 'memcached-dbgsym', '']:
            if name == '':
                continue
            with self.assertRaises(ValueError):
                builder.select_sources(self.args(name))
        with self.assertRaises(ValueError):
            builder.select_sources(self.args('memcached', True))

    def test_no_cross_distro_version_reuse(self):
        versions = [builder.version('php5.6', target) for target in ['16.04', '18.04', '20.04']]
        self.assertEqual(len(set(versions)), 3)
        for target, version in zip(['16.04', '18.04', '20.04'], versions):
            self.assertIn('+ubuntu' + target + '.1', version)

    def test_tidy_preserves_signed_source_epoch(self):
        # Without epoch 2 the built library cannot satisfy libtidy-dev >= 1:5.2.
        value = builder.version('tidy-html5', '16.04')
        self.assertTrue(value.startswith('2:5.6.0-'))
        self.assertEqual(subprocess.call(['dpkg', '--compare-versions', value, 'ge', '1:5.2.0']), 0)

    def test_lock_files_contain_only_pinned_https_components(self):
        for name, record in builder.SOURCES.items():
            self.assertEqual(name, record['source'])
            self.assertRegex(record['dsc_sha256'], r'^[a-f0-9]{64}$')
            self.assertTrue(record['url'].startswith('https://'))
            for component in record['files']:
                self.assertEqual(Path(component['filename']).name, component['filename'])
                self.assertNotIn('..', component['filename'])
                self.assertRegex(component['sha256'], r'^[a-f0-9]{64}$')
                self.assertGreater(component['size'], 0)
        php = builder.SOURCES['php5.6']
        original = next(c for c in php['files'] if '.orig.tar.' in c['filename'])
        self.assertEqual(original['sha256'], '1369a51eee3995d7fbd1c5342e5cc917760e276d561595b6052b21ace2656d1c')

    def test_checksum_mismatch_is_a_hard_error(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'source.tar.xz'
            destination.write_bytes(b'old-corrupt-cache')
            def corrupted_download(command):
                Path(command[command.index('--output') + 1]).write_bytes(b'tampered-download')
            with mock.patch.object(builder, 'run', side_effect=corrupted_download):
                with self.assertRaises(RuntimeError):
                    builder.fetch('https://example.invalid/source', destination, hashlib.sha256(b'expected').hexdigest())
            self.assertFalse(Path(str(destination) + '.part').exists())
            self.assertEqual(destination.read_bytes(), b'old-corrupt-cache')

    def test_known_recipe_drift_is_not_silently_ignored(self):
        with self.assertRaises(RuntimeError):
            builder.replace_once('missing original recipe line', 'expected', 'replacement')
        with self.assertRaises(RuntimeError):
            builder.replace_once('expected expected', 'expected', 'replacement')

    def test_pecl_targets_only_php56_and_exact_core(self):
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            (tree / 'debian').mkdir()
            (tree / 'debian/rules').write_text('#!/usr/bin/make -f\nDH_PHP_VERSIONS_OVERRIDE := 7.4\n'
                'PHP_DEFAULT_VERSION_OVERRIDE := 7.4\ninclude /usr/share/dh-php/pkg-pecl.mk\n')
            control = ('Source: php-pecl-http\nBuild-Depends: php-all-dev (>= 80~), '
                       'php-propro-all-dev, php-raphf-all-dev, libidn2-dev\n\n'
                       'Package: php-http\nPre-Depends: php-common (>= 2:69~)\nDepends: ${misc:Depends}\n')
            (tree / 'debian/control').write_text(control)
            (tree / 'debian/control.in').write_text(control)
            (tree / 'debian/changelog').write_text('Original changelog\n')
            core = builder.version('php5.6', '16.04')
            builder.adapt_pecl(tree, 'php-pecl-http', '16.04', core)
            rules = (tree / 'debian/rules').read_text()
            self.assertNotIn('7.4', rules)
            self.assertIn('DH_PHP_VERSIONS_OVERRIDE := 5.6', rules)
            control = (tree / 'debian/control').read_text()
            self.assertIn('php5.6-dev, php5.6-propro, php5.6-raphf, libidn2-0-dev', control)
            self.assertIn('Depends: php5.6-common (= ' + core + '), ', control)
            self.assertIn('Pre-Depends: php-common (>= 2:69~)', control)
            self.assertEqual(control, (tree / 'debian/control.in').read_text())

    def test_plan_does_not_run_docker_or_compilation(self):
        result = subprocess.check_output(['bash', str(ROOT / 'build.sh'), '--ubuntu', '20.04',
                                          '--core-only', '--plan']).decode()
        plan = json.loads(result)
        self.assertEqual(plan['status'], 'COMPILATION TEST REQUIRED')
        self.assertEqual(len(plan['sources_in_order']), 4)

    def test_native_plan_does_not_install_packages(self):
        result = subprocess.check_output(['bash', str(ROOT / 'build.sh'), '--ubuntu', '16.04',
                                          '--native', '--core-only', '--plan']).decode()
        self.assertEqual(json.loads(result)['status'], 'COMPILATION TEST REQUIRED')

    def test_pecl_last_dependency_keeps_the_following_control_field(self):
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            (tree / 'debian').mkdir()
            (tree / 'debian/rules').write_text('#!/usr/bin/make -f\ninclude /usr/share/dh-php/pkg-pecl.mk\n')
            (tree / 'debian/control').write_text('Source: php-amqp\nBuild-Depends: php-all-dev\n'
                                                'Standards-Version: 4.5.1\n\nPackage: php-amqp\nDepends: ${misc:Depends}\n')
            (tree / 'debian/changelog').write_text('Original changelog\n')
            builder.adapt_pecl(tree, 'php-amqp', '16.04', builder.version('php5.6', '16.04'))
            self.assertIn('Build-Depends: php5.6-dev\nStandards-Version: 4.5.1\n',
                          (tree / 'debian/control').read_text())

    def test_invalid_cli_options_fail(self):
        for options in [['--ubuntu', '22.04', '--plan'], ['--ubuntu', '16.04', '--jobs', '0', '--plan'],
                        ['--ubuntu', '16.04', '--extensions', 'missing', '--plan']]:
            result = subprocess.run(['bash', str(ROOT / 'build.sh')] + options,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertNotEqual(result.returncode, 0)

    def test_legacy_python_syntax(self):
        for directory in ['scripts', 'tools', 'validation']:
            for path in (ROOT / directory).glob('*.py'):
                ast.parse(path.read_text(), filename=str(path), feature_version=(3, 5))


if __name__ == '__main__':
    unittest.main()
