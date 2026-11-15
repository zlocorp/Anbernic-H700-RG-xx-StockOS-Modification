"""No app import: it provisions modules, probes network and touches /mnt at import time.
Execute the exact production data/manager class AST with stdlib dependencies instead.
Only subprocess scripts created inside TemporaryDirectory are executed.
"""
import ast
import base64
import dataclasses
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'Modified_System_Online_Upgrade/upgrade/installer.py'
module = types.ModuleType('manager_under_test')
sys.modules[module.__name__] = module
module.__dict__.update(vars(dataclasses))
module.__dict__.update(dict(os=os, json=json, base64=base64, tempfile=tempfile,
    shutil=shutil, subprocess=subprocess, Path=Path, time=time,
    LOGGER=logging.getLogger('test')))
nodes = ast.parse(SOURCE.read_text()).body
selected = [n for n in nodes if isinstance(n, ast.ClassDef) and n.name in ('SoftwarePackage', 'SoftwareManager')]
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)] + selected, type_ignores=[])), str(SOURCE), 'exec'), module.__dict__)
Manager, Package = module.SoftwareManager, module.SoftwarePackage

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = types.SimpleNamespace(database_path=str(self.root/'installed.json'), uninstall_path=str(self.root/'uninstall'), cache_path=str(self.root/'cache'))
        self.counter = self.root/'runs'

    def manager(self):
        m = Manager.__new__(Manager)
        m.cfg = self.cfg
        m.ui = types.SimpleNamespace(tips_info=lambda *a: None)
        m.t = types.SimpleNamespace(t=lambda s: s)
        m.software_list = []
        m.load_installed_software()
        if hasattr(m, 'load_pending_operations'):
            m.load_pending_operations()
        return m

    def package(self):
        return Package('demo', 'Demo', '2', 'tools', 0, '', '', '')

    def prepared(self, exit_code=0):
        root = Path(tempfile.mkdtemp(dir=self.root))
        payload = root/'payload'
        payload.mkdir()
        script = 'printf x >> "' + str(self.counter) + '"\nexit ' + str(exit_code) + '\n'
        (payload/'install.sh').write_text(script)
        (payload/'uninstall.sh').write_text(script)
        return str(root), str(payload)

    def pending_install(self):
        m, p = self.manager(), self.package()
        prepared = self.prepared()
        with patch.object(m, 'save_installed_software', return_value=False):
            self.assertFalse(m.install_software(p, prepared))
        self.assertEqual(self.counter.read_text(), 'x')
        return p, prepared

    def test_install_retry_after_restart_never_repeats_script(self):
        p, prepared = self.pending_install()
        m = self.manager()
        self.assertIn(p.id, getattr(m, 'pending_operations', {}))
        self.assertTrue(m.install_software(self.package()))
        self.assertEqual(self.counter.read_text(), 'x')
        self.assertEqual(self.manager().installed_software[p.id].local_version, '2')
        self.assertEqual(getattr(self.manager(), 'pending_operations', None), {})

    def test_install_recovers_when_staging_is_lost(self):
        p, prepared = self.pending_install()
        shutil.rmtree(prepared[0])
        m = self.manager()
        self.assertTrue(m.install_software(self.package()))
        self.assertTrue((Path(self.cfg.uninstall_path)/'tools/demo/uninstall.sh').is_file())
        self.assertEqual(self.counter.read_text(), 'x')

    def test_uninstall_retry_after_restart_never_repeats_script(self):
        m, p = self.manager(), self.package()
        self.assertTrue(m.install_software(p, self.prepared()))
        with patch.object(m, 'save_installed_software', return_value=False):
            self.assertFalse(m.uninstall_software(p))
        m = self.manager()
        self.assertTrue(m.uninstall_software(p))
        self.assertEqual(self.counter.read_text(), 'xx')
        self.assertNotIn(p.id, self.manager().installed_software)

    def test_failed_script_cannot_be_automatically_repeated(self):
        m, p = self.manager(), self.package()
        self.assertFalse(m.install_software(p, self.prepared(1)))
        m = self.manager()
        self.assertFalse(m.install_software(p, self.prepared()))
        self.assertEqual(self.counter.read_text(), 'x')

    def test_corrupt_journal_blocks_install(self):
        (self.root/'pending-operations.json').write_text('{')
        m = self.manager()
        self.assertFalse(m.install_software(self.package(), self.prepared()))
        self.assertFalse(self.counter.exists())

    def test_failure_to_persist_intent_prevents_script(self):
        m = self.manager()
        with patch.object(module.os, 'replace', side_effect=OSError('disk full')):
            self.assertFalse(m.install_software(self.package(), self.prepared()))
        self.assertFalse(self.counter.exists())

    def test_completion_write_failure_blocks_retry_after_restart(self):
        m, p = self.manager(), self.package()
        original = os.replace
        calls = []
        def replace(src, dest):
            if str(dest).endswith('pending-operations.json'):
                calls.append(dest)
                if len(calls) == 2:
                    raise OSError('power interrupted completion save')
            return original(src, dest)
        with patch.object(module.os, 'replace', side_effect=replace):
            self.assertFalse(m.install_software(p, self.prepared()))
        self.assertFalse(self.manager().install_software(p, self.prepared()))
        self.assertEqual(self.counter.read_text(), 'x')

    def test_pending_blocks_other_mutations(self):
        self.pending_install()
        other = self.package()
        other.id = 'other'
        self.assertFalse(self.manager().install_software(other, self.prepared()))
        self.assertEqual(self.counter.read_text(), 'x')

    def test_retry_keeps_completed_version_not_new_catalog_version(self):
        self.pending_install()
        latest = self.package()
        latest.version = '3'
        self.assertTrue(self.manager().install_software(latest))
        self.assertEqual(self.manager().installed_software['demo'].local_version, '2')
        self.assertTrue(latest.update_available)

    def test_repeated_metadata_failure_survives_restart(self):
        p, _ = self.pending_install()
        m = self.manager()
        with patch.object(m, 'save_installed_software', return_value=False):
            self.assertFalse(m.install_software(p))
        self.assertTrue(self.manager().install_software(p))
        self.assertEqual(self.counter.read_text(), 'x')

    def test_preserves_unrelated_and_unknown_record_fields(self):
        record = dataclasses.asdict(self.package())
        record['future_field'] = {'keep': True}
        (self.root/'installed.json').write_text(json.dumps({'demo': record, 'unknown': {'legacy': 1}}))
        self.pending_install()
        self.assertTrue(self.manager().install_software(self.package()))
        records = json.loads((self.root/'installed.json').read_text())
        self.assertEqual(records['unknown'], {'legacy': 1})
        self.assertEqual(records['demo']['future_field'], {'keep': True})

    def test_missing_catalog_package_remains_selectable_for_recovery(self):
        self.pending_install()
        m = self.manager()
        m.cfg.repositories = [{'name': 'test', 'url': 'https://example.invalid'}]
        m.t.lang_code = 'en_US'
        response = types.SimpleNamespace(raise_for_status=lambda: None,
                                         json=lambda: {'software': []})
        m.session = types.SimpleNamespace(get=lambda *a, **kw: response)
        self.assertTrue(m.fetch_software_list())
        self.assertEqual([p.id for p in m.software_list], ['demo'])

    def test_offline_catalog_still_allows_pending_recovery(self):
        self.pending_install()
        m = self.manager()
        m.cfg.repositories = []
        self.assertTrue(m.fetch_software_list())
        self.assertEqual([p.id for p in m.software_list], ['demo'])

    def test_recovery_uses_uninstall_script_written_by_install(self):
        m, p = self.manager(), self.package()
        prepared = self.prepared()
        payload = Path(prepared[1])
        (payload/'uninstall.sh').unlink()
        with (payload/'install.sh').open('w') as script:
            script.write("printf '# generated uninstall\\n' > uninstall.sh\n")
        with patch.object(m, 'save_installed_software', return_value=False):
            self.assertFalse(m.install_software(p, prepared))
        shutil.rmtree(prepared[0])
        self.assertTrue(self.manager().install_software(p))
        saved = Path(self.cfg.uninstall_path)/'tools/demo/uninstall.sh'
        self.assertTrue(saved.is_file())
        self.assertEqual(saved.read_text(), '# generated uninstall\n')

    def test_interruption_during_script_blocks_retry(self):
        m, p = self.manager(), self.package()
        with patch.object(module.subprocess, 'run', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                m.install_software(p, self.prepared())
        self.assertFalse(self.manager().install_software(p, self.prepared()))
        self.assertFalse(self.counter.exists())

    def test_clear_failure_keeps_metadata_only_retry(self):
        m, p = self.manager(), self.package()
        original = os.replace
        count = []
        def replace(src, dest):
            if str(dest).endswith('pending-operations.json'):
                count.append(dest)
                if len(count) == 3:
                    raise OSError('cannot clear journal')
            return original(src, dest)
        with patch.object(module.os, 'replace', side_effect=replace):
            self.assertFalse(m.install_software(p, self.prepared()))
        self.assertTrue(self.manager().install_software(p))
        self.assertEqual(self.counter.read_text(), 'x')

    def test_unreadable_database_blocks_pending_recovery(self):
        p, _ = self.pending_install()
        (self.root/'installed.json').write_text('{')
        self.assertFalse(self.manager().install_software(p))
        self.assertEqual((self.root/'installed.json').read_text(), '{')
        self.assertEqual(self.counter.read_text(), 'x')

    def test_invalid_journal_shapes_fail_closed(self):
        for document in [[], {'version': 2, 'operations': {}},
                         {'version': 1, 'operations': {'demo': {}}},
                         {'version': 1, 'operations': []}]:
            with self.subTest(document=document):
                (self.root/'pending-operations.json').write_text(json.dumps(document))
                self.assertFalse(self.manager().install_software(self.package(), self.prepared()))
                self.assertFalse(self.counter.exists())

    def test_successful_install_and_uninstall_clear_journal(self):
        m, p = self.manager(), self.package()
        self.assertTrue(m.install_software(p, self.prepared()))
        self.assertEqual(getattr(self.manager(), 'pending_operations', None), {})
        self.assertTrue(m.uninstall_software(p))
        self.assertEqual(getattr(self.manager(), 'pending_operations', None), {})
        self.assertEqual(self.counter.read_text(), 'xx')

if __name__ == '__main__':
    unittest.main()
