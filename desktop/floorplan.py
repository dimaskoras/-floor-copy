"""Observed wall sections and metric drawing. Unknown gaps remain unknown."""
import csv
import html
import json
import math
from pathlib import Path
import numpy as np
from planar import ScanMesh, discover_planes, face_data


def merge_intervals(intervals, tolerance=.06):
    result=[]
    for a,b in sorted(intervals):
        if b-a<.002:continue
        if result and a<=result[-1][1]+tolerance:result[-1][1]=max(b,result[-1][1])
        else:result.append([float(a),float(b)])
    return [v for v in result if v[1]-v[0]>=.08]


def section(vertices,faces,planes,height):
    centers,normals,areas=face_data(vertices,faces)
    walls=[]
    for plane in sorted(planes,key=lambda p:-p['areaM2']):
        if plane['kind']!='vertical' or plane['areaM2']<.7 or plane['bounds'][1][1]-plane['bounds'][0][1]<1.2:continue
        n=np.array(plane['normal']);horizontal=n[[0,2]];norm=np.linalg.norm(horizontal)
        if norm<.9:continue
        normal=horizontal/norm;constant=(plane['constant']+n[1]*height)/norm
        # Duplicate fragments are merged into the same architectural wall.
        if any(abs(normal@np.array(w['normal']))>.995 and abs(constant-(1 if normal@np.array(w['normal'])>0 else -1)*w['constant'])<.08 for w in walls):continue
        tangent=np.array([-normal[1],normal[0]]);anchor=-constant*normal
        mask=(areas>1e-8)&(np.abs(centers@n+plane['constant'])<.065)&(np.abs(normals@n)>.8)
        triangles=vertices[faces[mask]];intervals=[]
        for tri in triangles:
            intersections=[]
            for i,j in [(0,1),(1,2),(2,0)]:
                a,b=tri[i],tri[j];da=a[1]-height;db=b[1]-height
                if da*db<=0 and abs(a[1]-b[1])>1e-10:
                    q=a+(b-a)*(-da)/(db-da);intersections.append(float((q[[0,2]]-anchor)@tangent))
            if len(intersections)>=2:intervals.append([min(intersections),max(intersections)])
        spans=merge_intervals(intervals)
        if not spans:continue
        gaps=[]
        for a,b in zip(spans,spans[1:]):
            width=b[0]-a[1]
            if .35<=width<=2.5:gaps.append({'start':a[1],'end':b[0],'widthRaw':width,'type':'unknown','verified':False})
        walls.append({'id':len(walls)+1,'planeId':plane['id'],'normal':normal.tolist(),'constant':float(constant),
                      'anchor':anchor.tolist(),'tangent':tangent.tolist(),'spans':spans,'gaps':gaps,
                      'observedLengthRaw':sum(b-a for a,b in spans),'residualP95Mm':plane['p95ResidualMm']})
    return walls


def wall_point(w,t):return np.array(w['anchor'])+np.array(w['tangent'])*t


def build(source,folder,factor=1,section_meters=1.1,title='План по скану',scale=100):
    factor=float(factor);section_meters=float(section_meters);scale=int(scale)
    if not math.isfinite(factor) or not .1<factor<10 or not .1<=section_meters<=3 or scale not in (20,50,100,200):raise ValueError('Проверь масштаб, высоту сечения и масштаб листа')
    folder=Path(folder);mesh=ScanMesh(source,exclude_roles=('openingPhoto',))
    plane_file=Path(source).parent/('architectural.json' if Path(source).name=='architectural.glb' else 'planes.json')
    plane_document=json.loads(plane_file.read_text(encoding='utf-8')) if plane_file.exists() else {'planes':discover_planes(mesh.vertices,mesh.faces)[0]}
    planes=plane_document['planes'];is_model=Path(source).name=='architectural.glb'
    horizontal=[p for p in planes if p['kind']=='horizontal' and p['areaM2']>1]
    floor=min(horizontal,key=lambda p:sum(v[1] for v in p['bounds'])/2) if horizontal else None
    floor_y=plane_document['floorY'] if is_model else -floor['constant']/floor['normal'][1] if floor else float(np.quantile(mesh.vertices[:,1],.02))
    height=floor_y+section_meters/factor
    walls=section(mesh.vertices,mesh.faces,planes,height)
    if not walls:raise ValueError('На выбранной высоте не найдено стен. Измени высоту сечения или досними стены.')
    widths=[]
    for i,a in enumerate(walls):
        for b in walls[i+1:]:
            dot=np.array(a['normal'])@np.array(b['normal'])
            if abs(dot)<.995:continue
            raw=abs(a['constant']-(1 if dot>0 else -1)*b['constant'])
            if .5<raw<20:widths.append({'walls':[a['id'],b['id']],'rawMeters':raw,'meters':raw*factor,'supportLength':min(a['observedLengthRaw'],b['observedLengthRaw'])})
    widths.sort(key=lambda w:-w['supportLength'])
    report={'scanSource':Path(source).name,'method':'architectural plane sections; observed coverage only',
            'factor':factor,'sectionMeters':section_meters,'sheetScale':scale,'walls':walls,'parallelDistances':widths,
            'observedFloorAreaM2':plane_document.get('floorAreaEstimatedM2') if is_model else floor['areaM2']*factor**2 if floor else None,
            'areaSource':'geometric_model' if is_model else 'observed',
            'accuracyVerified':False,'gostCompliant':False,'title':str(title)[:100],
            'warnings':['Чертёж наблюдаемого участка; концы скана не замыкаются в комнату.',
                        'Разрывы могут быть проёмами, мебелью или пропусками съёмки. Тип и высота не определены.',
                        'Толщина стен, направление открывания дверей и невидимые участки не восстановлены.',
                        'Для рабочего чертежа и закупки материалов нужны контрольные обмеры и проверка оформления СПДС.']}
    drawing=[];dxf=['0','SECTION','2','HEADER','9','$INSUNITS','70','4','0','ENDSEC','0','SECTION','2','ENTITIES']
    def line_dxf(layer,a,b):dxf.extend(['0','LINE','8',layer,'10',str(a[0]*1000*factor),'20',str(-a[1]*1000*factor),'30','0','11',str(b[0]*1000*factor),'21',str(-b[1]*1000*factor),'31','0'])
    all_points=[wall_point(w,t) for w in walls for span in w['spans'] for t in span]
    bounds=np.array(all_points);lo=bounds.min(axis=0);hi=bounds.max(axis=0);mm=1000*factor/scale
    size=(hi-lo)*mm
    if size[0]>340 or size[1]>205:raise ValueError('Участок не помещается на A3. Выбери меньший масштаб листа, например 1:200.')
    offset=np.array([35,40])+(np.array([340,205])-size)/2
    def xy(p):return (np.array(p)-lo)*mm+offset
    def line(a,b,style):
        a=xy(a);b=xy(b);drawing.append(f'<line x1="{a[0]:.4f}" y1="{a[1]:.4f}" x2="{b[0]:.4f}" y2="{b[1]:.4f}" {style}/>')
    def dim(a,b,label,offset_m=.25):
        v=np.array(b)-a;length=np.linalg.norm(v)
        if length<.08:return
        normal=np.array([-v[1],v[0]])/length;u=np.array(a)+normal*offset_m;v=np.array(b)+normal*offset_m
        for p,q in [(a,u),(b,v),(u,v)]:line(p,q,'stroke="#555" stroke-width=".18"')
        for p in [u,v]:line(p-normal*.04-(np.array(b)-a)/length*.04,p+normal*.04+(np.array(b)-a)/length*.04,'stroke="#555" stroke-width=".25"')
        center=xy((u+v)/2);angle=math.degrees(math.atan2(b[1]-a[1],b[0]-a[0]));angle=(angle+90)%180-90
        drawing.append(f'<text x="{center[0]:.3f}" y="{center[1]-1:.3f}" text-anchor="middle" font-size="3" transform="rotate({angle:.3f} {center[0]:.3f} {center[1]:.3f})">{html.escape(label)}</text>')
        for p,q in [(a,u),(b,v),(u,v)]:line_dxf('DIMENSION_LINES',p,q)
        middle=(u+v)/2;dxf.extend(['0','TEXT','8','DIMENSION_VALUES','10',str(middle[0]*1000*factor),'20',str(-middle[1]*1000*factor),'30','0','40',str(3*scale),'1',str(round(length*factor*1000)),'50',str(-angle)])
    rows=[]
    for w in walls:
        w['observedLengthMeters']=w['observedLengthRaw']*factor
        for start,end in w['spans']:
            a,b=wall_point(w,start),wall_point(w,end);line(a,b,'stroke="#1a2630" stroke-width=".8"');line_dxf('OBSERVED_WALLS',a,b)
            dim(a,b,f'{(end-start)*factor:.3f} м');rows.append([f'Стена {w["id"]}',(end-start)*factor,'m','наблюдаемый фрагмент'])
        for j,gap in enumerate(w['gaps']):
            gap['widthMeters']=gap['widthRaw']*factor
            a,b=wall_point(w,gap['start']),wall_point(w,gap['end']);line(a,b,'stroke="#bd731b" stroke-width=".5" stroke-dasharray="2 1"');line_dxf('UNKNOWN_GAPS',a,b)
            dim(a,b,f'? {gap["widthMeters"]:.3f} м',-.25);rows.append([f'Разрыв {w["id"]}.{j+1}',gap['widthMeters'],'m','проём или пропуск; проверить'])
    for width in widths[:1]:
        a,b=[next(w for w in walls if w['id']==i) for i in width['walls']]
        mid=(a['spans'][0][0]+a['spans'][-1][1])/2;p=wall_point(a,mid);n=np.array(b['normal']);q=p-n*(n@p+b['constant']);dim(p,q,f'{width["meters"]:.3f} м',0)
    if is_model:report['warnings'][0]='Сечение геометрической модели. Скрытые поверхности продолжены по плоскостям; контрольные размеры заданы как ограничения.'
    area=report['observedFloorAreaM2'];area_label=f'Площадь пола модели: {area:.2f} м²' if is_model and area is not None else f'Наблюдаемая площадь пола: {area:.2f} м²' if area is not None else 'Площадь пола не определена'
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297"><rect width="420" height="297" fill="white"/><g font-family="Arial" fill="#1a2630"><rect x="20" y="5" width="395" height="287" fill="none" stroke="#333" stroke-width=".35"/><text x="30" y="17" font-size="5">{html.escape(report["title"])}</text><text x="30" y="25" font-size="3.5">Сечение {section_meters:.2f} м · 1:{scale} · коэффициент {factor:.6f}</text>{"".join(drawing)}<text x="30" y="258" font-size="3.5">{area_label}</text><text x="30" y="267" font-size="3" fill="#994b13">ЧЕРНОВИК ОБМЕРА. Точность не подтверждена. Разрывы (?) проверить на месте.</text><text x="30" y="275" font-size="3">Печать SVG: A3, 100%, без подгонки. Размерные числа — в метрах.</text><text x="30" y="284" font-size="3">Не является проверенным рабочим чертежом СПДС. Невидимые стены и двери не достроены.</text></g></svg>'
    if is_model:svg=svg.replace('Не является проверенным рабочим чертежом СПДС. Невидимые стены и двери не достроены.','Эскиз по геометрической модели. Высоты и проёмы требуют контрольных обмеров.')
    (folder/'floorplan.svg').write_text(svg,encoding='utf-8')
    dxf.extend(['0','ENDSEC','0','EOF']);(folder/'floorplan.dxf').write_text('\n'.join(dxf)+'\n',encoding='ascii')
    with (folder/'floorplan.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f,delimiter=';');writer.writerow(['Элемент','Размер','Единицы','Статус']);writer.writerows(rows)
    (folder/'floorplan.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report
