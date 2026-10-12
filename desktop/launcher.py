import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser
import psutil

ROOT=Path(__file__).resolve().parent.parent
PID=ROOT/'data/service.json'
PORT=4318


def health():
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/api/health',timeout=1) as response:return json.load(response)
    except Exception:return None


def start():
    current=health()
    if current:
        if Path(current['root']).resolve()!=ROOT:raise RuntimeError('Порт 4318 занят другой копией 3D. Сначала закрой её.')
        webbrowser.open(f'http://127.0.0.1:{PORT}');print('3D уже работает.');return
    (ROOT/'data').mkdir(exist_ok=True);(ROOT/'logs').mkdir(exist_ok=True)
    try:
        from get_fonts import install
        install()
    except Exception:pass
    with (ROOT/'logs/server.log').open('ab') as log:
        flags=subprocess.CREATE_NO_WINDOW|subprocess.DETACHED_PROCESS if os.name=='nt' else 0
        process=subprocess.Popen([sys.executable,str(ROOT/'desktop/service.py'),'--port',str(PORT)],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=flags)
    PID.write_text(json.dumps({'pid':process.pid,'created':psutil.Process(process.pid).create_time(),'script':str(ROOT/'desktop/service.py')}),encoding='utf-8')
    for _ in range(100):
        if process.poll() is not None:raise RuntimeError('Сервер завершился. Подробности: logs/server.log')
        if health():webbrowser.open(f'http://127.0.0.1:{PORT}');print('3D запущен. Проекты сохраняются в data/projects.');return
        time.sleep(.1)
    raise RuntimeError('Сервер не ответил. Подробности: logs/server.log')


def stop():
    if not PID.exists():print('У этой копии 3D нет запущенного сервера.');return
    info=json.loads(PID.read_text(encoding='utf-8'))
    try:process=psutil.Process(info['pid'])
    except psutil.NoSuchProcess:print('Сервер уже закрыт.');return
    command=process.cmdline()
    if abs(process.create_time()-info['created'])>.1 or str(ROOT/'desktop/service.py') not in command:raise RuntimeError('PID принадлежит другому процессу. Он не будет остановлен.')
    descendants=process.children(recursive=True)
    children=[]
    for child in descendants:
        if str(ROOT/'desktop/service.py') in child.cmdline():children.append(child)
        elif child.name().lower()!='conhost.exe':raise RuntimeError('Дочерний процесс не принадлежит серверу 3D.')
    for child in reversed(children):
        try:child.terminate()
        except psutil.NoSuchProcess:pass
    for child in reversed(children):
        try:child.wait(timeout=10)
        except psutil.NoSuchProcess:pass
    try:process.terminate();process.wait(timeout=10)
    except psutil.NoSuchProcess:pass
    PID.unlink(missing_ok=True)
    print('3D закрыт. Проекты и модели сохранены.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['start','stop']);args=parser.parse_args()
    try:start() if args.action=='start' else stop()
    except Exception as error:print(str(error));sys.exit(1)
