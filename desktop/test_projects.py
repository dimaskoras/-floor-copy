import tempfile
import unittest
import json
from pathlib import Path
from project_store import ProjectStore


class ProjectTests(unittest.TestCase):
    def test_persist_and_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ProjectStore(folder);p=store.create('Корпус ПК · этаж 5');store.attach(p['id'],'scan-1')
            reopened=ProjectStore(folder);saved=reopened.get(p['id']);self.assertEqual(saved['scans'],['scan-1']);self.assertEqual(saved['name'],p['name'])
    def test_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):ProjectStore(folder).get('../outside')
    def test_empty_name_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):ProjectStore(folder).create(' ')
    def test_new_project_inherits_optional_baseline_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            profile=Path(folder)/'default-calibration.json';profile.write_text(json.dumps({'factor':1.02,'enabled':True}))
            store=ProjectStore(folder);project=store.create('Test');self.assertEqual(project['baseline']['factor'],1.02)
            profile.write_text(json.dumps({'factor':1.1,'enabled':True}))
            self.assertEqual(store.get(project['id'])['baseline']['factor'],1.02)
    def test_archive_is_reversible_and_preserves_project(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ProjectStore(folder);project=store.create('Test');store.attach(project['id'],'scan-1')
            store.archive(project['id']);self.assertEqual(store.all(),[])
            self.assertEqual(store.all(True)[0]['scans'],['scan-1'])
            store.archive(project['id'],False);self.assertEqual(len(store.all()),1)
