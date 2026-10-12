import json
import struct
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image
from reconstruct import unproject, fuse, process, read_mesh, write_glb


def metadata(w=16, h=12):
    return {'depthWidth': w, 'depthHeight': h, 'imageWidth': w, 'imageHeight': h,
            'intrinsics': [8, 0, 0, 0, 8, 0, w/2, h/2, 1],
            'transform': np.eye(4).ravel(order='F').tolist()}


def fixture(path):
    meta = metadata()
    image = BytesIO()
    Image.new('RGB', (16, 12), (200, 80, 40)).save(image, 'JPEG')
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('manifest.json', json.dumps({'format': 'floorcopy-rgbd', 'version': 1, 'frames': 1}))
        z.writestr('00000.json', json.dumps(meta))
        z.writestr('00000.depth', np.full((12,16), 2, dtype='<f4').tobytes())
        z.writestr('00000.confidence', np.full((12,16), 2, dtype='u1').tobytes())
        z.writestr('00000.jpg', image.getvalue())
        z.writestr('mesh.ply', 'ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\nelement face 1\nproperty list uchar int vertex_indices\nend_header\n0 0 -2\n0.5 0 -2\n0 0.5 -2\n3 0 1 2\n')


class ReconstructionTests(unittest.TestCase):
    def test_camera_coordinate_axes(self):
        m = metadata(4,4)
        p, _ = unproject(np.full((4,4),2), np.full((4,4),2), Image.new('RGB',(4,4)), m, stride=1)
        np.testing.assert_allclose(p[10], [0,0,-2])
        self.assertLess(p[0,0],0)
        self.assertGreater(p[0,1],0)

    def test_pose_translation_and_rotation(self):
        m = metadata(4,4)
        pose = np.array([[0,0,1,3],[0,1,0,4],[-1,0,0,5],[0,0,0,1]],float)
        m['transform'] = pose.ravel(order='F').tolist()
        p, _ = unproject(np.full((4,4),2),np.full((4,4),2),Image.new('RGB',(4,4)),m,1)
        np.testing.assert_allclose(p[10],[1,4,5])

    def test_confidence_and_invalid_depth_filtered(self):
        d = np.array([[2,np.nan],[np.inf,-1]],float)
        p,_ = unproject(d,np.zeros((2,2)),Image.new('RGB',(2,2)),metadata(2,2),1)
        self.assertEqual(len(p),0)

    def test_voxel_averages_position_and_color(self):
        p,c = fuse(np.array([[.001,0,0],[.003,0,0],[1,0,0]]),np.array([[10,20,30],[30,40,50],[50,60,70]]))
        np.testing.assert_allclose(p[0],[.002,0,0],atol=1e-7)
        np.testing.assert_array_equal(c[0],[20,30,40])
        self.assertEqual(len(p),2)

    def test_glb_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'model.glb'
            write_glb(path,np.array([[0,0,-2],[1,0,-2],[0,1,-2]],dtype='<f4'),np.full((3,3),100,dtype='u1'),np.array([[0,1,2]]))
            raw=path.read_bytes()
            magic,version,length=struct.unpack_from('<III',raw)
            self.assertEqual((magic,version,length),(0x46546c67,2,len(raw)))
            size,kind=struct.unpack_from('<II',raw,12)
            doc=json.loads(raw[20:20+size])
            self.assertEqual(doc['meshes'][0]['primitives'][0]['mode'],4)
            self.assertEqual(doc['accessors'][1]['type'],'VEC4')
            for view in doc['bufferViews']:
                self.assertEqual(view['byteOffset']%4,0)

    def test_end_to_end_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root/'scan.zip')
            report=process(root/'scan.zip',root/'out')
            self.assertEqual(report['frames'],1)
            self.assertTrue(report['mesh'])
            self.assertFalse(report['accuracyVerified'])
            self.assertEqual(report['bounds'][0][2],-2)
            for name in ['points.ply','points.glb','mesh.ply','mesh.glb','report.json']:
                self.assertTrue((root/'out'/name).is_file())

    def test_bad_mesh_index_rejected(self):
        raw=b'ply\nformat ascii 1.0\nelement vertex 1\nelement face 1\nend_header\n0 0 0\n3 0 1 2\n'
        with self.assertRaises(ValueError):read_mesh(raw)

    def test_foreign_zip_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive=Path(tmp)/'bad.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('test.txt','hello')
            with self.assertRaises(ValueError):process(archive,Path(tmp)/'out')


if __name__ == '__main__':unittest.main()
