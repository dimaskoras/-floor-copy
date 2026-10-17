"""Rectilinear interior model from observed ceiling levels, Polycam DXF and references.

This is an explicit geometric interpretation, not a metrological certification.
"""
import csv
import hashlib
import json
import math
import struct
from collections import defaultdict
from pathlib import Path
import numpy as np
from scipy.ndimage import gaussian_filter1d
from planar import ScanMesh,discover_planes,face_data


def dxf_polylines(path):
    lines=Path(path).read_text(encoding='utf-8',errors='replace').splitlines()
    pairs=[(int(lines[i].strip()),lines[i+1].strip()) for i in range(0,len(lines)-1,2)]
    active=False;current=None;result=[]
    def finish(item):
        if not item or item['type']!='LWPOLYLINE':return
        points=[];x=None
        for code,value in item['pairs']:
            if code==10:x=float(value)/1000
            elif code==20 and x is not None:points.append([x,float(value)/1000]);x=None
        if points:result.append({'layer':next((v for c,v in item['pairs'] if c==8),''),'points':points})
    for code,value in pairs:
        if code==2 and value=='ENTITIES':active=True;continue
        if active and code==0:
            finish(current)
            if value=='ENDSEC':break
            current={'type':value,'pairs':[]}
        elif active and current:current['pairs'].append((code,value))
    return result


def room_layout(dxf,csv_path):
    rows=list(csv.reader(Path(csv_path).read_text(encoding='utf-8-sig').splitlines()))
    shapes=dxf_polylines(dxf)
    floors=[np.asarray(s['points']) for s in shapes if s['layer'].endswith('-Floors')]
    if len(floors)!=1:raise ValueError('Для ровной модели нужен план одной прямоугольной аудитории')
    floor=floors[0];lo,hi=floor.min(axis=0),floor.max(axis=0)
    for a,b in zip(floor,np.roll(floor,-1,axis=0)):
        if min(abs(a[0]-b[0]),abs(a[1]-b[1]))>1e-4:raise ValueError('Косой план требует отдельной привязки')
    # RoomPlan floor follows wall centerlines. CSV records its assumed wall thickness.
    thickness=next((float(r[2])/1000 for r in rows if len(r)>=3 and r[1].startswith('Wall thickness')),None)
    if thickness is None or not .02<=thickness<=1:raise ValueError('В CSV не найдена толщина линии стен')
    lo+=thickness/2;hi-=thickness/2
    center=(lo+hi)/2;fronts=[]
    for s in shapes:
        if not s['layer'].endswith('-Walls'):continue
        q=np.asarray(s['points']);mn,mx=q.min(axis=0),q.max(axis=0)
        if .15<mx[0]-mn[0]<(hi[0]-lo[0])*.3 and mx[1]-mn[1]<.6 and mn[0]>center[0]:fronts.append(mn[0])
    if not fronts:raise ValueError('В плане не найден выступ у окон для контрольной ширины')
    openings=[]
    for s in shapes:
        kind='window' if s['layer'].endswith('-Openings-Windows') else 'door' if s['layer'].endswith('-Openings-Doors') else None
        if not kind or len(s['points'])<4:continue
        q=np.asarray(s['points']);mn,mx=q.min(axis=0),q.max(axis=0)
        if mx[1]-mn[1]<.3 or mx[0]-mn[0]>.5:continue
        widths=[]
        for r in rows:
            if len(r)>=3 and r[1]==('Window dimensions [mm]' if kind=='window' else 'Door dimensions [mm]'):
                w,h=map(float,r[2].split(' x '));widths.append((w/1000,h/1000))
        if not widths:raise ValueError('Нет высоты проёмов в CSV')
        w,h=min(widths,key=lambda wh:abs(wh[0]-(mx[1]-mn[1])))
        z=(mn[1]+mx[1])/2
        openings.append({'kind':kind,'side':'right' if q[:,0].mean()>center[0] else 'left','start':z-w/2,'end':z+w/2,'height':h})
    # Reject non-rectangular floor contours instead of silently enclosing an L-shaped room.
    mid=(floor.min(axis=0)+floor.max(axis=0))/2
    if any(abs(p[0]-floor[:,0].min())>1e-4 and abs(p[0]-floor[:,0].max())>1e-4 and abs(p[1]-floor[:,1].min())>1e-4 and abs(p[1]-floor[:,1].max())>1e-4 for p in floor):
        raise ValueError('Этот контур не является прямоугольной коробкой')
    return {'low':lo,'high':hi,'columnFront':min(fronts),'openings':openings,'wallThicknessAssumed':thickness}


def ceiling_bands(vertices,faces,planes,layout):
    horizontal=[p for p in planes if p['kind']=='horizontal' and p['areaM2']>3.5]
    at=lambda p:-p['constant']/p['normal'][1]
    floor=max((p for p in horizontal if at(p)<=np.quantile(vertices[:,1],.15)+.05),key=lambda p:p['areaM2'])
    fy=at(floor)
    upper=[p for p in horizontal if at(p)>fy+2.5]
    if not upper:raise ValueError('Не найден потолок высотой более 2,5 м')
    main=max(upper,key=lambda p:p['areaM2']);levels=[at(main)]
    for p in sorted(upper,key=lambda p:-p['areaM2']):
        h=at(p)
        if h<levels[0]-.12 and all(abs(h-v)>.13 for v in levels):levels.append(h)
        if len(levels)==4:break
    levels=sorted(levels,reverse=True)
    centers,normals,area=face_data(vertices,faces)
    mask=(abs(normals[:,1])>.85)&(centers[:,1]>fy+2.5)&(centers[:,1]<levels[0]+.25)
    c=centers[mask];weights=area[mask];step=.05
    low,high=layout['low'],layout['high']
    x=np.arange(low[0]-.15,high[0]+.151,step);z=np.arange(low[1]-.15,high[1]+.151,step)
    total=np.histogram2d(c[:,2],c[:,0],bins=(z,x),weights=weights)[0]
    classes=np.argmin(abs(c[:,1,None]-np.array(levels)[None,:]),axis=1)
    bands=[]
    for level in range(1,len(levels)):
        hit=np.histogram2d(c[classes==level,2],c[classes==level,0],bins=(z,x),weights=weights[classes==level])[0]
        for axis,edges in [(0,x),(1,z)]:
            den=total.sum(axis=axis);num=hit.sum(axis=axis)
            ratio=gaussian_filter1d(np.divide(num,den,out=np.zeros_like(num),where=den>0),1)
            ids=np.flatnonzero(ratio>.48)
            for group in np.split(ids,np.flatnonzero(np.diff(ids)>1)+1):
                if len(group)<2:continue
                a=max(float(edges[group[0]]),float(low[axis]));b=min(float(edges[group[-1]+1]),float(high[axis]))
                if b-a>=.075:bands.append({'axis':axis,'start':a,'end':b,'height':levels[level],'support':float(ratio[group].mean())})
    return float(fy),levels,bands


class Surfaces:
    def __init__(self):self.parts=defaultdict(list)
    def quad(self,name,points):
        points=np.asarray(points,dtype=float)
        if np.linalg.norm(np.cross(points[1]-points[0],points[2]-points[0]))<1e-10:return
        self.parts[name].append(points)
    def glb(self,path,scale,extras,baker=None,photo_surfaces=None):
        blob=bytearray();views=[];accessors=[];meshes=[];nodes=[];images=[];textures=[]
        materials=[{'name':'Светлая поверхность','doubleSided':True,'pbrMetallicRoughness':{'baseColorFactor':[.72,.75,.77,1],'metallicFactor':0,'roughnessFactor':1}},
                   {'name':'Пол','doubleSided':True,'pbrMetallicRoughness':{'baseColorFactor':[.36,.31,.25,1],'metallicFactor':0,'roughnessFactor':1}}]
        def add(a,component,kind,bounds=False):
            blob.extend(b'\0'*(-len(blob)%4));start=len(blob);blob.extend(a.tobytes())
            views.append({'buffer':0,'byteOffset':start,'byteLength':a.nbytes})
            item={'bufferView':len(views)-1,'componentType':component,'count':len(a),'type':kind}
            if bounds:item.update(min=a.min(axis=0).tolist(),max=a.max(axis=0).tolist())
            accessors.append(item);return len(accessors)-1
        for name,quads in list(self.parts.items())+list(photo_surfaces.parts.items() if photo_surfaces else []):
            v=np.concatenate(quads)*np.array(scale);n=[];f=[]
            for i,q in enumerate(v.reshape(-1,4,3)):
                norm=np.cross(q[1]-q[0],q[2]-q[0]);norm/=np.linalg.norm(norm);n.extend([norm]*4)
                j=i*4;f.extend([[j,j+1,j+2],[j,j+2,j+3]])
            prim={'attributes':{'POSITION':add(v.astype('<f4'),5126,'VEC3',True),'NORMAL':add(np.array(n,dtype='<f4'),5126,'VEC3')},'indices':add(np.array(f,dtype='<u4').ravel(),5125,'SCALAR'),'mode':4,'material':1 if name=='Пол' else 0}
            atlas=baker.atlas(quads,[92,79,64] if name=='Пол' else [184,191,196]) if baker else None
            if atlas:
                photo,uv=atlas;prim['attributes']['TEXCOORD_0']=add(uv,5126,'VEC2')
                blob.extend(b'\0'*(-len(blob)%4));start=len(blob);blob.extend(photo)
                views.append({'buffer':0,'byteOffset':start,'byteLength':len(photo)})
                images.append({'bufferView':len(views)-1,'mimeType':'image/jpeg'})
                textures.append({'source':len(images)-1,'sampler':0})
                prim['material']=len(materials)
                materials.append({'name':name+' · фотографии скана','doubleSided':True,'extensions':{'KHR_materials_unlit':{}},
                    'pbrMetallicRoughness':{'baseColorTexture':{'index':len(textures)-1},'metallicFactor':0,'roughnessFactor':1}})
            role='openingPhoto' if photo_surfaces and name in photo_surfaces.parts else 'ceiling' if 'Потолок' in name or 'балок' in name else 'surface'
            meshes.append({'name':name,'primitives':[prim]});nodes.append({'name':name,'mesh':len(meshes)-1,'extras':{'architectureRole':role,'measurementExcluded':role=='openingPhoto'}})
        doc={'asset':{'version':'2.0','generator':'Floor Copy architectural reconstruction'},'scene':0,'scenes':[{'nodes':list(range(len(nodes)))}],'nodes':nodes,'meshes':meshes,'materials':materials,'buffers':[{'byteLength':len(blob)}],'bufferViews':views,'accessors':accessors,'extras':extras}
        if images:doc.update(images=images,textures=textures,samplers=[{'wrapS':33071,'wrapT':33071,'magFilter':9729,'minFilter':9729}],extensionsUsed=['KHR_materials_unlit'])
        raw=json.dumps(doc,separators=(',',':'),ensure_ascii=False).encode();raw+=b' '*(-len(raw)%4);blob.extend(b'\0'*(-len(blob)%4))
        Path(path).write_bytes(struct.pack('<III',0x46546c67,2,28+len(raw)+len(blob))+struct.pack('<II',len(raw),0x4e4f534a)+raw+struct.pack('<II',len(blob),0x004e4942)+blob)
    def dxf(self,path,scale):
        # DXF uses Z-up and millimetres; GLB uses Y-up and metres.
        lines=['0','SECTION','2','HEADER','9','$ACADVER','1','AC1015','9','$INSUNITS','70','4','0','ENDSEC','0','SECTION','2','ENTITIES']
        for number,(name,quads) in enumerate(self.parts.items()):
            for q in quads:
                points=np.asarray(q)*np.asarray(scale)*1000
                lines+=['0','3DFACE','8',f'ARCH_{number:02d}']
                for i,v in enumerate(points):
                    for code,value in zip([10+i,20+i,30+i],[v[0],v[2],v[1]]):lines += [str(code),f'{value:.6f}']
        lines += ['0','ENDSEC','0','EOF'];Path(path).write_text('\n'.join(lines)+'\n',encoding='ascii')


def plan_svg(path,rect,column,report):
    xl,zl,xr,zr=rect;front,cmin,cmax=column;scale=60
    px=lambda x:100+(x-xl)*scale
    py=lambda z:90+(zr-z)*scale
    width=(xr-xl)*scale+240;height=(zr-zl)*scale+210
    outline=[(xl,zl),(xr,zl),(xr,cmin),(front,cmin),(front,cmax),(xr,cmax),(xr,zr),(xl,zr),(xl,zl)]
    points=' '.join(f'{px(x):.3f},{py(z):.3f}' for x,z in outline)
    text=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" viewBox="0 0 {width} {height}">',
          '<rect width="100%" height="100%" fill="#fff"/>',
          '<style>text{font-family:Arial,sans-serif;fill:#24383f;font-size:15px}.dim{stroke:#087e82;stroke-width:1.3;fill:none}</style>',
          '<text x="50" y="28" style="font-size:21px">Аудитория · ровная модель по скану</text>',
          f'<polyline points="{points}" fill="#f3f2ed" stroke="#303e43" stroke-width="5"/>']
    for opening in report['openings']:
        xx=px(xl if opening['side']=='left' else xr);a=py(opening['start']*report['scaleXYZ'][2]);b=py(opening['end']*report['scaleXYZ'][2])
        color='#668faa' if opening['kind']=='window' else '#b47b48'
        text.append(f'<path d="M{xx} {a}V{b}" stroke="#fff" stroke-width="10"/>')
        text.append(f'<path d="M{xx} {a}V{b}" stroke="{color}" stroke-width="3"><title>Проём по плану Polycam, требует обмера</title></path>')
    yy=py((cmin+cmax)/2)
    text+=[f'<path class="dim" d="M{px(xl)} {yy}H{px(front)}"/>',
           f'<text x="{px(xl)+30}" y="{yy-12}">{report["constraints"]["columnGapMeters"]*1000:.0f} мм · лазерный размер</text>',
           f'<path class="dim" d="M{px(xl)-35} {py(zl)}V{py(zr)}"/>',
           f'<text x="{px(xl)-48}" y="{(py(zl)+py(zr))/2}" transform="rotate(-90 {px(xl)-48} {(py(zl)+py(zr))/2})">{report["constraints"]["lengthMeters"]*1000:.0f} мм · лазерный размер</text>',
           f'<text x="100" y="{height-75}">Полная ширина ≈ {report["fullWidthEstimatedMeters"]:.3f} м · оценка по плану</text>',
           f'<text x="100" y="{height-50}">Высоты, проёмы и балки требуют контрольных обмеров.</text>',
           f'<text x="100" y="{height-25}">Эскиз модели. Не является проверенным рабочим чертежом.</text>','</svg>']
    Path(path).write_text('\n'.join(text),encoding='utf-8')


def build(source,dxf,csv_path,destination,length_m,column_gap_m,height_m=None):
    length_m=float(length_m);column_gap_m=float(column_gap_m)
    if not all(math.isfinite(v) and 1<v<100 for v in [length_m,column_gap_m]):raise ValueError('Контрольные размеры нужны в метрах, от 1 до 100')
    plan_hash=hashlib.sha256(Path(dxf).read_bytes()+Path(csv_path).read_bytes()).hexdigest()
    layout=room_layout(dxf,csv_path);mesh=ScanMesh(source);destination=Path(destination)
    cache=destination/'architectural-source-planes.json';digest=hashlib.sha256(Path(source).read_bytes()).hexdigest()
    prior=json.loads(cache.read_text()) if cache.exists() else {}
    if prior.get('sourceHash')==digest:planes=prior['planes'];backend=prior['backend']
    else:
        planes,_,backend=discover_planes(mesh.vertices,mesh.faces,threshold=.035,max_planes=40,minimum_area=.2)
        cache.write_text(json.dumps({'sourceHash':digest,'planes':planes,'backend':backend}),encoding='utf-8')
    fy,levels,bands=ceiling_bands(mesh.vertices,mesh.faces,planes,layout)
    lo,hi=layout['low'],layout['high'];xl,zl=map(float,lo);xr,zr=map(float,hi);front=float(layout['columnFront'])
    sx=column_gap_m/(front-xl);sz=length_m/(zr-zl);sy=1.
    if height_m is not None:
        height_m=float(height_m)
        if not math.isfinite(height_m) or not 2<height_m<10:raise ValueError('Проверь высоту в метрах')
        sy=height_m/(levels[0]-fy)
    if not .8<sx<1.2 or not .8<sz<1.2:raise ValueError('Контрольные размеры слишком отличаются от плана. Проверь точки и метры')
    def roof(x,z):return min([levels[0]]+[b['height'] for b in bands if b['start']-1e-8<=(x if b['axis']==0 else z)<=b['end']+1e-8])
    xs=sorted({xl,xr,*[v for b in bands if b['axis']==0 for v in [b['start'],b['end']]]})
    zs=sorted({zl,zr,*[v for b in bands if b['axis']==1 for v in [b['start'],b['end']]]})
    surfaces=Surfaces()
    for i,(a,b) in enumerate(zip(xs,xs[1:])):
        for j,(c,d) in enumerate(zip(zs,zs[1:])):
            h=roof((a+b)/2,(c+d)/2);surfaces.quad('Потолок и низ балок',[[a,h,c],[b,h,c],[b,h,d],[a,h,d]])
            if i+1<len(xs)-1:
                other=roof((b+xs[i+2])/2,(c+d)/2)
                if abs(other-h)>.001:surfaces.quad('Вертикальные грани балок',[[b,h,c],[b,other,c],[b,other,d],[b,h,d]])
            if j+1<len(zs)-1:
                other=roof((a+b)/2,(d+zs[j+2])/2)
                if abs(other-h)>.001:surfaces.quad('Вертикальные грани балок',[[a,h,d],[a,other,d],[b,other,d],[b,h,d]])
    # Two side faces of the window pier are identified from observed tall planes near room center.
    center_z=(zl+zr)/2;column_sides=[]
    for p in planes:
        if p['kind']=='vertical' and abs(p['normal'][2])>.95 and p['bounds'][1][1]-p['bounds'][0][1]>1.7:
            z=-p['constant']/p['normal'][2]
            if abs(z-center_z)<.65:column_sides.append(z)
    if len(column_sides)>=2:cmin,cmax=min(column_sides),max(column_sides)
    else:
        red=[b for b in bands if b['axis']==1 and b['start']<center_z<b['end']]
        if not red:raise ValueError('Не удалось выделить ширину выступа в скане')
        cmin,cmax=red[0]['start'],red[0]['end']
    for a,b,c,d in [(xl,front,zl,zr),(front,xr,zl,cmin),(front,xr,cmax,zr)]:surfaces.quad('Пол',[[a,fy,c],[b,fy,c],[b,fy,d],[a,fy,d]])
    column_top=roof((front+xr)/2,(cmin+cmax)/2)
    surfaces.quad('Выступ у окон',[[front,fy,cmin],[front,column_top,cmin],[front,column_top,cmax],[front,fy,cmax]])
    for z in [cmin,cmax]:surfaces.quad('Боковые грани выступа',[[front,fy,z],[xr,fy,z],[xr,column_top,z],[front,column_top,z]])
    openings=layout['openings']
    window_top=min(levels)-.04
    for opening in openings:
        opening['bottom']=fy if opening['kind']=='door' else window_top-opening['height']
        opening['top']=opening['bottom']+opening['height']
        if opening['side']=='right':
            if (opening['start']+opening['end'])/2<cmin:opening['end']=min(opening['end'],cmin)
            else:opening['start']=max(opening['start'],cmax)
    wall_planes=[]
    for side,axis,value,start,end in [('left',0,xl,zl,zr),('right',0,xr,zl,zr),('near',2,zl,xl,xr),('far',2,zr,xl,xr)]:
        holes=[o for o in openings if o['side']==side];cuts=sorted({start,end,*([v for b in bands if b['axis']==(1 if axis==0 else 0) for v in [b['start'],b['end']]]),*[max(start,min(end,v)) for o in holes for v in [o['start'],o['end']]]})
        name={'left':'Стена с дверями','right':'Стена у окон','near':'Торцевая стена 1','far':'Торцевая стена 2'}[side]
        for a,b in zip(cuts,cuts[1:]):
            if b-a<1e-7:continue
            x,z=(value,(a+b)/2) if axis==0 else ((a+b)/2,value)
            top=roof(x,z);ys=sorted({fy,top,*[max(fy,min(top,v)) for o in holes for v in [o['bottom'],o['top']]]})
            for low,high in zip(ys,ys[1:]):
                if high-low<1e-7 or any(o['start']<(a+b)/2<o['end'] and o['bottom']<(low+high)/2<o['top'] for o in holes):continue
                q=[[value,low,a],[value,high,a],[value,high,b],[value,low,b]] if axis==0 else [[a,low,value],[a,high,value],[b,high,value],[b,low,value]]
                surfaces.quad(name,q)
        n=[0.,0.,0.];n[axis]=1;scaled=value*(sx if axis==0 else sz)
        bounds=[[xl*sx,fy*sy,zl*sz],[xr*sx,levels[0]*sy,zr*sz]];bounds[0][axis]=bounds[1][axis]=scaled
        wall_planes.append({'id':1000+len(wall_planes),'name':name,'kind':'vertical','p95ResidualMm':0.,'normal':n,'constant':-scaled,'areaM2':(end-start)*(levels[0]-fy),'bounds':bounds,'segmentXZ':[[value*sx,start*sz],[value*sx,end*sz]] if axis==0 else [[start*sx,value*sz],[end*sx,value*sz]]})
    for axis,value,a,b,name in [(0,front,cmin,cmax,'Выступ · передняя грань'),(2,cmin,front,xr,'Выступ · боковая грань 1'),(2,cmax,front,xr,'Выступ · боковая грань 2')]:
        n=[0.,0.,0.];n[axis]=1;scaled=value*(sx if axis==0 else sz)
        bounds=[[front*sx,fy*sy,cmin*sz],[xr*sx,column_top*sy,cmax*sz]];bounds[0][axis]=bounds[1][axis]=scaled
        segment=[[value*sx,a*sz],[value*sx,b*sz]] if axis==0 else [[a*sx,value*sz],[b*sx,value*sz]]
        wall_planes.append({'id':1000+len(wall_planes),'name':name,'kind':'vertical','p95ResidualMm':0.,'normal':n,'constant':-scaled,'areaM2':(b-a)*(column_top-fy)*sy*(sz if axis==0 else sx),'bounds':bounds,'segmentXZ':segment})
    report={'method':'rectilinear surface reconstruction','sourceHash':digest,'sourcePlanHash':plan_hash,'backend':backend,'planes':wall_planes,
        'revision':hashlib.sha256((digest+plan_hash+repr((length_m,column_gap_m,height_m))).encode()).hexdigest()[:16],
        'constraints':{'lengthMeters':length_m,'columnGapMeters':column_gap_m,'heightMeters':height_m},
        'scaleXYZ':[sx,sy,sz],'fullWidthEstimatedMeters':(xr-xl)*sx,'ceilingHeightEstimatedMeters':(levels[0]-fy)*sy,
        'columnDepthEstimatedMeters':(xr-front)*sx,'columnWidthEstimatedMeters':(cmax-cmin)*sz,'floorAreaEstimatedM2':((xr-xl)*(zr-zl)-(xr-front)*(cmax-cmin))*sx*sz,
        'floorY':fy*sy,'ceilingLevelsWorldY':[v*sy for v in levels],'bands':bands,'gridResolutionMeters':.05,
        'openings':openings,'components':{k:len(v) for k,v in surfaces.parts.items()},'accuracyVerified':False,
        'warnings':['Два заданных лазерных размера являются ограничениями модели, а не независимой проверкой точности.',
                    'Высоты, проёмы, глубина выступа и границы балок оценены по скану и автоматическому плану Polycam.',
                    'Плоские поверхности продолжены за мебелью. Это геометрическая интерпретация; отделка и мебель не реконструируются.',
                    'Прямые углы заданы по подтверждённому пользователем прямоугольному помещению. Локальные размеры требуют проверки.']}
    from photo_bake import PhotoBaker
    from raw_dimensions import dimensions_from_planes
    baker=PhotoBaker(mesh)
    photos=Surfaces()
    for o in openings if baker.images else []:
        x=xl if o['side']=='left' else xr
        photos.quad('Фото окон и дверей',[[x,o['bottom'],o['start']],[x,o['top'],o['start']],[x,o['top'],o['end']],[x,o['bottom'],o['end']]])
    surfaces.glb(destination/'architectural.glb',[sx,sy,sz],{'floorCopy':{'architecture':True,'accuracyVerified':False,'constraints':report['constraints']}},baker,photos)
    report['openingPhotoPanels']=sum(len(v) for v in photos.parts.values())
    report['rawScanDimensions']=dimensions_from_planes(planes)
    report['warnings'].append('Фото окон и дверей — визуальные вставки по скану, без достоверной толщины рам. Они исключены из чертежа и выбора точек измерений.')
    report['photoTexture']=baker.report()
    if baker.images:report['warnings'].append('Фотографии перенесены только с близких параллельных участков скана. Ненаблюдаемые области однотонные; перенос фото не повышает точность размеров.')
    surfaces.dxf(destination/'architectural.dxf',[sx,sy,sz])
    plan_svg(destination/'architectural-plan.svg',[xl*sx,zl*sz,xr*sx,zr*sz],[front*sx,cmin*sz,cmax*sz],report)
    with (destination/'architectural-dimensions.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream,delimiter=';');writer.writerow(['Размер','Метры','Источник','Независимая точность подтверждена'])
        writer.writerow(['Длина между торцами',length_m,'Лазерное ограничение пользователя','Нет'])
        writer.writerow(['От выступа до стены с дверями',column_gap_m,'Лазерное ограничение пользователя','Нет'])
        for label,key in [('Полная ширина','fullWidthEstimatedMeters'),('Высота основного потолка','ceilingHeightEstimatedMeters'),('Глубина выступа','columnDepthEstimatedMeters'),('Ширина выступа','columnWidthEstimatedMeters')]:
            writer.writerow([label,report[key],'Оценка по скану и плану' if not (key=='ceilingHeightEstimatedMeters' and height_m) else 'Лазерное ограничение пользователя','Нет'])
    (destination/'architectural.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report
