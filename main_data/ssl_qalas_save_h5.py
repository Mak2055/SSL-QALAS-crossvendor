#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Builds the h5 files that the SSL-QALAS training/inference pipeline reads,
from the raw 3D-QALAS and B1+ NIfTI files.

This script expects the brain mask to already exist at
$dir_tool/synthstrip_mask/<...>, produced by FreeSurfer's `mri_synthstrip`
(called from submit_CPU.sh before this script runs).

Usage:
    python3 ssl_qalas_save_h5.py <sub_ses> <f_QALAS> <f_fmap> <dir_bids> <dir_tool>
"""

import json
import re
import shutil
import sys
from pathlib import Path

import h5py
import nibabel as nib
import numpy as np

from py_utils import dicomread_dir, mflip, mperm

# ---------------------------------------------------------------------------
# MATLAB imresize3 port
# ---------------------------------------------------------------------------
# Ported from MATLAB's images/private/contributions.m + resizeAlongDim.m so
# that imresize3(V, [a b c]) here matches imresize3(V, [a b c]) there. Only
# the two kernels the .m could reach are implemented ('cubic' is the default
# imresize3 uses when no method is given; 'linear' is provided in case the
# method ever gets passed explicitly).

IMRESIZE3_METHOD = "cubic"  # MATLAB imresize3 default for numeric input
IMRESIZE3_ANTIALIASING = True  # MATLAB default for every method but 'nearest'


def _cubic(x):
    """MATLAB's images/private/cubic.m (Keys kernel, a = -0.5), width 4."""
    absx = np.abs(x)
    absx2 = absx * absx
    absx3 = absx2 * absx
    return (1.5 * absx3 - 2.5 * absx2 + 1.0) * (absx <= 1) + (
        -0.5 * absx3 + 2.5 * absx2 - 4.0 * absx + 2.0
    ) * ((absx > 1) & (absx <= 2))


def _triangle(x):
    """MATLAB's images/private/triangle.m (linear kernel), width 2."""
    return (x + 1.0) * ((x >= -1) & (x < 0)) + (1.0 - x) * ((x >= 0) & (x <= 1))


_KERNELS = {"cubic": (_cubic, 4.0), "linear": (_triangle, 2.0)}


def _contributions(in_length, out_length, scale, kernel, kernel_width, antialiasing):
    """Direct port of MATLAB's images/private/contributions.m."""
    if scale < 1 and antialiasing:
        # Use a modified kernel to simultaneously interpolate and antialias.
        def h(x, _k=kernel, _s=scale):
            return _s * _k(_s * x)

        kernel_width = kernel_width / scale
    else:
        h = kernel

    # Output-space coordinates (1-based, as in MATLAB).
    x = np.arange(1, out_length + 1, dtype=np.float64)

    # Input-space coordinates. Corresponding to output space coordinate x,
    # the input space coordinate u is such that the two are aligned at their
    # centres, not their edges.
    u = x / scale + 0.5 * (1.0 - 1.0 / scale)

    left = np.floor(u - kernel_width / 2.0)
    P = int(np.ceil(kernel_width)) + 2

    indices = left[:, None] + np.arange(P, dtype=np.float64)[None, :]
    weights = h(u[:, None] - indices)

    # Normalize so that each row of weights sums to 1.
    weights = weights / weights.sum(axis=1, keepdims=True)

    # Mirror out-of-bounds indices: aux = [1:n, n:-1:1].
    aux = np.concatenate(
        [np.arange(1, in_length + 1), np.arange(in_length, 0, -1)]
    ).astype(np.int64)
    indices = aux[np.mod(indices.astype(np.int64) - 1, aux.size)]

    # Drop columns that are all zero.
    keep = np.any(weights != 0, axis=0)
    return weights[:, keep], indices[:, keep] - 1  # 0-based indices for numpy


def _resize_along_dim(vol, dim, weights, indices):
    """Port of MATLAB's resizeAlongDim: out[i] = sum_j w[i,j] * in[idx[i,j]]."""
    gathered = np.take(vol, indices.ravel(), axis=dim)
    new_shape = list(vol.shape)
    new_shape[dim] = indices.shape[0]
    new_shape.insert(dim + 1, indices.shape[1])
    gathered = gathered.reshape(new_shape)
    w_shape = [1] * gathered.ndim
    w_shape[dim] = weights.shape[0]
    w_shape[dim + 1] = weights.shape[1]
    return np.sum(gathered * weights.reshape(w_shape), axis=dim + 1)


def imresize3(vol, output_shape, method=None, antialiasing=None):
    """MATLAB-equivalent imresize3(vol, output_shape).

    Defaults to cubic interpolation with antialiasing, matching MATLAB's
    imresize3 defaults for numeric volumes.
    """
    method = IMRESIZE3_METHOD if method is None else method
    antialiasing = IMRESIZE3_ANTIALIASING if antialiasing is None else antialiasing
    kernel, kernel_width = _KERNELS[method]

    out_shape = tuple(int(v) for v in output_shape)
    in_shape = vol.shape
    if len(out_shape) != 3 or vol.ndim != 3:
        raise ValueError("imresize3 expects a 3-D volume and a 3-element output size")

    scales = [out_shape[k] / in_shape[k] for k in range(3)]

    prepared = []
    for k in range(3):
        w, idx = _contributions(
            in_shape[k], out_shape[k], scales[k], kernel, kernel_width, antialiasing
        )
        prepared.append((w, idx))

    out = vol.astype(np.float64, copy=True)
    # MATLAB resizes the dimension with the smallest scale factor first.
    for k in sorted(range(3), key=lambda d: scales[d]):
        w, idx = prepared[k]
        out = _resize_along_dim(out, k, w, idx)

    return out.astype(np.float32)


# ---------------------------------------------------------------------------
# HDF5 writing helpers -- see notes (1)-(4) in the module docstring
# ---------------------------------------------------------------------------


def _matlab_dataset(hf, name, arr, dtype=np.float32):
    """Write `arr` exactly the way MATLAB's h5create/h5write would.

    MATLAB reverses the dimension order when talking to HDF5, so a MATLAB
    array of size [a,b,c] becomes an (c,b,a) dataset on disk. Reversing the
    numpy axes here gives a byte-identical dataset.
    """
    hf.create_dataset(name, data=np.ascontiguousarray(np.asarray(arr, dtype=dtype).T))


def _easyh5_dataset(hf, name, arr, dtype=np.float32):
    """Write `arr` the way jsonlab/easyh5's saveh5 would.

    saveh5 transposes the array itself before writing, so the dataset ends up
    with the *same* index order in h5py as it had in MATLAB -- i.e. nothing
    to do here beyond writing the array as-is.
    """
    hf.create_dataset(name, data=np.ascontiguousarray(np.asarray(arr, dtype=dtype)))


def _str_attr(hf, name, value):
    """Write a string attribute the way MATLAB's h5writeatt does.

    MATLAB writes char arrays as fixed-length ASCII strings, which h5py reads
    back as `bytes`. Writing a python `str` instead would produce a
    variable-length UTF-8 attribute that reads back as `str` -- a difference
    the rest of the (MATLAB-file-trained) pipeline can trip over.
    """
    hf.attrs.create(name, np.bytes_(value.encode("ascii")))


def _num_attr(hf, name, value, dtype=np.float64):
    """Write a numeric scalar attribute as a 1-element array.

    MATLAB stores these as 1-element (not scalar) dataspaces, which is what
    fastmri/models/qalas_map.py relies on when it does
    `hf.attrs['scan_flip_ang'][0]`.

    dtype mirrors MATLAB's class for each value: the norm_*/max_* attributes
    come from `norm(single_array)`/`max(single_array)` and are therefore
    single, while the hardcoded scan_* timings are double.
    """
    if value is None:
        raise ValueError(f"attribute {name!r} is None -- a required value was not set")
    hf.attrs.create(name, np.array([value], dtype=dtype))


def _ismrmrd_header_xml(Nx, Ny, Nz):
    """The same header the .m builds via ismrmrd.xml.serialize(header)."""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ismrmrdHeader xmlns="http://www.ismrm.org/ISMRMRD"'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        ' xsi:schemaLocation="http://www.ismrm.org/ISMRMRD ismrmrd.xsd">\n'
        "  <acquisitionSystemInformation>\n"
        "    <receiverChannels>32</receiverChannels>\n"
        "  </acquisitionSystemInformation>\n"
        "  <experimentalConditions>\n"
        "    <H1resonanceFrequency_Hz>128000000</H1resonanceFrequency_Hz>\n"
        "  </experimentalConditions>\n"
        "  <encoding>\n"
        "    <encodedSpace>\n"
        f"      <matrixSize><x>{Nx * 2}</x><y>{Ny}</y><z>{Nz}</z></matrixSize>\n"
        f"      <fieldOfView_mm><x>{Nx}</x><y>{Ny}</y><z>{Nz}</z></fieldOfView_mm>\n"
        "    </encodedSpace>\n"
        "    <reconSpace>\n"
        f"      <matrixSize><x>{Nx}</x><y>{Ny}</y><z>{Nz}</z></matrixSize>\n"
        f"      <fieldOfView_mm><x>{Nx}</x><y>{Ny}</y><z>{Nz}</z></fieldOfView_mm>\n"
        "    </reconSpace>\n"
        "    <encodingLimits>\n"
        "      <kspace_encoding_step_1>"
        f"<minimum>0</minimum><maximum>{Nx - 1}</maximum><center>{Nx // 2}</center>"
        "</kspace_encoding_step_1>\n"
        "      <kspace_encoding_step_2>"
        "<minimum>0</minimum><maximum>0</maximum><center>0</center>"
        "</kspace_encoding_step_2>\n"
        "    </encodingLimits>\n"
        "    <trajectory>cartesian</trajectory>\n"
        "  </encoding>\n"
        "</ismrmrdHeader>\n"
    )


def _write_ismrmrd_header(hf, xmlstring):
    """Write the XML at /ismrmrd_header + the empty /groupname group.

    Mirrors what this project's MATLAB ismrmrd.Dataset helper leaves in the
    file (see note (4) in the module docstring).
    """
    hf.create_group("groupname")
    hf.create_dataset(
        "ismrmrd_header",
        data=xmlstring.encode("ascii"),
        dtype=h5py.string_dtype(encoding="ascii"),
    )


def _scan_parameters(manufacturer, json_contents):
    """The vendor-specific 3D-QALAS timing block from the .m.

    Evaluated *before* the h5 file is opened so that an unsupported vendor
    (or an unfilled Canon placeholder) fails before a partial file is left on
    disk. The .m evaluates it mid-write; the resulting file contents are the
    same.
    """
    manu_lower = manufacturer.lower() if manufacturer else ""
    
    scan_esp_val=json_contents["RepetitionTime"]
    if scan_esp_val > 0.1:
        print(f"Unexpectedly high RepetitionTime value ({scan_esp_val}), trying to extract from RepetitionTimeExcitation.")
        try:
            scan_esp_val=json_contents["RepetitionTimeExcitation"]
            print(f"Found RepetitionTimeExcitation, setting RepetitionTime value to {scan_esp_val}")
        except Exception:
            print("!!!!!!!!!!!!!WARNING!!!!!!!!!!!!!")
            print(f"Did not find RepetitionTimeExcitation field, preserving RepetitionTime value as {scan_esp_val} - may cause numerical issues")

    if "siemens" in manu_lower:
        p = dict(
            scan_flip_ang=4,
            scan_tf=json_contents["EchoTrainLength"],
            scan_esp=scan_esp_val,
            scan_t2_prep=0.1097,
            scan_gap_bw_ro=0.9,
            scan_tr=4.5,
            scan_time_relax_end=0,
            scan_echo2use=1,
            scan_crusher_after_T2prep=9.7e-3,
            scan_inv_pulse=12.8e-3,  # delT_M4_M5
            scan_gap_inv_readout=100e-3 - 6.45e-3,  # delT_M5_M6
        )
        return p, "SIEMENS"

    if "philips" in manu_lower:
        p = dict(
            scan_flip_ang=4,
            scan_tf=json_contents["EchoTrainLength"],
            scan_esp=scan_esp_val,
            scan_t2_prep=106.98e-3,
            scan_gap_bw_ro=0.9,
            scan_tr=4.5,
            scan_time_relax_end=0,
            scan_echo2use=1,
            scan_crusher_after_T2prep=6.22e-3,
            scan_inv_pulse=13.059e-3,  # delT_M4_M5
            scan_gap_inv_readout=106.98e-3,  # delT_M5_M6
        )
        return p, "PHILIPS"

    if "ge" in manu_lower:
        inv_pulse = 16.2e-3
        heartbeat = 66.67
        p = dict(
            scan_flip_ang=4,
            scan_tf=128,
            scan_esp=scan_esp_val,
            scan_t2_prep=0.0928,
            scan_gap_bw_ro=60 / heartbeat,
            scan_tr=4.5,
            scan_time_relax_end=0,
            scan_echo2use=3,
            scan_crusher_after_T2prep=2.34e-3,
            scan_inv_pulse=inv_pulse,  # delT_M4_M5
            scan_gap_inv_readout=97.34e-3 + 160e-6 - inv_pulse / 2,  # delT_M5_M6
        )
        return p, "GE"

    if "canon" in manu_lower:
        # NOTE_CANON -- left as None on purpose (Mak asked to leave these
        # blank rather than keep the earlier estimated defaults, now that
        # exact Canon values are being sourced directly). The .m has no Canon
        # branch at all and would simply error out on undefined variables.
        #
        # Reminders from the earlier derivation -- keep these relationships in
        # mind when filling these in:
        #  - scan_t2_prep and scan_crusher_after_T2prep are a pair:
        #    qalas_map.py computes the T2-decay exponent as
        #    (t2_prep - crusher_after_T2prep). If your t2_prep number is
        #    already the "post-crusher" duration, crusher_after_T2prep should
        #    be 0 -- don't subtract it twice.
        #  - scan_inv_pulse and scan_gap_inv_readout only ever enter the model
        #    as their SUM (folded into a single delt_m3_m4 residual). If you
        #    only have the combined total, put the whole thing into
        #    scan_gap_inv_readout and leave scan_inv_pulse at 0.
        #  - scan_tr is the per-segment repetition time (900 ms x 5 segments =
        #    4.5 s for the other three vendors); if Canon's true total
        #    repetition time is longer than scan_tr, the difference belongs in
        #    scan_time_relax_end, not scan_tr.
        p = dict(
            scan_flip_ang=None,
            scan_tf=json_contents["EchoTrainLength"],
            scan_esp=scan_esp_val,
            scan_t2_prep=None,
            scan_gap_bw_ro=None,
            scan_tr=None,
            scan_time_relax_end=None,
            scan_echo2use=None,
            scan_crusher_after_T2prep=None,
            scan_inv_pulse=None,  # delT_M4_M5
            scan_gap_inv_readout=None,  # delT_M5_M6
        )
        unset = [k for k, v in p.items() if v is None]
        if unset:
            raise ValueError(
                "Canon timing parameters are still placeholders in "
                f"ssl_qalas_save_h5.py: {', '.join(sorted(unset))}. Fill in "
                "real values in the 'canon' branch of _scan_parameters() "
                "before running."
            )
        return p, "CANON"

    raise ValueError(
        f"No 3D-QALAS timing parameters defined for manufacturer={manufacturer!r}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def save_h5(sub_ses: str, f_QALAS: str, f_fmap: str, dir_bids: str, dir_tool: str) -> None:
    # ---- Set main variables ----
    dfold = dir_bids
    ffold = f"{dir_tool}/coreg_b1_maps"

    match = re.search(r"run-\d+", f_QALAS)
    if match is None:
        raise ValueError(f"Could not find a 'run-<n>' token in f_QALAS={f_QALAS!r}")
    sub_ses_run = f"{sub_ses}/{match.group(0)}"

    # ---- Set output variables ----
    h5_root = Path(dir_tool) / "main_data" / "h5_data" / sub_ses_run.replace("-", "")
    savepath = h5_root / "multicoil_train"
    savename = "train_data.h5"
    savepath_val = h5_root / "multicoil_val"
    savename_val = "val_data.h5"
    savepath.mkdir(parents=True, exist_ok=True)
    savepath_val.mkdir(parents=True, exist_ok=True)
    (h5_root / "multicoil_test").mkdir(parents=True, exist_ok=True)
    (h5_root / "reconstructions").mkdir(parents=True, exist_ok=True)

    # ---- Provide info on B1 map ----
    compare_ref_map = False
    # False (no comparison -> will use placeholder maps)
    # True (compare ssl-qalas with reference maps, e.g. dictionary matching)

    # load_b1_map is derived from f_fmap instead of being hardcoded True.
    # run_ssl.sh's no_b1_map=1 path (and submit_CPU.sh, which passes f_fmap
    # straight through) submits jobs with f_fmap="NONE" when no B1+ fieldmap
    # was acquired/found for a session -- that sentinel is what triggers the
    # "no b1 map" branch below. Any other f_fmap value keeps load_b1_map True
    # and every line of behavior identical to the .m.
    NO_B1_MAP_SENTINEL = "NONE"
    load_b1_map = f_fmap != NO_B1_MAP_SENTINEL

    b1_type = None
    if "TFL" in f_fmap:
        b1_type = 1  # TFL-based
    elif "AFI" in f_fmap:
        b1_type = 2  # AFI-based

    input_type = 2
    # 1 (DICOM, not fully implemented -- same limitation as the .m)
    # 2 (NIFTI)

    # ---- Load data ----
    print("loading data ... ", end="", flush=True)

    json_contents = None
    manufacturer = None

    if input_type == 1:
        dpath = f"{dfold}/{sub_ses_run}/{f_QALAS}"
        b1path = f"{ffold}/{sub_ses_run}/{f_fmap}"
        input_img = dicomread_dir(dpath).astype(np.float32)
        n1, n2, n3 = input_img.shape[0], input_img.shape[1], input_img.shape[2] // 5
        input_img = input_img.reshape(n1, n2, n3, 1, 5)
        # TODO ADD HEADER READING FROM DICOM FILES (same limitation as the .m)

    elif input_type == 2:
        dpath = f"{dfold}/{sub_ses}/anat/{f_QALAS}"
        b1path = f"{ffold}/{sub_ses}/fmap/{f_fmap}"

        if "_inv-" in dpath:
            # Assumes this is the BIDS convention for when 3D-QALAS images
            # are split into five separate _inv-0 .. _inv-4 files.
            #
            # NOTE the dtype: the .m preallocates with zeros(...) -- i.e.
            # *double* -- and only casts back to single at the kspace_acq
            # step, so the normalisation below happens in double here too.
            # The nested-NIfTI branch stays single, matching `single(vol)`.
            input_inv = np.asarray(nib.load(dpath).get_fdata(), dtype=np.float32)
            input_img = np.zeros(input_inv.shape + (5,), dtype=np.float64)
            input_img[..., 0] = input_inv
            for i in range(1, 5):
                dpath_inv = dpath.replace("_inv-0", f"_inv-{i}")
                input_inv = np.asarray(nib.load(dpath_inv).get_fdata(), dtype=np.float32)
                input_img[..., i] = input_inv
        else:
            # 3D-QALAS images nested as a single 4D NIfTI (Nx, Ny, Nz, 5)
            input_img = np.asarray(nib.load(dpath).get_fdata(), dtype=np.float32)

        # Loading the BIDS .json sidecar
        filename = re.sub(r"\.nii.*$", ".json", dpath)
        with open(filename) as fh:
            json_contents = json.load(fh)
        manufacturer = json_contents["Manufacturer"]

        # NIFTI are rotated compared to DICOM files; rotate back into the
        # same space.
        if "ge" in manufacturer.lower():
            input_img = mperm(input_img, [3, 2, 1, 4])
            input_img = input_img[:, :, :, np.newaxis, :]
            input_img = mflip(input_img, [1, 2, 3])
        else:
            # NOTE_CANON: Canon falls into this branch (same as
            # Siemens/Philips) because it's the more common orientation
            # convention and GE is the documented outlier in the .m. This has
            # NOT been verified against an actual Canon NIfTI -- view a
            # converted volume next to the DICOMs the first time you run this
            # and confirm L/R, A/P and S/I all come out correct; if they
            # don't, this is the block to adjust (and the matching block in
            # h5_to_maps.py, which is its exact inverse).
            input_img = mperm(input_img, [2, 1, 3, 4])
            input_img = input_img[:, :, :, np.newaxis, :]
            input_img = mflip(input_img, [1, 3])

    else:
        raise ValueError(f"Unsupported input_type={input_type}")

    Nx, Ny, Nz = input_img.shape[0], input_img.shape[1], input_img.shape[2]

    if load_b1_map:
        if input_type == 1:
            B1_map = dicomread_dir(b1path).astype(np.float32)
        else:
            loaded_b1 = np.asarray(nib.load(b1path).get_fdata(), dtype=np.float32)
            if "ge" in manufacturer.lower():
                B1_map = mperm(loaded_b1, [3, 2, 1])
                B1_map = mflip(B1_map, [1, 2, 3])
            else:
                # NOTE_CANON: same orientation caveat as above.
                B1_map = mperm(loaded_b1, [2, 1, 3])
                B1_map = mflip(B1_map, [1, 3])

        # Normalize TFL maps (for AFI it is performed at the estimation step,
        # in calculate_afi_b1.py)
        if b1_type == 1:
            B1_map = B1_map / 800.0
        # elif b1_type == 2:
        #     B1_map = B1_map / 60.0  # AFI-based -- commented out in the .m too

        B1_map = imresize3(B1_map, (Nx, Ny, Nz))
        B1_map = np.clip(B1_map, 0.65, 1.35)
    else:
        # No B1+ map was provided (f_fmap == "NONE"). The .m creates the
        # uniform map further down (after the crop); it has to be built here
        # instead, on the *pre-crop* grid, because the crop below does
        # `B1_map = B1_map[:, :, zRange0]` and needs it to already exist with
        # input_img's pre-crop shape. The end result is identical.
        B1_map = np.ones((Nx, Ny, Nz), dtype=np.float32)

    print("done")

    # ---- Brain mask: load the pre-computed SynthStrip mask ----
    bmask_path = f"{dir_tool}/synthstrip_mask/{f_QALAS.replace('_inv-0', '_inv-2')}"
    loaded_bmask = np.asarray(nib.load(bmask_path).get_fdata(), dtype=np.float32)
    if "ge" in manufacturer.lower():
        bmask = mperm(loaded_bmask, [3, 2, 1])
        bmask = mflip(bmask, [1, 2, 3])
    else:
        # NOTE_CANON: same orientation caveat as the QALAS image/B1 map above.
        bmask = mperm(loaded_bmask, [2, 1, 3])
        bmask = mflip(bmask, [1, 3])

    # ---- Brain crop: drop empty slices outside the mask, Z only ----
    # xRange/yRange are computed too (saved as h5 attributes below) but only
    # ever *applied* to the crop along Z -- ported as-is, not "fixed", to
    # match the .m exactly. h5_to_maps.py reads zRange/original_size back to
    # re-embed the cropped maps into the original volume size.
    x_idx, y_idx, z_idx = np.nonzero(bmask != 0)
    xRange0 = np.arange(x_idx.min(), x_idx.max() + 1)  # 0-indexed, used for the crop
    yRange0 = np.arange(y_idx.min(), y_idx.max() + 1)
    zRange0 = np.arange(z_idx.min(), z_idx.max() + 1)
    original_size = np.array(bmask.shape)

    bmask = bmask[:, :, zRange0]
    B1_map = B1_map[:, :, zRange0]
    input_img = input_img[:, :, zRange0, :, :]

    # 1-indexed versions, stored as h5 attributes (zRange/original_size are
    # read back by h5_to_maps.py).
    xRange = xRange0 + 1
    yRange = yRange0 + 1
    zRange = zRange0 + 1

    # ---- Organize the variables ----
    # Recomputed post-crop, and note this happens *after* the [2,1,3,4]
    # permute above, exactly as in the .m -- so "Nx" is the NIfTI's second
    # axis and "Ny" its first. Kept as-is so the h5 layout matches.
    Nx, Ny, Nz = input_img.shape[0], input_img.shape[1], input_img.shape[2]
    input_img = input_img / np.max(input_img)

    sens = np.ones((Nx, Ny, Nz, 1), dtype=np.float32)
    mask = np.ones((Nx, Ny), dtype=np.float32)
    if not compare_ref_map:
        T1_map = np.full((Nx, Ny, Nz), 5.0, dtype=np.float32)
        T2_map = np.full((Nx, Ny, Nz), 2.5, dtype=np.float32)
        PD_map = np.full((Nx, Ny, Nz), 1.0, dtype=np.float32)
        IE_map = np.full((Nx, Ny, Nz), 1.0, dtype=np.float32)
    # B1_map is already a uniform 1.0 map of the correct (post-crop) shape by
    # this point when load_b1_map is False -- built and cropped alongside the
    # real-map case above.

    input_img = mperm(input_img, [2, 1, 4, 3, 5])
    sens = mperm(sens, [2, 1, 4, 3])

    T1_map = mperm(T1_map, [2, 1, 3])
    T2_map = mperm(T2_map, [2, 1, 3])
    PD_map = mperm(PD_map, [2, 1, 3])
    IE_map = mperm(IE_map, [2, 1, 3])
    B1_map = mperm(B1_map, [2, 1, 3])

    bmask = mperm(bmask, [2, 1, 3])
    mask = mperm(mask, [2, 1])

    kspace_acq1 = input_img[:, :, :, :, 0].astype(np.float32)
    kspace_acq2 = input_img[:, :, :, :, 1].astype(np.float32)
    kspace_acq3 = input_img[:, :, :, :, 2].astype(np.float32)
    kspace_acq4 = input_img[:, :, :, :, 3].astype(np.float32)
    kspace_acq5 = input_img[:, :, :, :, 4].astype(np.float32)

    # Vendor timings -- resolved before anything is written (see the note in
    # _scan_parameters).
    scan_params, att_manufacturer = _scan_parameters(manufacturer, json_contents)

    # ---- Save data ----
    print("save h5 data ... ", end="", flush=True)

    file_name = savepath / savename
    file_name_val = savepath_val / savename_val

    att_patient = "0000"
    att_seq = "QALAS"

    kspace_acq1 = mperm(kspace_acq1, [4, 3, 2, 1])
    kspace_acq2 = mperm(kspace_acq2, [4, 3, 2, 1])
    kspace_acq3 = mperm(kspace_acq3, [4, 3, 2, 1])
    kspace_acq4 = mperm(kspace_acq4, [4, 3, 2, 1])
    kspace_acq5 = mperm(kspace_acq5, [4, 3, 2, 1])
    coil_sens = mperm(sens, [4, 3, 2, 1])  # noqa: F841 (computed, not written -- as in the .m)

    with h5py.File(file_name, "w") as hf:
        # saveh5(...) in the .m: real single, same index order in h5py as in
        # MATLAB. The 'ComplexFormat',{'r','i'} option is a no-op for real
        # input, which is why the MATLAB file holds H5T_FLOAT and not a
        # {r,i} compound -- this pipeline's input is magnitude data.
        _easyh5_dataset(hf, "kspace_acq1", kspace_acq1)
        _easyh5_dataset(hf, "kspace_acq2", kspace_acq2)
        _easyh5_dataset(hf, "kspace_acq3", kspace_acq3)
        _easyh5_dataset(hf, "kspace_acq4", kspace_acq4)
        _easyh5_dataset(hf, "kspace_acq5", kspace_acq5)

        # h5create/h5write in the .m: dimension order reversed on disk.
        _matlab_dataset(hf, "reconstruction_t1", T1_map)
        _matlab_dataset(hf, "reconstruction_t2", T2_map)
        _matlab_dataset(hf, "reconstruction_pd", PD_map)
        _matlab_dataset(hf, "reconstruction_ie", IE_map)
        _matlab_dataset(hf, "reconstruction_b1", B1_map)

        # mask(:,1) is a [Ny,1] MATLAB column vector -> (1,Ny) on disk.
        mask_col = mask[:, 0:1]
        for i in range(1, 6):
            _matlab_dataset(hf, f"mask_acq{i}", mask_col)

        _matlab_dataset(hf, "mask_brain", bmask)

        # norm_*/max_* come from single arrays in the .m -> single attributes.
        # Keep np.linalg.norm on the float32 array: it accumulates in float32
        # and reproduced MATLAB's norm() exactly in the file comparison.
        _num_attr(hf, "norm_t1", np.linalg.norm(T1_map.ravel()), np.float32)
        _num_attr(hf, "max_t1", np.max(T1_map), np.float32)
        _num_attr(hf, "norm_t2", np.linalg.norm(T2_map.ravel()), np.float32)
        _num_attr(hf, "max_t2", np.max(T2_map), np.float32)
        _num_attr(hf, "norm_pd", np.linalg.norm(PD_map.ravel()), np.float32)
        _num_attr(hf, "max_pd", np.max(PD_map), np.float32)
        _num_attr(hf, "norm_ie", np.linalg.norm(IE_map.ravel()), np.float32)
        _num_attr(hf, "max_ie", np.max(IE_map), np.float32)
        _num_attr(hf, "norm_b1", np.linalg.norm(B1_map.ravel()), np.float32)
        _num_attr(hf, "max_b1", np.max(B1_map), np.float32)
        _str_attr(hf, "patient_id", att_patient)
        _str_attr(hf, "acquisition", att_seq)

        # Metadata describing the parameters of the 3D-QALAS sequence. For
        # now this assumes a fixed sequence per vendor -> hardcoded.
        for key in (
            "scan_flip_ang",
            "scan_tf",
            "scan_esp",
            "scan_t2_prep",
            "scan_gap_bw_ro",
            "scan_tr",
            "scan_time_relax_end",
            "scan_echo2use",
            "scan_crusher_after_T2prep",
            "scan_inv_pulse",
            "scan_gap_inv_readout",
        ):
            _num_attr(hf, key, scan_params[key], np.float64)
        _str_attr(hf, "scan_manufacturer", att_manufacturer)

        # Attributes for the image size restoration (zRange + original_size
        # are read back by h5_to_maps.py).
        hf.attrs.create("xRange", xRange.astype(np.float64))
        hf.attrs.create("yRange", yRange.astype(np.float64))
        hf.attrs.create("zRange", zRange.astype(np.float64))
        hf.attrs.create("original_size", original_size.astype(np.float64))

        # ---- Additional information about the sequence (ISMRMRD header) ----
        _write_ismrmrd_header(hf, _ismrmrd_header_xml(Nx, Ny, Nz))

    shutil.copyfile(file_name, file_name_val)

    print("done")


if __name__ == "__main__":
    if len(sys.argv) != 6:
        sys.exit(
            "Usage: python3 ssl_qalas_save_h5.py <sub_ses> <f_QALAS> <f_fmap> <dir_bids> <dir_tool>"
        )
    save_h5(*sys.argv[1:6])
