import tempfile
import unittest
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
