"""Import self-contained GLB exports without uploading them to external services."""
import json
import shutil
import struct
from pathlib import Path


def import_glb(source, destination):
    source, destination = Path(source), Path(destination)
    with source.open('rb') as stream:
        header = stream.read(12)
        if len(header) != 12:
            raise ValueError('Файл GLB слишком короткий')
        magic, version, size = struct.unpack('<III', header)
        if magic != 0x46546C67 or version != 2 or size != source.stat().st_size:
            raise ValueError('Некорректный заголовок GLB 2.0')
        chunk_size, kind = struct.unpack('<II', stream.read(8))
        if kind != 0x4E4F534A or chunk_size > min(size-20, 32*1024**2):
            raise ValueError('Некорректный JSON-блок GLB')
        document = json.loads(stream.read(chunk_size))
    if document.get('asset', {}).get('version') != '2.0':
        raise ValueError('Поддерживается glTF 2.0')
    for obj in document.get('buffers', []) + document.get('images', []):
        uri = obj.get('uri', '')
        if uri and not uri.startswith('data:'):
            raise ValueError('Нужен GLB со встроенными текстурами, без внешних ссылок')
    primitives = [p for m in document.get('meshes', []) for p in m.get('primitives', [])]
    if not primitives:
        raise ValueError('В файле GLB нет геометрии')
    if any(p.get('mode', 4) not in (0, 4, 5, 6) for p in primitives):
        raise ValueError('Поддерживаются точки и треугольная сетка')
    mesh = any(p.get('mode', 4) in (4, 5, 6) for p in primitives)
    destination.mkdir(parents=True, exist_ok=True)
    filename = 'mesh.glb' if mesh else 'points.glb'
    shutil.copyfile(source, destination/filename)
    count = sum(document['accessors'][p['attributes']['POSITION']]['count'] for p in primitives)
    report = {'frames': None, 'points': count, 'mesh': mesh, 'importedModel': True,
              'availableFiles': [filename], 'accuracyVerified': False,
              'warnings': ['Импортирована готовая модель; исходные LiDAR-кадры и траектория недоступны.',
                           'Масштаб и точность нужно проверить контрольными замерами.']}
    (destination/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report
