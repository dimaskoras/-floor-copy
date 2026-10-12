import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from project_store import atomic_json

BASE='https://mpunav.ru/cdn/plans/'


def catalog(data):
    folder=Path(data)/'mpunav';folder.mkdir(exist_ok=True);path=folder/'manifest.json'
    if path.exists():document=json.loads(path.read_text(encoding='utf-8'))
    else:
        with urllib.request.urlopen(BASE+'manifest.json',timeout=25) as response:document=json.load(response)
        atomic_json(path,document)
    return [{'name':n,'size':v['size'],'version':document.get('version')} for n,v in document['plans'].items() if re.fullmatch(r'[A-Za-z0-9_-]+\.svg',n)]


def fetch_map(name,data,destination):
    if name not in {p['name'] for p in catalog(data)}:raise ValueError('Карты нет в каталоге MPUNAV')
    with urllib.request.urlopen(BASE+name,timeout=25) as response:raw=response.read(5*1024**2)
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('Неподдерживаемый SVG')
    root=ET.fromstring(raw)
    if root.tag.split('}')[-1]!='svg':raise ValueError('Ответ не является SVG')
    for parent in root.iter():
        for child in list(parent):
            if child.tag.split('}')[-1] in {'script','foreignObject','iframe','image'}:parent.remove(child)
        for key in list(parent.attrib):
            if key.lower().startswith('on') or (key.split('}')[-1]=='href' and not parent.attrib[key].startswith('#')):del parent.attrib[key]
    view=root.get('viewBox')
    if view:bounds=[float(v) for v in re.split(r'[\s,]+',view.strip())]
    else:bounds=[0,0,float(root.get('width','1000').removesuffix('px')),float(root.get('height','1000').removesuffix('px'))]
    ET.register_namespace('','http://www.w3.org/2000/svg')
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    ET.ElementTree(root).write(destination/'mpunav.svg',encoding='utf-8',xml_declaration=True)
    return {'name':name,'url':BASE+name,'viewBox':bounds,'transform':None,'accuracyVerified':False,
            'referenceScale':54.8 if name=='PK-MAIN-5.svg' else None,
            'scaleNote':'54,8 SVG-ед./м использовались в предыдущем проекте навигации; физически не подтверждены.' if name=='PK-MAIN-5.svg' else 'Масштаб требует привязки по контрольным точкам.'}
