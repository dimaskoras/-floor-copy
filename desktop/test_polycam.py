import copy
import json
import struct
import tempfile
import unittest
from pathlib import Path
import numpy as np
import laspy
from planar import ScanMesh
from reconstruct import write_glb
from las_processing import import_las


def two_part_glb(path,shared=False):
    first=Path(path).with_name('single.glb');vertices=np.array([[0,0,0],[1,0,0],[0,0,1]],dtype=np.float32)
    write_glb(first,vertices,np.full((3,3),120,dtype=np.uint8),np.array([[0,1,2]]))
    mesh=ScanMesh(first);doc=copy.deepcopy(mesh.doc);binary=bytes(mesh.binary)
    if shared:
        doc['meshes'].append(copy.deepcopy(doc['meshes'][0]))
    else:
        view_offset=len(doc['bufferViews']);accessor_offset=len(doc['accessors'])
        views=copy.deepcopy(doc['bufferViews']);accessors=copy.deepcopy(doc['accessors']);primitive=copy.deepcopy(doc['meshes'][0]['primitives'][0])
        for view in views:view['byteOffset']=view.get('byteOffset',0)+len(binary)
        for accessor in accessors:accessor['bufferView']+=view_offset
        for key,value in primitive['attributes'].items():primitive['attributes'][key]=value+accessor_offset
        primitive['indices']+=accessor_offset
        doc['bufferViews']+=views;doc['accessors']+=accessors;doc['meshes'].append({'primitives':[primitive]});binary+=binary
    doc['nodes']=[{'mesh':0},{'mesh':1}];doc['scenes']=[{'nodes':[0,1]}];doc['buffers'][0]['byteLength']=len(binary)
    payload=json.dumps(doc).encode();payload+=b' '*(-len(payload)%4)
    Path(path).write_bytes(struct.pack('<III',0x46546c67,2,28+len(payload)+len(binary))+struct.pack('<II',len(payload),0x4e4f534a)+payload+struct.pack('<II',len(binary),0x004e4942)+binary)


class PolycamTests(unittest.TestCase):
    def test_all_parts_are_processed_and_colors_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'parts.glb';two_part_glb(source);mesh=ScanMesh(source)
            self.assertEqual(len(mesh.vertices),6);self.assertEqual(mesh.faces.tolist(),[[0,1,2],[3,4,5]])
            colors=[mesh.array(p['attributes']['COLOR_0']) for p in mesh.primitives]
            modified=mesh.vertices.copy();modified[3:,1]=.01;mesh.save(Path(temp)/'out.glb',modified);result=ScanMesh(Path(temp)/'out.glb')
            np.testing.assert_allclose(result.vertices[:,1],[0,0,0,.01,.01,.01]);np.testing.assert_array_equal(result.faces,mesh.faces)
            for p,c in zip(result.primitives,colors):np.testing.assert_array_equal(result.array(p['attributes']['COLOR_0']),c)
    def test_shared_accessor_is_written_once(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'parts.glb';two_part_glb(source,True);mesh=ScanMesh(source)
            self.assertEqual(len(mesh.vertices),3);self.assertEqual(len(mesh.faces),2)
            modified=mesh.vertices.copy();modified[:,1]=.02;mesh.save(Path(temp)/'out.glb',modified)
            np.testing.assert_allclose(ScanMesh(Path(temp)/'out.glb').vertices[:,1],.02)
    def test_compressed_cloud_matches_las(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cloud=laspy.LasData(laspy.LasHeader(point_format=3,version='1.2'))
            cloud.x=[1,2,3];cloud.y=[2,3,4];cloud.z=[3,4,5];cloud.red=[257,514,771];cloud.green=[514,771,1028];cloud.blue=[771,1028,1285]
            cloud.write(root/'in.las');cloud.write(root/'in.laz');a=root/'a';b=root/'b';a.mkdir();b.mkdir()
            ra=import_las(root/'in.las',a);rb=import_las(root/'in.laz',b)
            self.assertEqual(ra['inputPoints'],rb['inputPoints']);self.assertEqual((a/'points.glb').read_bytes(),(b/'points.glb').read_bytes())


if __name__=='__main__':unittest.main()
