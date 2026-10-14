"""Optional planar projection of observed architecture; no invented dimensions."""
import json
from pathlib import Path
import numpy as np
from planar import ScanMesh,discover_planes,face_data


def project_architecture(vertices,faces,planes,labels,maximum=.1):
    _,inverse,counts=np.unique(np.round(vertices,6),axis=0,return_inverse=True,return_counts=True)
    welded=np.zeros((len(counts),3));np.add.at(welded,inverse,vertices);welded/=counts[:,None]
    f=inverse[faces];centers,_,areas=face_data(vertices,faces)
    horizontal=[p for p in planes if p['kind']=='horizontal' and p['areaM2']>=4]
    largest=max([p['areaM2'] for p in horizontal],default=0)
    heights=[-p['constant']/p['normal'][1] for p in horizontal if p['areaM2']>=largest*.15]
    extremes=[min(heights),max(heights)] if heights else []
    accepted=[]
    for source in planes:
        p=dict(source);kind=p['kind']
        if kind=='vertical':
            if p['areaM2']<2.5 or p['bounds'][1][1]-p['bounds'][0][1]<1.7:continue
            n=np.array(p['normal'],dtype=float);n[1]=0;n/=np.linalg.norm(n)
        elif kind=='horizontal':
            height=-p['constant']/p['normal'][1]
            if not extremes or p['areaM2']<max(4,largest*.15) or min(abs(height-h) for h in extremes)>.25:continue
            n=np.array([0.,1.,0.])
        else:continue
        support=labels==p['id']
        if not support.any():continue
        anchor=np.average(centers[support],axis=0,weights=areas[support])
        p.update(normal=n.tolist(),constant=float(-n@anchor));accepted.append(p)
    use=np.isin(labels,[p['id'] for p in accepted])
    incidence=np.bincount(f.ravel(),minlength=len(welded))
    votes=np.bincount(f[use].ravel(),minlength=len(welded))
    trusted=(votes>0)&(votes>=incidence*.67)
    lhs=np.zeros((len(welded),3,3));rhs=np.zeros_like(welded)
    for p in accepted:
        ids=np.unique(f[labels==p['id']]);ids=ids[trusted[ids]];n=np.array(p['normal'])
        lhs[ids]+=np.outer(n,n);rhs[ids]-=(welded[ids]@n+p['constant'])[:,None]*n
    active=np.linalg.norm(lhs,axis=(1,2))>0;delta=np.zeros_like(welded)
    delta[active]=(np.linalg.pinv(lhs[active],rcond=1e-6)@rhs[active,:,None])[:,:,0]
    excessive=np.linalg.norm(delta,axis=1)>maximum;delta[excessive]=0
    _,old_normals,old_area=face_data(vertices,faces);rejected=np.zeros(len(faces),bool)
    # Reject folds rather than introduce the triangles seen in an earlier version.
    for _ in range(64):
        result=vertices+delta[inverse];_,normals,area=face_data(result,faces)
        unsafe=(old_area>1e-10)&((np.einsum('ij,ij->i',old_normals,normals)<=0)|(area<old_area*.05)|(area>old_area*10))
        if not unsafe.any():break
        ids=np.unique(f[unsafe]);rejected|=unsafe
        if not np.any(delta[ids]):break
        delta[ids]=0
    else:result=vertices.copy();delta[:]=0
    result=vertices+delta[inverse]
    shift=np.linalg.norm(result-vertices,axis=1)
    bounds_before=np.array([vertices.min(axis=0),vertices.max(axis=0)])
    bounds_after=np.array([result.min(axis=0),result.max(axis=0)])
    for p in accepted:
        ids=np.unique(faces[labels==p['id']]);n=np.array(p['normal'])
        p['beforeP95Mm']=float(np.quantile(np.abs(vertices[ids]@n+p['constant']),.95)*1000)
        p['afterP95Mm']=float(np.quantile(np.abs(result[ids]@n+p['constant']),.95)*1000)
    return result,accepted,{'movedVertices':int((shift>1e-6).sum()),'maximumShiftMm':float(shift.max()*1000),
        'rejectedExcessiveVertices':int(excessive.sum()),'rejectedFoldFaces':int(rejected.sum()),
        'processedPlanes':len(accepted),'extentBeforeMeters':(bounds_before[1]-bounds_before[0]).tolist(),
        'extentAfterMeters':(bounds_after[1]-bounds_after[0]).tolist(),
        'extentChangeMm':(((bounds_after[1]-bounds_after[0])-(bounds_before[1]-bounds_before[0]))*1000).tolist()}


def analyze_forced(source,destination):
    destination=Path(destination);mesh=ScanMesh(source)
    planes,labels,backend=discover_planes(mesh.vertices,mesh.faces,threshold=.08,max_planes=24)
    result,accepted,changes=project_architecture(mesh.vertices,mesh.faces,planes,labels)
    mesh.save(destination/'forced.glb',result)
    report={'method':'architectural plane projection','backend':backend,'planes':accepted,'changes':changes,
        'maximumAllowedShiftMeters':.1,'accuracyVerified':False,
        'warnings':['Выравниваются только распознанные архитектурные поверхности; пропуски не достраиваются.',
                    'Правка меняет геометрию и может менять размеры. Реальные размеры требуют контрольных обмеров.',
                    'Углы 90 градусов не навязываются. Участки с риском переворота треугольников оставлены исходными.']}
    (destination/'forced-planes.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report
