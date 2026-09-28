#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extracts the final T1/T2/PD/IE parametric map NIfTIs from the h5
reconstruction produced by the SSL-QALAS training/inference pipeline.

Usage:
    python3 h5_to_maps.py <sub_ses> <f_QALAS> <dir_bids>
"""

import re
import sys
from pathlib import Path

import h5py
import nibabel as nib
import numpy as np

from py_utils import mflip, mperm


def _as_text(value):
    """h5py hands string attributes back as bytes or str depending on how
    they were written (MATLAB writes fixed-length char -> bytes)."""
    if isinstance(value, bytes):
        return value.decode("ascii")
    if isinstance(value, np.ndarray):
        return _as_text(value.reshape(-1)[0])
    return str(value)


def h5_to_maps(sub_ses: str, f_QALAS: str, dir_bids: str) -> None:
    match = re.search(r"run-\d+", f_QALAS)
    if match is None:
        raise ValueError(f"Could not find a 'run-<n>' token in f_QALAS={f_QALAS!r}")
    sub_ses_run = f"{sub_ses}/{match.group(0)}"
    sub_ses_run_ = sub_ses_run.replace("/", "_")

    print(sub_ses_run)

    h5_root = Path("h5_data") / sub_ses_run.replace("-", "")
    recon_file = h5_root / "reconstructions" / "val_data.h5"
    with h5py.File(recon_file, "r") as hf:
        # `.T` converts h5py's (n_slices, H, W) view into the (W, H, n_slices)
        # view MATLAB's h5read gives the .m -- see the module docstring.
        T1_cropped = np.asarray(hf["reconstruction_t1"]).T
        T2_cropped = np.asarray(hf["reconstruction_t2"]).T
        PD_cropped = np.asarray(hf["reconstruction_pd"]).T
        IE_cropped = np.asarray(hf["reconstruction_ie"]).T

    attr_file = h5_root / "multicoil_val" / "val_data.h5"
    with h5py.File(attr_file, "r") as hf:
        manufacturer = _as_text(hf.attrs["scan_manufacturer"])
        # xRange/yRange are written by ssl_qalas_save_h5.py too but, like in
        # the .m (where the corresponding reads are commented out), are not
        # used here -- only Z is ever actually cropped.
        zRange = np.rint(np.asarray(hf.attrs["zRange"])).astype(np.int64)
        original_size = tuple(
            int(v) for v in np.rint(np.asarray(hf.attrs["original_size"])).astype(np.int64)
        )

    # ---- Restoring back into full volume ----
    # zRange was stored 1-indexed (matching ssl_qalas_save_h5.py) -> 0-indexed.
    zRange0 = zRange - 1

    expected = (original_size[0], original_size[1], zRange0.size)
    if T1_cropped.shape != expected:
        raise ValueError(
            "Reconstruction volume does not fit the stored crop.\n"
            f"  reconstruction_t1 (MATLAB view) : {T1_cropped.shape}\n"
            f"  expected from original_size/zRange: {expected}\n"
            f"  original_size = {original_size}, len(zRange) = {zRange0.size}\n"
            "If the reconstruction file's axis order changed, adjust the `.T` "
            "in h5_to_maps.py (see the module docstring)."
        )

    T1 = np.zeros(original_size, dtype=np.float32)
    T1[:, :, zRange0] = T1_cropped
    T2 = np.zeros(original_size, dtype=np.float32)
    T2[:, :, zRange0] = T2_cropped
    PD = np.zeros(original_size, dtype=np.float32)
    PD[:, :, zRange0] = PD_cropped
    IE = np.zeros(original_size, dtype=np.float32)
    IE[:, :, zRange0] = IE_cropped

    qalas_path = Path(dir_bids) / sub_ses / "anat" / f_QALAS
    orig_img = nib.load(str(qalas_path))

    # ---- Fixing dimensions and info ----
    if manufacturer.upper() == "GE":
        T1 = mflip(mperm(T1, [3, 2, 1]), [3, 2, 1])
        T2 = mflip(mperm(T2, [3, 2, 1]), [3, 2, 1])
        PD = mflip(mperm(PD, [3, 2, 1]), [3, 2, 1])
        IE = mflip(mperm(IE, [3, 2, 1]), [3, 2, 1])
    else:
        # NOTE_CANON: Canon shares the Siemens/Philips branch; see the
        # orientation caveat in ssl_qalas_save_h5.py -- verify the first
        # Canon output against the source DICOMs.
        T1 = mflip(mperm(T1, [2, 1, 3]), [3, 2])
        T2 = mflip(mperm(T2, [2, 1, 3]), [3, 2])
        PD = mflip(mperm(PD, [2, 1, 3]), [3, 2])
        IE = mflip(mperm(IE, [2, 1, 3]), [3, 2])

    hdr = orig_img.header.copy()
    hdr.set_data_dtype(np.float32)
    # info_NIFTI.AdditiveOffset = 0 / MultiplicativeScaling = 1 in the .m.
    hdr.set_slope_inter(1, 0)
    # The .m also drops the 4th dimension when the source QALAS is 4D;
    # nibabel takes the shape from the data array, so that is automatic.

    out_dir = Path("maps") / sub_ses / "anat"
    out_dir.mkdir(parents=True, exist_ok=True)

    for suffix, vol in (("_T1map", T1), ("_T2map", T2), ("_PDmap", PD), ("_IEmap", IE)):
        img = nib.Nifti1Image(np.ascontiguousarray(vol, dtype=np.float32), orig_img.affine, hdr)
        img.header.set_slope_inter(1, 0)
        nib.save(img, str(out_dir / f"{sub_ses_run_}{suffix}.nii.gz"))


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit("Usage: python3 h5_to_maps.py <sub_ses> <f_QALAS> <dir_bids>")
    h5_to_maps(*sys.argv[1:4])
