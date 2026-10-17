import io
import tempfile
import unittest
from pathlib import Path
import numpy as np
from PIL import Image
from architecture import Surfaces
from planar import ScanMesh
from photo_bake import PhotoBaker


class FixtureAtlas:
    def atlas(self, quads, neutral):
        rgb=np.zeros((32,32,3),dtype=np.uint8)
        rgb[:16,:16]=[230,30,20];rgb[:16,16:]=[20,220,30]
        rgb[16:,:16]=[20,30,230];rgb[16:,16:]=[220,210,20]
        out=io.BytesIO();Image.fromarray(rgb).save(out,format='JPEG',quality=100,subsampling=0)
        return out.getvalue(),np.array([[0,0],[1,0],[1,1],[0,1]]*len(quads),dtype='<f4')


class PhotoBakeTests(unittest.TestCase):
    def test_photo_orientation_unobserved_and_furniture_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source.glb';surfaces=Surfaces()
            q=np.array([[0,0,0],[1,0,0],[1,0,1],[0,0,1]],dtype=float)
            surfaces.quad('floor',q)
            surfaces.quad('desk',q+[1, .8, 0])
            surfaces.glb(source,[1,1,1],{},FixtureAtlas())
            before=source.read_bytes();baker=PhotoBaker(ScanMesh(source),pixels_per_meter=32)
            patch=baker.patch(q,32,32,[184,191,196])
            for y,x,color in [(5,5,[230,30,20]),(5,25,[20,220,30]),(25,5,[20,30,230]),(25,25,[220,210,20])]:
                np.testing.assert_allclose(patch[y,x],color,atol=2)
            # No source floor exists below this tabletop: do not project it down.
            missing=baker.patch(q+[1,0,0],32,32,[184,191,196])
            np.testing.assert_array_equal(missing,np.broadcast_to([184,191,196],missing.shape))
            self.assertEqual(source.read_bytes(),before)
            # Nonuniform laser scaling affects geometry only; UVs stay in source coordinates.
            destination=Path(tmp)/'colored.glb';clean=Surfaces();clean.quad('floor',q)
            clean.glb(destination,[1.02,1,.97],{},baker)
            result=ScanMesh(destination)
            np.testing.assert_allclose(result.vertices,q*[1.02,1,.97],atol=1e-7)
            self.assertEqual(len(result.doc['images']),1)
            p=result.primitives[0];self.assertIn('TEXCOORD_0',p['attributes'])
            self.assertIn('baseColorTexture',result.doc['materials'][p['material']]['pbrMetallicRoughness'])
            self.assertFalse(baker.report()['geometryChanged'])
            windows=Surfaces();windows.quad('Фото окон и дверей',q+[0,1,0])
            clean.glb(destination,[1,1,1],{},baker,windows)
            self.assertEqual(len(ScanMesh(destination).faces),4)
            self.assertEqual(len(ScanMesh(destination,exclude_roles=('openingPhoto',)).faces),2)
            self.assertTrue(ScanMesh(destination).doc['nodes'][-1]['extras']['measurementExcluded'])

    def test_untextured_source_remains_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'plain.glb';s=Surfaces();s.quad('wall',[[0,0,0],[1,0,0],[1,1,0],[0,1,0]])
            s.glb(path,[1,1,1],{});baker=PhotoBaker(ScanMesh(path))
            self.assertIsNone(baker.atlas(s.parts['wall'],[180,180,180]))


if __name__=='__main__':unittest.main()
