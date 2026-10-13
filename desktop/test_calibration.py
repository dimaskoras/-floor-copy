import json
import struct
import tempfile
import unittest
from pathlib import Path
import numpy as np
from calibration import reference,scale_glb
from reconstruct import write_glb


class CalibrationTests(unittest.TestCase):
    def test_height_reference_scales_all_axes(self):
        result=reference([[0,0,0],[0,2,0]],2.05,'Проём')
        self.assertAlmostEqual(result['factor'],1.025)
        self.assertAlmostEqual(10*result['factor'],10.25)
        self.assertAlmostEqual(6*result['factor']**2,6.30375)

    def test_invalid_reference_rejected(self):
        for points,real in [([[0,0,0],[0,0,0]],2),([[0,0,0],[0,2,0]],float('nan')),([[0,0,0],[0,2,0]],2050)]:
            with self.assertRaises(ValueError):reference(points,real)

    def test_scaled_export_preserves_binary_and_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.glb';target=root/'scaled.glb'
            write_glb(source,np.array([[0,0,0],[2,0,0],[0,0,3]],dtype='<f4'),np.full((3,3),100,dtype='u1'),np.array([[0,1,2]],dtype='<u4'))
            original=source.read_bytes();scale_glb(source,target,1.025);changed=target.read_bytes()
            self.assertEqual(original,source.read_bytes())
            a=struct.unpack_from('<I',original,12)[0];b=struct.unpack_from('<I',changed,12)[0]
            self.assertEqual(original[20+a:],changed[20+b:])
            doc=json.loads(changed[20:20+b]);wrapper=doc['nodes'][doc['scenes'][0]['nodes'][0]]
            self.assertEqual(wrapper['scale'],[1.025]*3)
            self.assertFalse(doc['extras']['metricCalibration']['accuracyVerified'])
