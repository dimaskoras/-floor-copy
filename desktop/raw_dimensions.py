"""Uncalibrated distances between observed scan planes, in source GLB metres."""
import numpy as np


def dimensions_from_planes(planes):
    result=[];sides={}
    for axis in [0,2]:
        candidates=[p for p in planes if p['kind']=='vertical' and abs(p['normal'][axis])>.95 and p['areaM2']>3]
        negative=[p for p in candidates if -p['constant']/p['normal'][axis]<0]
        positive=[p for p in candidates if -p['constant']/p['normal'][axis]>0]
        if negative and positive:sides[axis]=(max(negative,key=lambda p:p['areaM2']),max(positive,key=lambda p:p['areaM2']))
    horizontal=[p for p in planes if p['kind']=='horizontal' and p['areaM2']>3]
    low=[p for p in horizontal if -p['constant']/p['normal'][1]<=.15]
    high=[p for p in horizontal if -p['constant']/p['normal'][1]>1]
    if not low or not high:return {'source':'uncalibrated scan planes','factor':1,'accuracyVerified':False,'items':[]}
    floor=max(low,key=lambda p:p['areaM2']);roof=max(high,key=lambda p:p['areaM2'])
    fy=-floor['constant']/floor['normal'][1]
    def coordinate(p,axis,point):
        n=np.array(p['normal']);return float((-p['constant']-sum(n[k]*point[k] for k in range(3) if k!=axis))/n[axis])
    def add(name,axis,pair,point):
        a=np.array(point,dtype=float);b=a.copy();a[axis]=coordinate(pair[0],axis,a);b[axis]=coordinate(pair[1],axis,b)
        result.append({'name':name,'points':[a.tolist(),b.tolist()],'meters':float(np.linalg.norm(b-a)),'planeIds':[p['id'] for p in pair]})
    for axis,name in [(0,'Между боковыми стенами'),(2,'Между торцевыми стенами')]:
        if axis in sides:
            point=[0,fy+.12,0];other=2 if axis==0 else 0
            if other in sides:point[other]=-sides[other][0]['constant']/sides[other][0]['normal'][other]+.65
            add(name,axis,sides[axis],point)
    point=[0,0,0]
    for axis in sides:point[axis]=-sides[axis][0]['constant']/sides[axis][0]['normal'][axis]+.45
    add('Пол — основной потолок',1,(floor,roof),point)
    return {'source':'uncalibrated scan planes','factor':1,'accuracyVerified':False,'items':result,
            'note':'Расстояния вдоль осей исходного GLB между аппроксимациями наблюдаемых плоскостей. Лазерные ограничения не применены.'}
