import json
import hashlib
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from project_store import atomic_json

BASE='https://mpunav.ru/cdn/plans/'


def catalog(data):
    folder=Path(data)/'mpunav';folder.mkdir(exist_ok=True);path=folder/'manifest.json'
    if path.exists():document=json.loads(path.read_text(encoding='utf-8'))
    else:
        with urllib.request.urlopen(BASE+'manifest.json',timeout=25) as response:document=json.load(response)
        atomic_json(path,document)
    return [{'name':n,'size':v['size'],'hash':v['hash'],'version':document.get('version'),
             'cached':(folder/'maps'/n).is_file()} for n,v in document['plans'].items() if re.fullmatch(r'[A-Za-z0-9_-]+\.svg',n)]


def map_bytes(item,data):
    folder=Path(data)/'mpunav'/'maps';folder.mkdir(parents=True,exist_ok=True)
    path=folder/item['name']
    def valid(raw):
        return len(raw)==item['size'] and 'sha256-'+hashlib.sha256(raw).hexdigest()==item['hash']
    if path.exists():
        raw=path.read_bytes()
        if valid(raw):return raw
    with urllib.request.urlopen(BASE+item['name'],timeout=40) as response:raw=response.read(5*1024**2+1)
    if not valid(raw):raise ValueError('Размер или SHA-256 карты не совпадает с каталогом: '+item['name'])
    sanitized_root(raw)
    temporary=path.with_suffix('.svg.tmp');temporary.write_bytes(raw);os.replace(temporary,path)
    return raw


def sanitized_root(raw):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('Неподдерживаемый SVG')
    root=ET.fromstring(raw)
    if root.tag.split('}')[-1]!='svg':raise ValueError('Ответ не является SVG')
    for parent in root.iter():
        for child in list(parent):
            if child.tag.split('}')[-1] in {'script','foreignObject','iframe','image'}:parent.remove(child)
        for key in list(parent.attrib):
            if key.lower().startswith('on') or (key.split('}')[-1]=='href' and not parent.attrib[key].startswith('#')):del parent.attrib[key]
    return root


def download_all(data):
    folder=Path(data)/'mpunav';folder.mkdir(parents=True,exist_ok=True)
    with urllib.request.urlopen(BASE+'manifest.json',timeout=40) as response:document=json.load(response)
    atomic_json(folder/'manifest.json',document)
    items=catalog(data);failures=[];done=0
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending={pool.submit(map_bytes,item,data):item['name'] for item in items}
        for future in as_completed(pending):
            try:future.result();done+=1
            except Exception as error:failures.append({'name':pending[future],'error':str(error)})
    report={'downloaded':done,'total':len(items),'version':document.get('version'),'failures':failures}
    atomic_json(folder/'download-report.json',report)
    return report


def fetch_map(name,data,destination):
    item=next((p for p in catalog(data) if p['name']==name),None)
    if item is None:raise ValueError('Карты нет в каталоге MPUNAV')
    root=sanitized_root(map_bytes(item,data))
    view=root.get('viewBox')
    if view:bounds=[float(v) for v in re.split(r'[\s,]+',view.strip())]
    else:bounds=[0,0,float(root.get('width','1000').removesuffix('px')),float(root.get('height','1000').removesuffix('px'))]
    ET.register_namespace('','http://www.w3.org/2000/svg')
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    ET.ElementTree(root).write(destination/'mpunav.svg',encoding='utf-8',xml_declaration=True)
    return {'name':name,'url':BASE+name,'viewBox':bounds,'transform':None,'accuracyVerified':False,
            'referenceScale':54.8 if name=='PK-MAIN-5.svg' else None,
            'scaleNote':'54,8 SVG-ед./м использовались в предыдущем проекте навигации; физически не подтверждены.' if name=='PK-MAIN-5.svg' else 'Масштаб требует привязки по контрольным точкам.'}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--data',type=Path,default=Path(__file__).resolve().parent.parent/'data')
    report=download_all(parser.parse_args().data);print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(bool(report['failures']))
