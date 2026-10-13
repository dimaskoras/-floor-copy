import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from floorplan import section,build
from reconstruct import write_glb
from baseline import fit_baseline


def wall_with_door():
    vertices=[];faces=[]
    # 4m wall, 2.5m high; 1m doorway from x=1 to x=2, height 2m.
    for x0,x1,y0,y1 in [(0,1,0,2.5),(1,2,2,2.5),(2,4,0,2.5)]:
        i=len(vertices);vertices.extend([[x0,y0,0],[x1,y0,0],[x1,y1,0],[x0,y1,0]]);faces.extend([[i,i+1,i+2],[i,i+2,i+3]])
    plane={'id':0,'kind':'vertical','normal':[0,0,1],'constant':0,'areaM2':8,'bounds':[[0,0,0],[4,2.5,0]],'p95ResidualMm':0}
    return np.array(vertices,dtype=np.float32),np.array(faces),[plane]


class FloorplanTests(unittest.TestCase):
    def test_opening_is_candidate_not_certified_door(self):
        v,f,p=wall_with_door();walls=section(v,f,p,1.1)
        self.assertEqual(len(walls),1);self.assertAlmostEqual(walls[0]['observedLengthRaw'],3)
        self.assertAlmostEqual(walls[0]['gaps'][0]['widthRaw'],1)
        self.assertEqual(walls[0]['gaps'][0]['type'],'unknown')
        self.assertFalse(walls[0]['gaps'][0]['verified'])
        self.assertEqual(section(v,f,p,2.2)[0]['gaps'],[])

    def test_export_metric_scale_and_no_invented_room(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);v,f,p=wall_with_door();write_glb(root/'mesh.glb',v,np.full((len(v),3),100,dtype=np.uint8),f)
            (root/'planes.json').write_text(json.dumps({'planes':p}))
            report=build(root/'mesh.glb',root,1.1)
            self.assertAlmostEqual(report['walls'][0]['gaps'][0]['widthMeters'],1.1)
            self.assertIsNone(report['observedFloorAreaM2']);self.assertFalse(report['gostCompliant'])
            self.assertIn('420mm',(root/'floorplan.svg').read_text(encoding='utf-8'))
            self.assertIn('$INSUNITS\n70\n4',(root/'floorplan.dxf').read_text())
            self.assertTrue((root/'floorplan.csv').exists())
            with self.assertRaises(ValueError):build(root/'mesh.glb',root,1.1,3)

    def test_conflicting_baseline_retains_residuals(self):
        profile=fit_baseline([3.205045,5.510891],[3.42,5.54])
        self.assertAlmostEqual(profile['factor'],1.020898,places=5)
        self.assertGreater(abs(profile['references'][0]['residualMeters']),.14)
        self.assertFalse(profile['accuracyVerified'])
        with self.assertRaises(ValueError):fit_baseline([0],[3])


if __name__=='__main__':unittest.main()
