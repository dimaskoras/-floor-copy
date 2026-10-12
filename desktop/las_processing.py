import json
from pathlib import Path
import laspy
import numpy as np
from scipy.spatial import cKDTree
from planar import ScanMesh
from reconstruct import write_glb,write_ply,fuse


def import_las(source,destination,mesh_path=None,progress=lambda percent,message:None):
    destination=Path(destination)
    las=laspy.read(source)
    if len(las.points)==0 or len(las.points)>15000000:raise ValueError('LAS должен содержать от 1 до 15 млн точек')
    origin=np.asarray(las.header.offsets)
    local=np.c_[las.x,las.y,las.z]-origin
    points=np.c_[local[:,0],local[:,2],-local[:,1]]
    if not np.isfinite(points).all():raise ValueError('LAS содержит некорректные координаты')
    dimensions=set(las.point_format.dimension_names)
    if {'red','green','blue'}<=dimensions:
        raw=np.c_[las.red,las.green,las.blue]
        colors=(raw/(257 if raw.max()>255 else 1)).clip(0,255).astype('u1')
    else:colors=np.full((len(points),3),170,dtype='u1')
    alignment=None
    if mesh_path:
        progress(20,'Совмещаю LAS с GLB')
        mesh=ScanMesh(mesh_path);tree=cKDTree(mesh.vertices)
        rng=np.random.default_rng(2026);sample=points[rng.choice(len(points),min(8000,len(points)),replace=False)]
        ac=np.median(sample,axis=0);bc=np.median(mesh.vertices,axis=0);best=None
        for degrees in range(0,360,5):
            angle=np.deg2rad(degrees);c,s=np.cos(angle),np.sin(angle)
            rotation=np.array([[c,0,s],[0,1,0],[-s,0,c]]);translation=bc-ac@rotation.T
            dist,_=tree.query(sample@rotation.T+translation,workers=2)
            score=np.mean(np.sort(dist)[:max(1,int(len(dist)*.8))])
            if best is None or score<best[0]:best=(score,rotation,translation)
        _,rotation,translation=best
        for _ in range(60):
            proposed=sample@rotation.T+translation;dist,near=tree.query(proposed,workers=2)
            keep=dist<=min(.25,np.quantile(dist,.8))
            if keep.sum()<20:raise ValueError('LAS и GLB не удалось уверенно совместить')
            a,b=proposed[keep],mesh.vertices[near[keep]];a0,b0=a.mean(axis=0),b.mean(axis=0)
            u,_,vt=np.linalg.svd((a-a0).T@(b-b0));r=vt.T@u.T
            if np.linalg.det(r)<0:vt[-1]*=-1;r=vt.T@u.T
            t=b0-a0@r.T;rotation=r@rotation;translation=translation@r.T+t
            if np.linalg.norm(t)<1e-6 and np.linalg.norm(r-np.eye(3))<1e-6:break
        points=points@rotation.T+translation
        dist,_=tree.query(points[::max(1,len(points)//70000)],workers=2)
        alignment={'rotation':rotation.tolist(),'translation':translation.tolist(),
                   'medianDistanceMm':float(np.median(dist)*1000),'p90DistanceMm':float(np.quantile(dist,.9)*1000),
                   'accepted':bool(np.median(dist)<.06 and np.quantile(dist,.9)<.2),
                   'note':'Совмещение экспортов, не независимая проверка точности.'}
        if not alignment['accepted']:
            (destination/'alignment.json').write_text(json.dumps(alignment,ensure_ascii=False,indent=2),encoding='utf-8')
            raise ValueError('LAS и GLB расходятся: совместное использование отклонено. Проверь, что файлы из одного скана.')
    progress(35,'Объединяю цветные точки LAS')
    points,colors=fuse(points,colors,voxel=.01)
    write_glb(destination/'points.glb',points,colors);write_ply(destination/'points.ply',points,colors)
    metadata={'inputPoints':len(las.points),'outputPoints':len(points),'originLAS':origin.tolist(),
              'alignment':alignment,'accuracyVerified':False,'voxelMeters':.01}
    (destination/'las.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    return metadata
