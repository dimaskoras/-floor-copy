"""Reconstruct a single uninterrupted ARKit scan. Units: meters, Y up."""
import json
import struct
import zipfile
from pathlib import Path
from io import BytesIO

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree


def unproject(depth, confidence, rgb, meta, stride=2):
    h, w = depth.shape
    if not np.isfinite(meta['transform']).all() or not np.isfinite(meta['intrinsics']).all():
        raise ValueError('Non-finite camera metadata')
    k = np.array(meta['intrinsics'], dtype=np.float64).reshape(3, 3, order='F')
    k[0, :] *= w / meta['imageWidth']
    k[1, :] *= h / meta['imageHeight']
    if k[0, 0] <= 0 or k[1, 1] <= 0:
        raise ValueError('Invalid focal length')
    y, x = np.mgrid[0:h:stride, 0:w:stride]
    z = depth[y, x]
    valid = np.isfinite(z) & (z > 0.15) & (z < 5) & (confidence[y, x] >= 1)
    x, y, z = x[valid], y[valid], z[valid]
    # Image coordinates point down; ARKit camera looks along negative Z.
    camera = np.column_stack(((x - k[0, 2]) * z / k[0, 0],
                              -(y - k[1, 2]) * z / k[1, 1], -z, np.ones_like(z)))
    pose = np.array(meta['transform'], dtype=np.float64).reshape(4, 4, order='F')
    points = (camera @ pose.T)[:, :3]
    colors = np.asarray(rgb.resize((w, h), Image.Resampling.BILINEAR))[y, x, :3]
    return points, colors


def fuse(points, colors, voxel=0.015):
    cells = np.floor(points / voxel).astype(np.int64)
    _, inverse, counts = np.unique(cells, axis=0, return_inverse=True, return_counts=True)
    xyz = np.zeros((len(counts), 3), np.float64)
    rgb = np.zeros_like(xyz)
    np.add.at(xyz, inverse, points)
    np.add.at(rgb, inverse, colors)
    return (xyz / counts[:, None]).astype('<f4'), np.round(rgb / counts[:, None]).astype(np.uint8)


def read_mesh(raw):
    lines = raw.decode('utf-8').splitlines()
    end = lines.index('end_header')
    header = lines[:end]
    if 'format ascii 1.0' not in header:
        raise ValueError('Expected ASCII ARKit mesh')
    nv = int(next(s.split()[-1] for s in header if s.startswith('element vertex ')))
    nf = int(next(s.split()[-1] for s in header if s.startswith('element face ')))
    body = [s for s in lines[end+1:] if s.strip()]
    vertices = np.array([[float(v) for v in row.split()[:3]] for row in body[:nv]], dtype='<f4').reshape(-1, 3)
    faces = np.array([[int(v) for v in row.split()[1:4]] for row in body[nv:nv+nf]], dtype='<u4').reshape(-1, 3)
    if len(vertices) != nv or len(faces) != nf or not np.isfinite(vertices).all():
        raise ValueError('Malformed mesh')
    if len(faces) and faces.max() >= nv:
        raise ValueError('Mesh index outside vertex array')
    return vertices, faces


def write_ply(path, points, colors, faces=None):
    faces = np.empty((0, 3), dtype='<u4') if faces is None else faces
    header = ('ply\nformat binary_little_endian 1.0\n'
              f'element vertex {len(points)}\nproperty float x\nproperty float y\nproperty float z\n'
              'property uchar red\nproperty uchar green\nproperty uchar blue\n'
              f'element face {len(faces)}\nproperty list uchar uint vertex_indices\nend_header\n')
    vertices = np.empty(len(points), dtype=[('p', '<f4', (3,)), ('c', 'u1', (3,))])
    vertices['p'], vertices['c'] = points, colors
    triangles = np.empty(len(faces), dtype=[('count', 'u1'), ('indices', '<u4', (3,))])
    triangles['count'], triangles['indices'] = 3, faces
    with open(path, 'wb') as out:
        out.write(header.encode())
        out.write(vertices.tobytes())
        out.write(triangles.tobytes())


def write_glb(path, points, colors, faces=None):
    blob, views, accessors = bytearray(), [], []

    def add(array, component, kind, normalized=False, bounds=False):
        while len(blob) % 4:
            blob.append(0)
        start = len(blob)
        blob.extend(array.tobytes())
        views.append({'buffer': 0, 'byteOffset': start, 'byteLength': array.nbytes})
        accessor = {'bufferView': len(views)-1, 'componentType': component, 'count': len(array), 'type': kind}
        if normalized:
            accessor['normalized'] = True
        if bounds:
            accessor.update(min=array.min(axis=0).tolist(), max=array.max(axis=0).tolist())
        accessors.append(accessor)
        return len(accessors)-1

    srgb = colors.astype(np.float64) / 255
    linear = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055)**2.4)
    rgba = np.column_stack((np.round(linear*255).astype(np.uint8), np.full(len(colors), 255, dtype=np.uint8)))
    primitive = {'attributes': {'POSITION': add(points.astype('<f4'), 5126, 'VEC3', bounds=True),
                                'COLOR_0': add(rgba, 5121, 'VEC4', normalized=True)}, 'mode': 0}
    if faces is not None and len(faces):
        primitive.update(mode=4, indices=add(faces.astype('<u4').ravel(), 5125, 'SCALAR'), material=0)
    gltf = {'asset': {'version': '2.0', 'generator': 'Floor Copy 0.1'}, 'scene': 0,
            'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}], 'meshes': [{'primitives': [primitive]}],
            'materials': [{'doubleSided': True, 'pbrMetallicRoughness': {'metallicFactor': 0, 'roughnessFactor': 1},
                           'extensions': {'KHR_materials_unlit': {}}}],
            'extensionsUsed': ['KHR_materials_unlit'],
            'bufferViews': views, 'accessors': accessors, 'buffers': [{'byteLength': len(blob)}]}
    doc = json.dumps(gltf, separators=(',', ':')).encode()
    doc += b' ' * (-len(doc) % 4)
    blob.extend(b'\0' * (-len(blob) % 4))
    with open(path, 'wb') as out:
        out.write(struct.pack('<III', 0x46546C67, 2, 12+8+len(doc)+8+len(blob)))
        out.write(struct.pack('<II', len(doc), 0x4E4F534A))
        out.write(doc)
        out.write(struct.pack('<II', len(blob), 0x004E4942))
        out.write(blob)


def process(archive, destination, progress=lambda percent, message: None):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    pts, cols, trajectory = [], [], []
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate ZIP members')
        manifests = [n for n in names if n == 'manifest.json' or n.endswith('/manifest.json')]
        if len(manifests) != 1:
            raise ValueError('В ZIP должен быть один manifest.json от Floor Copy')
        prefix = manifests[0][:-len('manifest.json')]
        if sum(i.file_size for i in z.infolist()) > 4 * 1024**3:
            raise ValueError('Распакованный архив превышает 4 ГБ')
        manifest = json.loads(z.read(manifests[0]))
        if manifest.get('format') != 'floorcopy-rgbd' or manifest.get('version') != 1:
            raise ValueError('Неподдерживаемый формат скана')
        count = int(manifest['frames'])
        if count < 1 or count > 240:
            raise ValueError('В скане должно быть от 1 до 240 кадров')
        for i in range(count):
            stem = prefix + f'{i:05d}'
            meta = json.loads(z.read(stem + '.json'))
            w, h = int(meta['depthWidth']), int(meta['depthHeight'])
            if w < 1 or h < 1 or w*h > 1024*1024:
                raise ValueError('Некорректный размер карты глубины')
            depth = np.frombuffer(z.read(stem + '.depth'), dtype='<f4').reshape(h, w)
            # Missing confidence is rejected: otherwise noisy samples look reliable.
            confidence = np.frombuffer(z.read(stem + '.confidence'), dtype='u1').reshape(h, w)
            image = Image.open(BytesIO(z.read(stem + '.jpg'))).convert('RGB')
            if image.size != (meta['imageWidth'], meta['imageHeight']):
                raise ValueError('Размер фото не совпадает с калибровкой')
            points, colors = unproject(depth, confidence, image, meta)
            pts.append(points)
            cols.append(colors)
            trajectory.append(np.array(meta['transform']).reshape(4, 4, order='F')[:3, 3].tolist())
            progress(int(60 * (i+1)/count), f'Читаю кадр {i+1}/{count}')
        progress(65, 'Объединяю цветные точки')
        points, colors = fuse(np.concatenate(pts), np.concatenate(cols))
        if len(points) == 0:
            raise ValueError('Нет надёжных измерений глубины')
        write_ply(destination/'points.ply', points, colors)
        write_glb(destination/'points.glb', points, colors)
        mesh_available = False
        if prefix+'mesh.ply' in names:
            vertices, faces = read_mesh(z.read(prefix+'mesh.ply'))
            if len(vertices) and len(faces):
                progress(80, 'Переношу цвет на сетку ARKit')
                distances, nearest = cKDTree(points).query(vertices, workers=2)
                vertex_colors = colors[nearest].copy()
                vertex_colors[distances > 0.15] = [130, 139, 153]
                write_ply(destination/'mesh.ply', vertices, vertex_colors, faces)
                write_glb(destination/'mesh.glb', vertices, vertex_colors, faces)
                mesh_available = True
        report = {'frames': count, 'points': len(points), 'mesh': mesh_available,
                  'bounds': [points.min(axis=0).tolist(), points.max(axis=0).tolist()],
                  'trajectory': trajectory, 'voxelMeters': 0.015, 'accuracyVerified': False,
                  'warnings': ['Точность не проверена контрольными замерами.',
                               'Цвет сетки назначен ближайшими измеренными точками; фототекстуры пока не построены.',
                               'Обрабатывается один участок. Совмещение отдельных проходов пока не реализовано.']}
        if manifest.get('events'):
            report['warnings'].append('Запись содержит прерывание AR-сессии; проверь участок.')
        (destination/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        progress(100, 'Готово')
        return report
