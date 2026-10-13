"""Uniform metric scale from a measured reference; never certifies local accuracy."""
import json
import math
import struct
from pathlib import Path


def reference(points, real, name='Контрольный размер'):
    if not isinstance(points,list) or len(points)!=2 or any(not isinstance(p,list) or len(p)!=3 or not all(math.isfinite(float(v)) for v in p) for p in points):raise ValueError('Выбери две точки на 3D-скане')
    raw=math.dist(points[0],points[1]);real=float(real)
    if raw<.05 or not math.isfinite(real) or not .01<real<1000:raise ValueError('Проверь точки и реальный размер в метрах')
    factor=real/raw
    if not .1<factor<10:raise ValueError('Масштаб отличается более чем в 10 раз. Проверь единицы и выбранные точки')
    return {'points':points,'rawMeters':raw,'realMeters':real,'name':str(name)[:100],'factor':factor}


def scale_glb(source,destination,factor):
    raw=Path(source).read_bytes()
    if len(raw)<20 or struct.unpack_from('<III',raw)!=(0x46546c67,2,len(raw)):raise ValueError('Некорректный GLB')
    length,kind=struct.unpack_from('<II',raw,12)
    if kind!=0x4e4f534a:raise ValueError('GLB без JSON')
    document=json.loads(raw[20:20+length]);nodes=document.setdefault('nodes',[])
    for scene in document.get('scenes',[]):
        wrapper=len(nodes);nodes.append({'name':'Metric calibration','scale':[factor]*3,'children':scene.get('nodes',[])})
        scene['nodes']=[wrapper]
    document.setdefault('extras',{})['metricCalibration']={'factor':factor,'accuracyVerified':False}
    payload=json.dumps(document,separators=(',',':')).encode();payload+=b' '*(-len(payload)%4)
    tail=raw[20+length:];result=struct.pack('<III',0x46546c67,2,20+len(payload)+len(tail))+struct.pack('<II',len(payload),kind)+payload+tail
    Path(destination).write_bytes(result)
