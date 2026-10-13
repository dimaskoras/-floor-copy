import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from reconstruct import write_glb
from import_model import import_glb
from project_store import ProjectStore
import service


class ImportRegressionTests(unittest.TestCase):
    def test_point_glb_is_available_as_point_cloud(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'points-input.glb'
            write_glb(source,np.array([[0,0,0],[1,0,0],[0,1,0]],dtype='<f4'),np.full((3,3),120,dtype='u1'))
            result=import_glb(source,root/'result')
            self.assertFalse(result['mesh']);self.assertTrue(result['pointCloud'])
            self.assertEqual(result['availableFiles'],['points.glb'])
            self.assertEqual((root/'result/points.glb').read_bytes(),source.read_bytes())

    def test_interrupted_plan_recovers_after_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=ProjectStore(root);project=store.create('QA')
            project['plan']={'source':'source-plan.png','state':'running'};store.save(project)
            with patch.object(service,'DATA',root),patch.object(service,'STORE',store),patch.object(service,'JOBS',{}):service.load()
            recovered=store.get(project['id'])['plan']
            self.assertEqual(recovered['state'],'error');self.assertIn('прерван',recovered['error'])
