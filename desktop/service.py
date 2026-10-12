import argparse
import json
import mimetypes
import threading
import uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs,unquote

from project_store import ProjectStore,atomic_json
from import_model import import_glb
from las_processing import import_las
from planar import analyze
from plan_analysis import analyze_plan
from reconstruct import process
from mpunav import catalog,fetch_map

ROOT=Path(__file__).resolve().parent
DATA=ROOT.parent/'data';DATA.mkdir(exist_ok=True)
STORE=ProjectStore(DATA)
LOCK=threading.RLock();COMPUTE=threading.Lock();JOBS={}


def save_job(identifier):atomic_json(DATA/identifier/'job.json',JOBS[identifier])


def progress(identifier,percent,message):
    with LOCK:
        JOBS[identifier].update(progress=percent,message=message)
        save_job(identifier)


def compute(identifier):
    folder=DATA/identifier
    try:
        with COMPUTE:
            if (folder/'source.zip').exists():
                report=process(folder/'source.zip',folder,lambda p,m:progress(identifier,p,m))
                report['pointCloud']=(folder/'points.glb').exists()
            else:
                report=import_glb(folder/'source.glb',folder) if (folder/'source.glb').exists() else {'mesh':False,'importedModel':True,'frames':None,'accuracyVerified':False}
                if (folder/'source.las').exists():
                    las=import_las(folder/'source.las',folder,folder/'mesh.glb' if report['mesh'] else None,lambda p,m:progress(identifier,p,m))
                    report.update(pointCloud=True,las=las,points=las['outputPoints'])
            if report['mesh']:
                progress(identifier,55,'GPU: поиск плоскостей и безопасное выравнивание')
                analysis=analyze(folder/'mesh.glb',folder)
                report.update(straightened=True,processingVersion=2,planarAnalysis={k:v for k,v in analysis.items() if k!='planes'})
            report['availableFiles']=[p.name for p in folder.iterdir() if p.name in {'mesh.glb','points.glb','points.ply','straightened.glb','planes.json','las.json'}]
            report['legacyResult']=(folder/'previous-v1.glb').exists()
            if (folder/'plan-comparison.png').exists():report['planComparison']='plan-comparison.png'
            atomic_json(folder/'report.json',report)
        with LOCK:
            JOBS[identifier].update(state='done',progress=100,message='Обработка v2 завершена',report=report)
            save_job(identifier)
    except Exception as error:
        with LOCK:
            JOBS[identifier].update(state='error',message=str(error));save_job(identifier)


def process_plan(project_id):
    try:
        p=STORE.get(project_id);folder=STORE.root/project_id
        result=analyze_plan(folder/p['plan']['source'],folder)
        with STORE.lock:
            p=STORE.get(project_id);p['plan'].update(state='done',analysis=result);STORE.save(p)
    except Exception as error:
        with STORE.lock:
            p=STORE.get(project_id);p['plan'].update(state='error',error=str(error));STORE.save(p)


class Handler(BaseHTTPRequestHandler):
    def reply(self,data,status=200):
        raw=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
    def read_json(self):
        length=int(self.headers.get('Content-Length','0'))
        if not 0<length<=4*1024**2:raise ValueError('Некорректный размер запроса')
        return json.loads(self.rfile.read(length))
    def upload(self,path,maximum=2*1024**3):
        length=int(self.headers.get('Content-Length','0'))
        if not 0<length<=maximum:raise ValueError('Файл пуст или превышает допустимый размер')
        path.parent.mkdir(parents=True,exist_ok=True)
        temp=path.with_suffix(path.suffix+'.upload')
        with temp.open('wb') as out:
            remaining=length
            while remaining:
                chunk=self.rfile.read(min(1024**2,remaining))
                if not chunk:raise ValueError('Передача файла прервана')
                out.write(chunk);remaining-=len(chunk)
        temp.replace(path)
    def do_GET(self):
        parsed=urlsplit(self.path);path=parsed.path;query=parse_qs(parsed.query)
        try:
            if path=='/api/projects':return self.reply(STORE.all())
            if path=='/api/mpunav/catalog':return self.reply(catalog(DATA))
            if path=='/api/jobs':
                project_id=query.get('project',[''])[0]
                project=STORE.get(project_id) if project_id else None
                with LOCK:jobs=[dict(id=k,**v) for k,v in JOBS.items() if project is None or k in project['scans']]
                return self.reply(jobs)
            if path=='/api/health':return self.reply({'status':'ok','root':str(ROOT.parent),'version':'0.2'})
            base=DATA if path.startswith('/data/') else ROOT/'web'
            target=(base/(path[6:] if path.startswith('/data/') else 'index.html' if path=='/' else path.lstrip('/'))).resolve()
            if not target.is_relative_to(base.resolve()) or not target.is_file() or target.suffix.lower() not in {'.html','.js','.css','.json','.glb','.ply','.png','.jpg','.jpeg','.svg','.pdf','.woff2'}:return self.reply({'error':'Не найдено'},404)
            self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(target.name)[0] or 'application/octet-stream');self.send_header('Content-Length',str(target.stat().st_size));self.send_header('Cache-Control','no-store');self.end_headers()
            with target.open('rb') as stream:
                while chunk:=stream.read(1024**2):self.wfile.write(chunk)
        except (ValueError,KeyError,json.JSONDecodeError) as error:self.reply({'error':str(error)},400)
    def do_POST(self):
        if self.headers.get('Origin') not in {None,f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'}:return self.reply({'error':'Недопустимый источник'},403)
        try:
            path=urlsplit(self.path).path
            if path=='/api/projects':return self.reply(STORE.create(self.read_json().get('name')),201)
            if path=='/api/measurements':
                data=self.read_json();p=STORE.get(data['project']);items=data['items']
                if not isinstance(items,list) or len(items)>1000:raise ValueError('Некорректные измерения')
                p['measurements']=items;STORE.save(p);return self.reply({'saved':True})
            if path=='/api/mpunav/map':
                data=self.read_json();p=STORE.get(data['project']);mapping=fetch_map(data['name'],DATA,STORE.root/p['id']);p['mpunav']=mapping;STORE.save(p);return self.reply(mapping)
            if path=='/api/mpunav/save':
                data=self.read_json();p=STORE.get(data['project'])
                if not p.get('mpunav'):raise ValueError('Сначала загрузи карту')
                transform=data['transform']
                import math
                if any(not math.isfinite(float(transform[k])) for k in ['scale','angle','x','y']) or not 0<float(transform['scale'])<10000:raise ValueError('Некорректная привязка')
                p['mpunav']['transform']=transform;p['mpunav']['anchors']=data.get('anchors',[]);STORE.save(p);return self.reply({'saved':True})
            if path=='/api/mpunav/export':
                import math,xml.etree.ElementTree as ET
                data=self.read_json();p=STORE.get(data['project']);mapping=p.get('mpunav');points=data['points']
                if not mapping or not mapping.get('transform'):raise ValueError('Сначала сохрани привязку')
                if not isinstance(points,list) or len(points)>10000:raise ValueError('Некорректные точки')
                root=ET.parse(STORE.root/p['id']/'mpunav.svg').getroot();ns='{http://www.w3.org/2000/svg}'
                group=ET.SubElement(root,ns+'g',{'id':'floorcopy-scan-overlay','data-accuracy':'unverified'})
                t=mapping['transform'];c,s=math.cos(t['angle']),math.sin(t['angle'])
                for point in points:
                    if len(point)!=3 or not all(math.isfinite(float(v)) for v in point):raise ValueError('Некорректная точка')
                    x=t['scale']*(point[0]*c-point[2]*s)+t['x'];y=t['scale']*(point[0]*s+point[2]*c)+t['y']
                    ET.SubElement(group,ns+'circle',{'cx':str(x),'cy':str(y),'r':'1.5','fill':'#63e3d4','opacity':'.65'})
                ET.ElementTree(root).write(STORE.root/p['id']/'mpunav-with-scan.svg',encoding='utf-8',xml_declaration=True)
                return self.reply({'url':f"/data/projects/{p['id']}/mpunav-with-scan.svg"})
            if path=='/api/upload':
                project_id=self.headers.get('X-Project-ID');STORE.get(project_id)
                name=unquote(self.headers.get('X-File-Name',''));extension=Path(name).suffix.lower()
                if extension not in {'.glb','.las','.zip'}:raise ValueError('Поддерживаются GLB, LAS и ZIP Floor Copy')
                identifier=self.headers.get('X-Scan-ID')
                if identifier:
                    with LOCK:
                        if identifier not in JOBS or JOBS[identifier]['project']!=project_id:raise ValueError('Скан не принадлежит проекту')
                        if JOBS[identifier]['state']=='running':raise ValueError('Нельзя менять файлы во время обработки')
                else:
                    identifier=uuid.uuid4().hex
                    with LOCK:JOBS[identifier]={'project':project_id,'name':Path(name).stem,'state':'ready','progress':0,'message':'Файлы загружены. Нажми «Обработать».','files':[],'report':{}}
                    STORE.attach(project_id,identifier)
                folder=DATA/identifier
                with LOCK:
                    if extension=='.zip' and any(e in JOBS[identifier]['files'] for e in ['.glb','.las']):raise ValueError('ZIP нельзя смешивать с GLB/LAS')
                    if extension in ['.glb','.las'] and '.zip' in JOBS[identifier]['files']:raise ValueError('ZIP нельзя смешивать с GLB/LAS')
                self.upload(folder/('source'+extension))
                with LOCK:
                    job=JOBS[identifier]
                    if extension not in job['files']:job['files'].append(extension)
                    if extension=='.glb':job['report']=import_glb(folder/'source.glb',folder)
                    job.update(state='ready',progress=0,message='Файлы загружены. Нажми «Обработать».')
                    save_job(identifier)
                return self.reply({'id':identifier},201)
            if path in {'/api/process','/api/regularize'}:
                identifier=self.read_json()['id']
                with LOCK:
                    if identifier not in JOBS:raise ValueError('Скан не найден')
                    if any(j['state']=='running' for j in JOBS.values()):raise ValueError('Дождись завершения текущей обработки')
                    JOBS[identifier].update(state='running',progress=1,message='Подготавливаю данные');save_job(identifier)
                threading.Thread(target=compute,args=(identifier,),daemon=True).start();return self.reply({'id':identifier},202)
            if path=='/api/plan':
                project_id=self.headers.get('X-Project-ID');p=STORE.get(project_id)
                extension=Path(unquote(self.headers.get('X-File-Name',''))).suffix.lower()
                if extension not in {'.png','.jpg','.jpeg','.pdf'}:raise ValueError('Планировка: PNG, JPG или PDF')
                name='source-plan'+extension;self.upload(STORE.root/project_id/name,maximum=50*1024**2)
                p['plan']={'source':name,'state':'running'};STORE.save(p)
                threading.Thread(target=process_plan,args=(project_id,),daemon=True).start();return self.reply({'accepted':True},202)
            return self.reply({'error':'Не найдено'},404)
        except (ValueError,KeyError,TypeError,json.JSONDecodeError) as error:return self.reply({'error':str(error)},400)
        except Exception as error:return self.reply({'error':str(error)},500)


def load():
    for path in DATA.glob('*/job.json'):
        job=json.loads(path.read_text(encoding='utf-8-sig'))
        if job['state']=='running':job.update(state='ready',message='Обработка была прервана. Запусти снова.')
        JOBS[path.parent.name]=job
    legacy=[p for p in DATA.glob('*/report.json') if p.parent.name not in JOBS]
    if legacy:
        project=STORE.create('Комната 18,9 м²')
        for path in legacy:
            if not (path.parent/'source.glb').exists() and (path.parent/'mesh.glb').exists():
                import shutil;shutil.copyfile(path.parent/'mesh.glb',path.parent/'source.glb')
            report=json.loads(path.read_text(encoding='utf-8-sig'))
            identifier=path.parent.name
            JOBS[identifier]={'project':project['id'],'name':report.get('title','Первый скан'),'state':'done','progress':100,'message':'Сохранённый скан','files':[p.suffix for p in path.parent.glob('source.*')],'report':report}
            STORE.attach(project['id'],identifier);save_job(identifier)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=4318);args=parser.parse_args()
    load();print(f'Floor Copy 0.2: http://127.0.0.1:{args.port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()


if __name__=='__main__':main()
