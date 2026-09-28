"""
Small helpers shared by ssl_qalas_save_h5.py and h5_to_maps.py.

mperm()/mflip() exist so the Python code can mirror the original
permute()/flip() calls almost verbatim (same numeric literals, 1-indexed,
as in the original local-machine source) instead of being silently
re-derived into 0-indexed numpy axes by hand. That makes it possible to
diff the Python logic against the original ssl_qalas_save_h5.py /
h5_to_maps.py implementation line by line during review, which matters
for code that reorients real patient images.
"""

from pathlib import Path

import numpy as np


def mperm(arr: np.ndarray, order_1indexed) -> np.ndarray:
    """Equivalent of the original permute(arr, order_1indexed) call.

    order_1indexed is 1-indexed, exactly as written in the original source
    (e.g. permute(x, [3, 2, 1, 4])  ->  mperm(x, [3, 2, 1, 4])).
    """
    axes = tuple(d - 1 for d in order_1indexed)
    return np.transpose(arr, axes=axes)


def mflip(arr: np.ndarray, dims_1indexed) -> np.ndarray:
    """Equivalent of one or more of the original flip(arr, dim) calls.

    dims_1indexed is 1-indexed and may be a single int or a list/tuple
    (e.g. two calls flip(x,1); flip(x,3)  ->  mflip(x, [1, 3])).
    """
    if isinstance(dims_1indexed, int):
        dims_1indexed = [dims_1indexed]
    axes = tuple(d - 1 for d in dims_1indexed)
    return np.flip(arr, axis=axes)


def rsos(img: np.ndarray, dim_1indexed: int) -> np.ndarray:
    """Equivalent of the original rsos(img, chan_dim) helper:
    root-sum-of-squares along one (1-indexed) dimension.
    """
    axis = dim_1indexed - 1
    return np.sqrt(np.sum(np.abs(img) ** 2, axis=axis))


def dicomread_dir(dicom_dir) -> np.ndarray:
    """Equivalent of the original dicomread_dir helper: stack every file in
    a directory as DICOM pixel-data slices, in directory-listing order.

    NOTE: exactly like the original version (see the input_type == 1
    branch and its "TODO ADD HEADER READING FROM DICOM FILES" comment in
    ssl_qalas_save_h5.py), the DICOM input path is not exercised by the
    pipeline today -- input_type is hardcoded to 2 (NIFTI). This is kept
    as a faithful, working translation in case that path gets finished
    later, but it has not been run against real DICOM data as part of
    this port.
    """
    import pydicom

    dicom_dir = Path(dicom_dir)
    files = sorted(p for p in dicom_dir.iterdir() if p.is_file())
    slices = [pydicom.dcmread(str(f)).pixel_array for f in files]
    return np.stack(slices, axis=-1)
