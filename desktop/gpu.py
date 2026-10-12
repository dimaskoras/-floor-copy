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
        minimum=cells.min(axis=0);spans=cp.asnumpy(cells.max(axis=0)-minimum+1)
        if int(spans[0])*int(spans[1])*int(spans[2])>=2**63:
            raise ValueError('Voxel-key range exceeds int64')
        shifted=cells-minimum
        keys=(shifted[:,0]*int(spans[1])+shifted[:,1])*int(spans[2])+shifted[:,2]
        # CuPy unique(axis=0) compares rows through Python on this version.
        # One-dimensional keys preserve the same lexicographic ordering and
        # execute sorting and grouping in batched GPU kernels.
        _, inverse, counts = cp.unique(keys, return_inverse=True, return_counts=True)
        xyz = cp.zeros((len(counts),3), cp.float64)
        rgb = cp.zeros_like(xyz)
        cp.add.at(xyz, inverse, p)
        cp.add.at(rgb, inverse, c)
        result = cp.asnumpy(xyz/counts[:,None]).astype('<f4'), cp.asnumpy(cp.rint(rgb/counts[:,None])).astype(np.uint8)
        last_backend = 'CUDA'
        return result
    finally:
        cp.get_default_memory_pool().free_all_blocks()
