import json
import uuid
from datetime import datetime,timezone
from pathlib import Path
from threading import RLock


def atomic_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)


class ProjectStore:
    def __init__(self,data):self.data=Path(data);self.root=self.data/'projects';self.root.mkdir(exist_ok=True);self.lock=RLock()
    def all(self,include_archived=False):
        with self.lock:
            projects=[json.loads(p.read_text(encoding='utf-8-sig')) for p in self.root.glob('*/project.json')]
            return sorted([p for p in projects if include_archived or not p.get('archived')],key=lambda p:p['created'],reverse=True)
    def archive(self,identifier,archived=True):
        with self.lock:
            project=self.get(identifier);project['archived']=bool(archived);self.save(project);return project
    def get(self,identifier):
        if not isinstance(identifier,str) or len(identifier)!=32 or any(c not in '0123456789abcdef' for c in identifier):raise ValueError('Некорректный проект')
        path=self.root/identifier/'project.json'
        if not path.exists():raise ValueError('Проект не найден')
        with self.lock:return json.loads(path.read_text(encoding='utf-8-sig'))
    def create(self,name):
        if not isinstance(name,str) or not name.strip() or len(name)>100:raise ValueError('Имя проекта: от 1 до 100 символов')
        project={'id':uuid.uuid4().hex,'name':name.strip(),'created':datetime.now(timezone.utc).isoformat(),'scans':[],'measurements':[],'plan':None}
        profile=self.data/'default-calibration.json'
        if profile.exists():project['baseline']=json.loads(profile.read_text(encoding='utf-8'))
        self.save(project);return project
    def save(self,project):
        with self.lock:atomic_json(self.root/project['id']/'project.json',project)
    def attach(self,project_id,scan_id):
        with self.lock:
            p=self.get(project_id)
            if scan_id not in p['scans']:p['scans'].append(scan_id)
            self.save(p)
