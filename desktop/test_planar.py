import tempfile
import unittest
from pathlib import Path
import numpy as np
from planar import discover_planes,straighten,face_data,ScanMesh
from reconstruct import write_glb


class PlanarTests(unittest.TestCase):
    def test_small_waves_keep_orientation_and_bound(self):
        x,z=np.meshgrid(np.linspace(0,2,25),np.linspace(0,2,25))
        vertices=np.c_[x.ravel(),(.006*np.sin(x*2)*np.cos(z)).ravel(),z.ravel()]
        faces=[]
        for j in range(24):
            for i in range(24):
                a=j*25+i;faces.extend([[a,a+1,a+25],[a+1,a+26,a+25]])
        faces=np.array(faces)
        planes,labels,_=discover_planes(vertices,faces,max_planes=1)
        self.assertEqual(len(planes),1)
        result,report=straighten(vertices,faces,planes,labels)
        self.assertGreater(report['movedVertices'],300)
        self.assertLessEqual(report['maximumShiftMm'],5.001)
        _,normal_before,_=face_data(vertices,faces)
        _,normal_after,_=face_data(result,faces)
        self.assertTrue((np.einsum('ij,ij->i',normal_before,normal_after)>0).all())
        self.assertLessEqual(report['maximumNormalChangeDegrees'],12.001)

    def test_texture_seam_aliases_move_together(self):
        x,z=np.meshgrid(np.linspace(0,2,20),np.linspace(0,2,20))
        base=np.c_[x.ravel(),(.007*np.sin(x*2)).ravel(),z.ravel()]
        vertices=np.vstack([base,base]);faces=[]
        for j in range(19):
            for i in range(19):
                a=j*20+i;faces.extend([[a,a+1,a+20],[a+1+400,a+21+400,a+20+400]])
        faces=np.array(faces)
        planes,labels,_=discover_planes(vertices,faces,max_planes=1)
        result,_=straighten(vertices,faces,planes,labels)
        np.testing.assert_allclose(result[:400],result[400:],atol=1e-12)

    def test_glb_rewrite_preserves_topology_and_color(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);v=np.array([[0,0,0],[1,0,0],[0,0,1]],dtype='<f4');f=np.array([[0,1,2]])
            write_glb(root/'a.glb',v,np.full((3,3),100,dtype='u1'),f)
            mesh=ScanMesh(root/'a.glb')
            colors=mesh.array(mesh.primitive['attributes']['COLOR_0'])
            modified=v.copy();modified[:,1]=.01;mesh.save(root/'b.glb',modified)
            result=ScanMesh(root/'b.glb')
            np.testing.assert_array_equal(result.faces,mesh.faces)
            np.testing.assert_array_equal(result.array(result.primitive['attributes']['COLOR_0']),colors)
            np.testing.assert_allclose(result.vertices[:,1],.01)

    def test_large_correction_is_rejected(self):
        v=np.array([[0,.2,0],[1,.2,0],[0,.2,1],[1,.2,1]])
        f=np.array([[0,1,2],[1,3,2]])
        result,report=straighten(v,f,[{'id':0,'normal':[0,1,0],'constant':0}],np.array([0,0]))
        np.testing.assert_array_equal(result,v)
        self.assertEqual(report['movedVertices'],0)


if __name__=='__main__':unittest.main()
