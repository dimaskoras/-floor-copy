"""Optional CUDA voxel fusion. CPU remains available on machines without CUDA."""
import numpy as np

_cupy = None
_failure = None
last_backend = 'CPU'


def cupy_backend():
    global _cupy, _failure
    if _cupy is not None:
        return _cupy
    if _failure is not None:
        return None
    try:
        import cupy as cp
        if cp.cuda.runtime.getDeviceCount() < 1:
            raise RuntimeError('Нет CUDA-устройства')
        cp.get_default_memory_pool().set_limit(size=3*1024**3)
        (cp.arange(8, dtype=cp.float32)*2).sum().get()
        _cupy = cp
        return cp
    except Exception as error:
        _failure = str(error)
        return None


def fuse_cuda(points, colors, voxel):
    global last_backend
    cp = cupy_backend()
    if cp is None:
        raise RuntimeError(_failure or 'CUDA недоступна')
    try:
        p = cp.asarray(points, dtype=cp.float64)
        c = cp.asarray(colors, dtype=cp.float64)
        cells = cp.floor(p/voxel).astype(cp.int64)
        _, inverse, counts = cp.unique(cells, axis=0, return_inverse=True, return_counts=True)
        xyz = cp.zeros((len(counts),3), cp.float64)
        rgb = cp.zeros_like(xyz)
        cp.add.at(xyz, inverse, p)
        cp.add.at(rgb, inverse, c)
        result = cp.asnumpy(xyz/counts[:,None]).astype('<f4'), cp.asnumpy(cp.rint(rgb/counts[:,None])).astype(np.uint8)
        last_backend = 'CUDA'
        return result
    finally:
        cp.get_default_memory_pool().free_all_blocks()
