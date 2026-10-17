import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from architecture import build,room_layout,Surfaces
from planar import ScanMesh,face_data
from floorplan import build as build_floorplan


def fixture(root):
    parts=['0','SECTION','2','ENTITIES']
    def poly(layer,points):
        parts.extend(['0','LWPOLYLINE','8','Polycam-Floor_1-'+layer])
        for x,z in points:parts.extend(['10',str(x),'20',str(z)])
    poly('Floors',[[-4550,-5850],[4550,-5850],[4550,5850],[-4550,5850],[-4550,-5850]])
    poly('Walls',[[4550,-100],[3900,-100],[3900,100],[4550,100]])
    poly('Openings-Windows',[[4500,300],[4600,300],[4600,5500],[4500,5500],[4500,300]])
    poly('Openings-Doors',[[-4600,-2200],[-4500,-2200],[-4500,-1200],[-4600,-1200],[-4600,-2200]])
    parts.extend(['0','ENDSEC','0','EOF']);(root/'plan.dxf').write_text('\n'.join(parts))
    (root/'plan.csv').write_text('Settings,Wall thickness [mm],100\nRoom,Window dimensions [mm],5200 x 2000\nRoom,Door dimensions [mm],1000 x 2100\n')
    surfaces=Surfaces();surfaces.quad('floor',[[-4.5,0,-5.8],[4.5,0,-5.8],[4.5,0,5.8],[-4.5,0,5.8]])
    surfaces.quad('ceiling',[[-4.5,3.2,-5.8],[4.5,3.2,-5.8],[4.5,3.2,5.8],[-4.5,3.2,5.8]])
    surfaces.quad('beam',[[-4.5,2.9,-.2],[4.5,2.9,-.2],[4.5,2.9,.2],[-4.5,2.9,.2]])
    surfaces.glb(root/'source.glb',[1,1,1],{})
    planes=[{'id':0,'kind':'horizontal','areaM2':100,'normal':[0,1,0],'constant':0},
            {'id':1,'kind':'horizontal','areaM2':80,'normal':[0,1,0],'constant':-3.2},
            {'id':2,'kind':'horizontal','areaM2':5,'normal':[0,1,0],'constant':-2.9}]
    for z in [-.2,.2]:planes.append({'id':len(planes),'kind':'vertical','areaM2':2,'normal':[0,0,1],'constant':-z,'bounds':[[3.9,0,z],[4.5,2.9,z]]})
    return planes


class ArchitectureTests(unittest.TestCase):
    def test_exact_independent_constraints_and_axis_aligned_surfaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);planes=fixture(root);raw=(root/'source.glb').read_bytes()
            with patch('architecture.discover_planes',return_value=(planes,None,'CPU')):
                r=build(root/'source.glb',root/'plan.dxf',root/'plan.csv',root,12.1,8.3)
            mesh=ScanMesh(root/'architectural.glb');size=np.ptp(mesh.vertices,axis=0)
            self.assertAlmostEqual(size[2],12.1,places=5)
            wall=next(p for p in r['planes'] if p['name']=='Стена с дверями')
            node=next(n for n in mesh.doc['nodes'] if n['name']=='Выступ у окон')
            primitive=mesh.doc['meshes'][node['mesh']]['primitives'][0]
            front=mesh.array(primitive['attributes']['POSITION'])[0,0]
            self.assertAlmostEqual(front+wall['constant'],8.3,places=5)
            _,normals,area=face_data(mesh.vertices,mesh.faces)
            self.assertTrue((area>1e-9).all());self.assertTrue((abs(normals).max(axis=1)>1-1e-9).all())
            self.assertEqual((root/'source.glb').read_bytes(),raw)
            self.assertEqual(r['sourceHash'],hashlib.sha256(raw).hexdigest())
            self.assertFalse(r['accuracyVerified']);self.assertTrue((root/'architectural-plan.svg').exists())
            dxf=(root/'architectural.dxf').read_text();self.assertIn('$INSUNITS\n70\n4',dxf)
            self.assertEqual(dxf.count('\n3DFACE\n'),len(mesh.faces)//2)
            plan=build_floorplan(root/'architectural.glb',root)
            self.assertGreaterEqual(len(plan['walls']),6)
            self.assertAlmostEqual(plan['factor'],1)
            self.assertTrue((root/'floorplan.svg').exists())

    def test_height_reference_does_not_change_horizontal_constraints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);planes=fixture(root)
            with patch('architecture.discover_planes',return_value=(planes,None,'CPU')):
                r=build(root/'source.glb',root/'plan.dxf',root/'plan.csv',root,12.1,8.3,3.7)
            size=np.ptp(ScanMesh(root/'architectural.glb').vertices,axis=0)
            self.assertAlmostEqual(size[1],3.7,places=5);self.assertAlmostEqual(size[2],12.1,places=5)

    def test_invalid_dimensions_and_missing_reference_pier_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root)
            with self.assertRaises(ValueError):build(root/'source.glb',root/'plan.dxf',root/'plan.csv',root,float('nan'),8)
            with self.assertRaises(ValueError):build(root/'source.glb',root/'plan.dxf',root/'plan.csv',root,0,8)
            (root/'plan.dxf').write_text('0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF')
            with self.assertRaises(ValueError):room_layout(root/'plan.dxf',root/'plan.csv')


if __name__=='__main__':unittest.main()
