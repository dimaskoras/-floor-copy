"""Conservative planar regularization of a single Scaniverse mesh.

Does not infer missing walls, enforce right angles, or certify dimensions.
Texture coordinates, topology, and the original embedded image are preserved.
"""
import json
import struct
from pathlib import Path

import numpy as np
import gpu
from scipy.sparse import coo_matrix, diags


class ScanMesh:
    def __init__(self, path):
        raw = Path(path).read_bytes()
        magic, version, total = struct.unpack_from('<III', raw)
        if (magic, version, total) != (0x46546c67, 2, len(raw)):
            raise ValueError('Некорректный GLB')
        length, kind = struct.unpack_from('<II', raw, 12)
        if kind != 0x4e4f534a:
            raise ValueError('GLB без JSON')
        self.doc = json.loads(raw[20:20+length])
        cursor = 20+length
        binary_size, binary_kind = struct.unpack_from('<II', raw, cursor)
        if binary_kind != 0x004e4942:
            raise ValueError('Нужна встроенная геометрия GLB')
        self.binary = bytearray(raw[cursor+8:cursor+8+binary_size])
        if len(self.doc.get('meshes', [])) != 1 or len(self.doc['meshes'][0]['primitives']) != 1:
            raise ValueError('Пока поддерживается одна сетка в GLB')
        for node in self.doc.get('nodes', []):
            identity = (np.allclose(node.get('translation', [0,0,0]), [0,0,0])
                        and np.allclose(node.get('rotation', [0,0,0,1]), [0,0,0,1])
                        and np.allclose(node.get('scale', [1,1,1]), [1,1,1])
                        and np.allclose(node.get('matrix', np.eye(4).ravel().tolist()), np.eye(4).ravel()))
            if not identity:
                raise ValueError('GLB с преобразованиями узлов пока нельзя выравнивать')
        self.primitive = self.doc['meshes'][0]['primitives'][0]
        if self.primitive.get('mode',4) != 4:
            raise ValueError('Нужна треугольная сетка, а не splat')
        self.position_id = self.primitive['attributes']['POSITION']
        self.vertices = self.array(self.position_id).astype(np.float64)
        self.faces = self.array(self.primitive['indices']).reshape(-1,3).astype(np.int64)
        if len(self.faces) and (self.faces.min() < 0 or self.faces.max() >= len(self.vertices)):
            raise ValueError('Некорректные индексы треугольников')
        if not np.isfinite(self.vertices).all():
            raise ValueError('Некорректные вершины')

    def array(self, index):
        accessor = self.doc['accessors'][index]
        if 'sparse' in accessor:
            raise ValueError('Sparse accessors пока не поддерживаются')
        view = self.doc['bufferViews'][accessor['bufferView']]
        dtype = {5126:'<f4',5125:'<u4',5123:'<u2',5121:'u1'}[accessor['componentType']]
        columns = {'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}[accessor['type']]
        item = np.dtype(dtype).itemsize
        offset = view.get('byteOffset',0)+accessor.get('byteOffset',0)
        stride = view.get('byteStride',columns*item)
        return np.ndarray((accessor['count'],columns), dtype=dtype, buffer=self.binary,
                          offset=offset,strides=(stride,item)).copy()

    def save(self, path, vertices):
        accessor = self.doc['accessors'][self.position_id]
        view = self.doc['bufferViews'][accessor['bufferView']]
        if accessor['componentType'] != 5126:
            raise ValueError('Нужны float32-координаты')
        offset = view.get('byteOffset',0)+accessor.get('byteOffset',0)
        stride = view.get('byteStride',12)
        destination = np.ndarray((len(vertices),3),dtype='<f4',buffer=self.binary,offset=offset,strides=(stride,4))
        destination[:] = vertices
        accessor['min'] = destination.min(axis=0).tolist()
        accessor['max'] = destination.max(axis=0).tolist()
        modified=not np.array_equal(destination,self.vertices.astype('<f4'))
        if modified:self.primitive['attributes'].pop('NORMAL',None)
        self.doc.setdefault('extras',{})['floorCopy'] = {'modifiedGeometry':modified,'accuracyVerified':False}
        doc = json.dumps(self.doc,separators=(',',':')).encode()
        doc += b' ' * (-len(doc)%4)
        binary = bytes(self.binary)
        binary += b'\0' * (-len(binary)%4)
        with open(path,'wb') as out:
            out.write(struct.pack('<III',0x46546c67,2,28+len(doc)+len(binary)))
            out.write(struct.pack('<II',len(doc),0x4e4f534a));out.write(doc)
            out.write(struct.pack('<II',len(binary),0x004e4942));out.write(binary)


def face_data(vertices, faces):
    triangles = vertices[faces]
    cross = np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
    lengths = np.linalg.norm(cross,axis=1)
    normals = cross/np.maximum(lengths[:,None],1e-15)
    return triangles.mean(axis=1), normals, lengths/2


def discover_planes(vertices, faces, threshold=.025, max_planes=16, minimum_area=.3):
    centers,normals,areas = face_data(vertices,faces)
    eligible = (areas > 1e-8) & ((np.abs(normals[:,1]) > .80) | (np.abs(normals[:,1]) < .35))
    rng = np.random.default_rng(2026)
    labels = np.full(len(faces),-1,np.int32)
    planes = []
    cp = gpu.cupy_backend()
    backend = 'CUDA' if cp is not None else 'CPU'
    for iteration in range(max_planes):
        remaining = np.flatnonzero(eligible & (labels < 0))
        if len(remaining) < 80:
            break
        sample = rng.choice(remaining,size=min(12000,len(remaining)),replace=False)
        candidates = rng.choice(remaining,size=min(192,len(remaining)),replace=False)
        n = normals[candidates].copy()
        horizontal = np.abs(n[:,1]) > .8
        # Gravity is known in ARKit coordinates. Only candidate seeds use it;
        # the final plane is fitted to actual data, without forcing orthogonality.
        n[horizontal] = [0,1,0]
        n[~horizontal,1] = 0
        n /= np.linalg.norm(n,axis=1)[:,None]
        d = -np.einsum('ij,ij->i',n,centers[candidates])
        if cp is not None:
            c_gpu = cp.asarray(centers[sample],dtype=cp.float32)
            normals_gpu = cp.asarray(normals[sample],dtype=cp.float32)
            seeds_gpu = cp.asarray(n.T,dtype=cp.float32)
            distance = cp.abs(c_gpu@seeds_gpu + cp.asarray(d,dtype=cp.float32))
            mask = (distance < threshold) & (cp.abs(normals_gpu@seeds_gpu) > .85)
            scores = cp.asnumpy(cp.sum(mask*cp.asarray(areas[sample],dtype=cp.float32)[:,None],axis=0))
        else:
            mask = (np.abs(centers[sample]@n.T+d)<threshold) & (np.abs(normals[sample]@n.T)>.85)
            scores = np.sum(mask*areas[sample,None],axis=0)
        best = int(np.argmax(scores))
        normal,constant = n[best],d[best]
        support = np.zeros(len(faces),bool)
        for _ in range(4):
            support = (labels<0) & eligible & (np.abs(centers@normal+constant)<threshold) & (np.abs(normals@normal)>.85)
            if support.sum() < 80:
                break
            points,weights = centers[support],areas[support]
            center = np.average(points,axis=0,weights=weights)
            delta = points-center
            covariance = (delta.T*weights)@delta/weights.sum()
            _,vectors = np.linalg.eigh(covariance)
            refined = vectors[:,0]
            if refined@normal < 0:refined=-refined
            normal,constant = refined,-refined@center
        support = (labels<0) & eligible & (np.abs(centers@normal+constant)<threshold) & (np.abs(normals@normal)>.85)
        area = float(areas[support].sum())
        if support.sum()<80 or area<minimum_area:
            break
        plane_id = len(planes)
        labels[support]=plane_id
        ids = np.unique(faces[support])
        points = vertices[ids]
        distances = points@normal+constant
        bounds = np.quantile(points,[.02,.98],axis=0)
        classification = 'horizontal' if abs(normal[1])>.9 else 'vertical' if abs(normal[1])<.25 else 'inclined'
        # Endpoints describe only observed support. Never extend them to invent walls.
        endpoints = None
        if classification=='vertical':
            tangent = np.array([-normal[2],0,normal[0]])
            tangent/=np.linalg.norm(tangent)
            anchor = points.mean(axis=0)
            t = (points-anchor)@tangent
            ends = anchor + np.quantile(t,[.02,.98])[:,None]*tangent
            endpoints = ends[:,[0,2]].tolist()
        planes.append({'id':plane_id,'kind':classification,'normal':normal.tolist(),'constant':float(constant),
                       'areaM2':area,'faces':int(support.sum()),'vertices':int(len(ids)),
                       'medianResidualMm':float(np.median(np.abs(distances))*1000),
                       'p95ResidualMm':float(np.quantile(np.abs(distances),.95)*1000),
                       'bounds':bounds.tolist(),'segmentXZ':endpoints})
        print(f'Plane {plane_id}: {classification}, area {area:.2f} m2',flush=True)
    if cp is not None:cp.get_default_memory_pool().free_all_blocks()
    return planes,labels,backend


def straighten(vertices,faces,planes,labels,max_shift=.005, architecture_only=False):
    # Texture seams duplicate geometric vertices. All aliases must receive the
    # same displacement, even if their triangle incidence differs.
    _,inverse,counts=np.unique(np.round(vertices,6),axis=0,return_inverse=True,return_counts=True)
    number=len(counts)
    welded=np.zeros((number,3));np.add.at(welded,inverse,vertices);welded/=counts[:,None]
    f=inverse[faces]
    use_labels=labels.copy()
    accepted=[]
    low,high=np.quantile(vertices[:,1],[.02,.98])
    for p in planes:
        if not architecture_only:
            accepted.append(p)
            continue
        midpoint=(p['bounds'][0][1]+p['bounds'][1][1])/2
        architecture=(p['kind']=='vertical' and p['areaM2']>=2.5 and p['bounds'][1][1]-p['bounds'][0][1]>=1.7) or (p['kind']=='horizontal' and p['areaM2']>=4 and min(abs(midpoint-low),abs(midpoint-high))<.15)
        if not architecture_only or architecture:accepted.append(p)
        else:use_labels[use_labels==p['id']]=-1
    incidence=np.bincount(f.ravel(),minlength=number)
    votes=np.bincount(f[use_labels>=0].ravel(),minlength=number)
    trusted=(votes>=2)&(votes>=incidence*.67)
    lhs=np.tile(np.eye(3)[None]*1e-6,(number,1,1));rhs=np.zeros_like(welded)
    for p in accepted:
        ids=np.unique(f[use_labels==p['id']]);n=np.array(p['normal'])
        distance=welded[ids]@n+p['constant']
        ids=ids[(np.abs(distance)<.025)&trusted[ids]]
        distance=welded[ids]@n+p['constant']
        lhs[ids]+=np.outer(n,n);rhs[ids]-=distance[:,None]*n
    active=np.linalg.norm(rhs,axis=1)>1e-10
    delta=np.zeros_like(welded)
    delta[active]=np.linalg.solve(lhs[active],rhs[active,:,None])[:,:,0]
    length=np.linalg.norm(delta,axis=1)
    delta*=np.minimum(1,max_shift/np.maximum(length,1e-15))[:,None]
    # Smooth the displacement field, not the surface itself. Fixed unsupported
    # vertices taper each patch into its untouched surroundings.
    edges=np.sort(np.concatenate([f[:,[0,1]],f[:,[1,2]],f[:,[2,0]]]),axis=1)
    edges=np.unique(edges,axis=0);edges=edges[edges[:,0]!=edges[:,1]]
    rows=np.r_[edges[:,0],edges[:,1]];cols=np.r_[edges[:,1],edges[:,0]]
    adjacency=coo_matrix((np.ones(len(rows)),(rows,cols)),shape=(number,number)).tocsr()
    avg=diags(1/np.maximum(np.asarray(adjacency.sum(axis=1)).ravel(),1))@adjacency
    for _ in range(8):
        delta=.35*delta+.65*(avg@delta)
        delta[~active]=0
    _,old_normals,old_area=face_data(vertices,faces)
    old_edges=np.linalg.norm(vertices[faces[:,[1,2,0]]]-vertices[faces],axis=2)
    factors=np.ones(number)
    rejected=np.zeros(len(faces),bool)
    for _ in range(32):
        result=vertices+(delta*factors[:,None])[inverse]
        _,normals,area=face_data(result,faces)
        edge_length=np.linalg.norm(result[faces[:,[1,2,0]]]-result[faces],axis=2)
        ratio=edge_length/np.maximum(old_edges,1e-10)
        unsafe=(old_area>1e-10)&((np.einsum('ij,ij->i',old_normals,normals)<np.cos(np.deg2rad(12))) | (area<old_area*.7) | (area>old_area*1.3) | (ratio.min(axis=1)<.8) | (ratio.max(axis=1)>1.2))
        if not unsafe.any():break
        rejected|=unsafe
        factors[np.unique(f[unsafe])]*=.5
    else:
        # Conservative final fallback: the unmodified mesh is preferable to
        # hiding a failed quality check behind a visually smooth result.
        result=vertices.copy();factors[:]=0
    shift=np.linalg.norm(result-vertices,axis=1)
    _,normals,_=face_data(result,faces)
    angles=np.degrees(np.arccos(np.clip(np.einsum('ij,ij->i',old_normals,normals),-1,1)))
    return result,{'movedVertices':int((shift>1e-6).sum()),'maximumShiftMm':float(shift.max()*1000),
                  'medianShiftMm':float(np.median(shift[shift>1e-6])*1000) if (shift>1e-6).any() else 0,
                  'restrictedFaces':int(rejected.sum()),'maximumNormalChangeDegrees':float(angles[old_area>1e-10].max()),
                  'weldedSeamGroups':int((counts>1).sum()),'profile':'architecture' if architecture_only else 'selected surfaces',
                  'processedPlanes':[p['id'] for p in accepted]}


def analyze(source,destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    mesh=ScanMesh(source)
    planes,labels,backend=discover_planes(mesh.vertices,mesh.faces)
    corrected,changes=straighten(mesh.vertices,mesh.faces,planes,labels,architecture_only=True)
    mesh.save(destination/'straightened.glb',corrected)
    report={'method':'seam-aware displacement regularization v2','processingVersion':2,'backend':backend,'planes':planes,'changes':changes,
            'bounds':np.array([mesh.vertices.min(axis=0),mesh.vertices.max(axis=0)]).tolist(),
            'accuracyVerified':False,'maximumAllowedShiftMeters':.005,
            'warnings':['Исправлены только небольшие отклонения от найденных плоскостей.',
                        'Пропущенные поверхности не восстановлены; мебель не заменена CAD-моделями.',
                        'Выделенные вертикальные плоскости могут принадлежать мебели, а не стенам.',
                        'План ниже показывает обнаруженные сегменты, а не подтверждённый контур помещения.']}
    (destination/'planes.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('source');parser.add_argument('destination')
    args=parser.parse_args();report=analyze(args.source,args.destination)
    print(json.dumps({k:v for k,v in report.items() if k!='planes'},ensure_ascii=False))
