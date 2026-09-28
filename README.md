# SSL-QALAS-crossvendor (version 2.0.0)

![SSL-QALAS](figure/SSL-QALAS.jpg?raw=true "SSL-QALAS")

SSL-QALAS-crossvendor turns raw **3D-QALAS** and **B1 map** NIfTI files into quantitative **T1, T2, PD and IE maps**. It works with data from different MRI vendors and takes care of the vendor differences for you (sequence timing, and the B1 mapping method: AFI on GE and Philips, TFL on Siemens).

It is a wrapper around the original [SSL-QALAS](https://github.com/yohan-jun/SSL-QALAS) code ([Jun et al., Magnetic Resonance in Medicine, 2023](https://doi.org/10.1002/mrm.29786)), which is itself based on [fastMRI](https://github.com/facebookresearch/fastMRI). Version 1.0.0 of this tool is used in the [HBCD](https://hbcdstudy.org) study.

You do not need to know Python to use it: you edit a few paths in two scripts, make a list of sessions, and start one command. Everything else runs automatically on your computing cluster.

---

## Contents

- [What's new in 2.0.0](#whats-new-in-200)
- [Words used in this README](#words-used-in-this-readme)
- [Quick start](#quick-start)
- [Requirements](#requirements)
- [Installation](#installation)
- [One-time setup](#one-time-setup)
- [Input data (BIDS naming)](#input-data-bids-naming)
- [Step 1: process one participant from each scanner first](#step-1-process-one-participant-from-each-scanner-first)
- [Step 2: process all remaining sessions](#step-2-process-all-remaining-sessions)
- [Choosing a B1 map yourself (`exceptions_manual_run_ssl.sh`)](#choosing-a-b1-map-yourself-exceptions_manual_run_sslsh)
- [Processing without a B1 map](#processing-without-a-b1-map)
- [Processing on a GPU](#processing-on-a-gpu)
- [What happens inside each job](#what-happens-inside-each-job)
- [Output](#output)
- [Checking progress and re-running failed sessions](#checking-progress-and-re-running-failed-sessions)
- [Folders created by the tool](#folders-created-by-the-tool)
- [Supported vendors](#supported-vendors)
- [Troubleshooting](#troubleshooting)
- [Adapting the pipeline](#adapting-the-pipeline)
- [Future work](#future-work)
- [Citation](#citation)

---

## What's new in 2.0.0

- **No MATLAB needed.** The data conversion steps are now pure Python (`main_data/ssl_qalas_save_h5.py`, `main_data/h5_to_maps.py`). The folder formerly called `matlab/` is now `main_data/`.
- **Built-in skull-stripping** with FreeSurfer's SynthStrip (see [What happens inside each job](#what-happens-inside-each-job)).
- **Scanner-specific baseline weights.** The first session from each scanner is trained from scratch; every later session from the same scanner starts from those weights and trains much shorter. See [Step 1](#step-1-process-one-participant-from-each-scanner-first).
- **Processing without a B1 map** (`no_b1_map` option, not recommended).
- **GPU processing** is documented step by step.
- **Safer training/inference.** A job now stops with a clear error message instead of producing empty (NaN) maps when training did not save a result.
- **Canon support is prepared but not yet active** (see [Supported vendors](#supported-vendors)).

---

## Words used in this README

- **Session**: one scanning visit of one participant, i.e. a `sub-*/ses-*` folder in BIDS.
- **Run**: one 3D-QALAS acquisition within a session (`run-1`, `run-2`, ...). Each run is processed as one job.
- **Job**: a task sent to the cluster with Slurm (`sbatch`). You can see your jobs with `squeue -u $USER`.
- **Weights / checkpoint**: the trained network saved to a file (`.ckpt`). SSL-QALAS trains a small network for every run; the checkpoint is the result of that training.
- **Log file**: a text file in `logs/` with everything a job printed. It also works as a "lock": a run that already has a log file is not submitted again.

---

## Quick start

```bash
# 1. Install (only once)
conda env create -f environment.yml
conda activate ssl_qalas_crossvendor
pip install -e .

# 2. One-time setup: edit the paths in run_ssl.sh (lines 18-25)
#    and your Slurm account in submit_CPU.sh (line 8)

# 3. Make a list of all sessions to process
dir_tool=/path/to/SSL-QALAS-crossvendor   # same paths as in run_ssl.sh
dir_bids=/path/to/bids
mkdir -p $dir_tool/lists
cd $dir_bids
ls sub-*/ses-*/anat/*QALAS*nii* | cut -d"/" -f1-2 | sort | uniq > $dir_tool/lists/sub_ses_list.txt

# 4. IMPORTANT: first process ONE session per scanner and wait until it finishes
#    (see "Step 1" below)

# 5. Then process everything else
cd $dir_tool
source run_ssl.sh
```

> [!IMPORTANT]
> **Process one participant from each scanner first, and wait until those jobs are finished before processing the rest.** This first run estimates the baseline weights for that scanner, which all later sessions from the same scanner start from. See [Step 1](#step-1-process-one-participant-from-each-scanner-first).

---

## Requirements

- A Linux computing cluster with the [Slurm](https://slurm.schedmd.com/) job scheduler (`sbatch`).
- [Conda](https://docs.conda.io/) (Miniconda or Anaconda) for the Python environment.
- `jq` (a small tool for reading JSON files; usually already installed).
- [FreeSurfer](https://surfer.nmr.mgh.harvard.edu/) **7.3.0 or newer**, which includes `mri_synthstrip`. This repository does not include any FreeSurfer code, license or model weights; you use your own FreeSurfer installation.
- Optional: a GPU node, see [Processing on a GPU](#processing-on-a-gpu).

The pipeline has been tested with Miniconda3 and Anaconda3.

---

## Installation

You only need to do this once, before using the tool for the first time. In a terminal, go to the tool folder and run:

```bash
conda env create -f environment.yml
conda activate ssl_qalas_crossvendor
pip install -e .
```

Note: this environment is different from the one in the original SSL-QALAS repository. If your cluster has no internet access, see [Troubleshooting](#troubleshooting).

---

## One-time setup

Open these files in a text editor and fill in your own values. You only have to do this once.

| File | Lines | What to set |
|---|---|---|
| `run_ssl.sh` | 18-25 | Paths to the tool, your session list, your BIDS folder, output folders, Conda and FreeSurfer, and the `no_b1_map` option |
| `submit_CPU.sh` | 8 | Your Slurm account: replace `---` with your project/allocation name |
| `submit_CPU.sh` | 4-6 | (Optional) time limit, memory and number of CPUs per job |
| `exceptions_manual_run_ssl.sh` | 19-23 | Same paths as in `run_ssl.sh` (only if you use this script) |
| `post_fix_failed_logs.sh` | 12-14 | Same paths as in `run_ssl.sh` (only if you use this script) |

The settings in `run_ssl.sh` look like this:

```bash
dir_tool='/path/to/SSL-QALAS-main-crossvendor'   # Folder where SSL-QALAS-crossvendor is stored
sub_ses_list=$dir_tool'/lists/sub_ses_list.txt'  # List of sessions to process, one "sub-*/ses-*" per line
dir_bids='/path/to/bids'                         # Your BIDS folder
afi_out=$dir_tool'/afi_b1_maps'                  # Where estimated AFI B1 maps are saved (if applicable)
sum_out=$dir_tool'/overview'                     # Where summaries are saved
dir_conda='/path/to/conda'                       # Path to (mini)conda, or to a standalone environment folder
dir_freesurfer='/path/to/freesurfer'             # Path to your FreeSurfer installation
no_b1_map=0                                      # Keep at 0 unless no B1 maps were acquired at all
```

> [!TIP]
> **Finding your FreeSurfer path.** If FreeSurfer is available as a module on your cluster, run `module load FreeSurfer` (the exact name may differ, see `module avail FreeSurfer`) and then `echo $FREESURFER_HOME`. Use the printed path for `dir_freesurfer`.

---

## Input data (BIDS naming)

Your data should be organized in [BIDS](https://bids.neuroimaging.io/) with these file names:

```
anat/
    sub-*_ses-*_*_run-*_inv-[0-4]_QALAS.[nii.gz;json]          # 3D-QALAS, one NIfTI file per inversion (ungrouped)
    sub-*_ses-*_*_run-*_QALAS.[nii.gz;json]                    # 3D-QALAS, all inversions in one NIfTI file (nested)
fmap/
    sub-*_ses-*_*_acq-tr[1;2]_run-*_TB1AFI.[nii.gz;json]       # Raw AFI B1 maps (GE, Philips)
    sub-*_ses-*_*_acq-[anat;famp]_run-*_TB1TFL.[nii.gz;json]   # TFL B1 maps (Siemens): acq-famp is used for processing, acq-anat for coregistration
    sub-*_ses-*_*_run-*_part-[mag;phase]_TB1TFL.[nii.gz;json]  # TFL B1 maps (alternative naming): part-phase is used for processing, part-mag for coregistration
```

The JSON sidecar files are required: the tool reads the vendor, sequence timing and scanner serial number from them.

---

## Step 1: process one participant from each scanner first

> [!IMPORTANT]
> Before processing a whole dataset, **process one session from each scanner once and wait until it has finished.**

**Why?** The first time the tool sees data from a scanner, it trains the network from scratch (500 epochs) and saves the result as the **baseline weights** for that scanner. Scanners are recognized by the `DeviceSerialNumber` in the 3D-QALAS JSON file. Every later session from the same scanner starts from these baseline weights and only needs a short training (100 epochs), which is much faster.

If you submit all sessions at once instead, none of the jobs can find baseline weights (they don't exist yet), so **every** job trains from scratch. That takes much longer, and the scanner-specific baseline is not used.

**How to do it:**

1. Make an overview of which session was acquired on which scanner (run this in a terminal, using the same paths as in `run_ssl.sh`):

   ```bash
   dir_tool=/path/to/SSL-QALAS-crossvendor
   dir_bids=/path/to/bids
   cd $dir_bids
   while read -r s; do
     j=$(ls $s/anat/*QALAS.json 2>/dev/null | head -n 1)
     [ -n "$j" ] && echo "$(jq -r '.DeviceSerialNumber' "$j") $s"
   done < $dir_tool/lists/sub_ses_list.txt | sort > $dir_tool/lists/scanner_overview.txt
   ```

   Each line of `scanner_overview.txt` shows a scanner serial number and a session. `null` means the JSON has no serial number (see "Good to know" below).

2. Pick one session per scanner. This command picks the first one for each scanner automatically:

   ```bash
   sort -k1,1 -u $dir_tool/lists/scanner_overview.txt | cut -d" " -f2 > $dir_tool/lists/baseline_list.txt
   ```

   You can also open `baseline_list.txt` and replace a session by hand. Because the baseline is the starting point for all other sessions from that scanner, we recommend choosing a session with good image quality.

3. In `run_ssl.sh`, line 19, point `sub_ses_list` to the new list:

   ```bash
   sub_ses_list=$dir_tool'/lists/baseline_list.txt'
   ```

4. Start the processing:

   ```bash
   cd $dir_tool
   source run_ssl.sh
   ```

5. Wait until all jobs have finished (`squeue -u $USER` shows no more `SSL_QALAS` jobs). Then check that there is one folder per scanner here:

   ```bash
   ls $dir_tool/qalas_log/scanner_checkpoints/
   ```

   The folders are named after the scanner's serial number (for example `DeviceSerialNumber12345`).

Now continue with [Step 2](#step-2-process-all-remaining-sessions).

Good to know:

- If you later add data from a **new scanner**, repeat Step 1 for that scanner only.
- To **redo the baseline** for a scanner, delete its folder in `qalas_log/scanner_checkpoints/`. The next session from that scanner will be trained from scratch again and becomes the new baseline.
- If a session's JSON has no `DeviceSerialNumber`, that session is always trained from scratch and no baseline is saved (a warning is printed in its log file).
- The number of epochs can be changed in `submit_CPU.sh`, lines 75-77.

---

## Step 2: process all remaining sessions

In `run_ssl.sh`, line 19, point `sub_ses_list` back to the full list (`sub_ses_list.txt`) and run:

```bash
cd $dir_tool
source run_ssl.sh
```

Sessions that were already submitted in Step 1 are skipped automatically (they already have a log file). You can follow the jobs with `squeue -u $USER` and in the log files in `$dir_tool/logs/`.

**How the tool pairs each 3D-QALAS run with a B1 map.** Before submitting a job, `run_ssl.sh` estimates the AFI B1 map (if applicable), finds the right B1 map for each 3D-QALAS run and aligns (coregisters) it to the 3D-QALAS images. The pairing follows this order:

1. **Only one possible pair.** If there is exactly one 3D-QALAS and one B1 map, they belong together.
2. **Unique shim setting.** If a B1 map and a 3D-QALAS have the same `ShimSetting` in their JSON files (not "null"), and no other B1 map has that shim setting, they are paired.
3. **Same run number.** If the shim information is missing or not unique, the run numbers are compared (e.g. `run-2` with `run-2`), as long as the runs were saved in the order they were acquired.
4. **No clear match.** Otherwise the pair is written to `overview/no_clear_match.txt` for you to check by hand. You can then process it with [`exceptions_manual_run_ssl.sh`](#choosing-a-b1-map-yourself-exceptions_manual_run_sslsh).

At the end, the script prints the sessions it could not match. You can also look at them later with:

```bash
cat "$sum_out/no_clear_match.txt" | cut -d"/" -f1-2 | sort | uniq
```

The files in `overview/` are a simple summary and are not yet complete, so use them as a guide only.

---

## Choosing a B1 map yourself (`exceptions_manual_run_ssl.sh`)

Use this when the automatic pairing did not work, or when you want to choose the pair yourself. It skips the pairing checks and processes exactly the pair you give it.

1. Fill in the paths in lines 19-23 (the same as in `run_ssl.sh`).
2. Write the two file names (only the names, not the full paths) in lines 15-16:

   ```bash
   f_QALAS="sub-*_ses-*_run-?_inv-0_QALAS.nii.gz"   # use inv-0 for ungrouped 3D-QALAS files
   f_fmap="sub-*_ses-*_acq-tr1_run-?_TB1AFI.nii.gz" # use acq-tr1 for AFI; acq-famp for TFL
   ```

3. Run it:

   ```bash
   cd $dir_tool
   source exceptions_manual_run_ssl.sh
   ```

The subject and session are read from the file names. The script estimates the AFI B1 map (if applicable), coregisters the B1 map and submits one job. As with `run_ssl.sh`, a run that already has a log file is not submitted again.

---

## Processing without a B1 map

If **no B1 maps were acquired at all** for your dataset, set `no_b1_map=1` in `run_ssl.sh` (line 25). The tool then skips everything related to B1 maps and uses a uniform B1 value of 1.0 for every 3D-QALAS run.

Only use this when there really is no B1 map: B1 correction is part of the T1/T2 estimation, so maps without it are expected to be less accurate, especially where the B1 field is uneven. For normal processing, keep `no_b1_map=0`.

---

## Processing on a GPU

By default everything runs on the CPU, so the tool works on any cluster. If you have access to GPU nodes, processing can run on a GPU instead, which is especially helpful for the long from-scratch runs in [Step 1](#step-1-process-one-participant-from-each-scanner-first). Three files need a small edit:

**1. `submit_CPU.sh`: ask Slurm for a GPU.** Add two lines to the `#SBATCH` block at the top (lines 3-8), for example right after line 8:

```bash
#SBATCH --partition=<your-gpu-partition>   # name of the GPU partition on your cluster
#SBATCH --gres=gpu:1                       # ask for one GPU
```

Partition names and the exact GPU option differ between clusters, so check your cluster's documentation.

**2. `train_qalas.py`, line 88: train on the GPU.** Change

```python
trainer = pl.Trainer.from_argparse_args(args, accelerator="cpu", log_every_n_steps=1)
```

to

```python
trainer = pl.Trainer.from_argparse_args(args, accelerator="gpu", gpus=1, log_every_n_steps=1)
```

Don't use the commented-out line 87 instead: with the PyTorch Lightning version in this environment (1.5.10), it fails because of the default `backend = "cuda"` on line 115.

**3. `inference_qalas_map.py`, line 145: make the maps on the GPU.** Change `default="cpu"` to `default="cuda"`.

That's all. You don't need to load a CUDA module: the PyTorch package brings what it needs, and the GPU node only needs its normal NVIDIA driver. To check that the GPU is really used, look for this line in the job's log file:

```
GPU available: True, used: True
```

Weights are always loaded onto the CPU first (`train_qalas.py` line 92, `inference_qalas_map.py` line 73), so checkpoints and scanner baselines made on a GPU can be used on the CPU and the other way around. The job script keeps the name `submit_CPU.sh`; if you rename it, also update the `sbatch` lines in `run_ssl.sh` (lines 152 and 168) and `exceptions_manual_run_ssl.sh` (line 84). To go back to the CPU, undo the three edits.

> [!NOTE]
> The environment installs PyTorch 1.11.0 built for CUDA 10.2. This works on older GPUs (for example V100, T4, RTX 20xx). On newer GPUs such as the A100, you will see an error saying the GPU's "CUDA capability sm_80 is not compatible with the current PyTorch installation". In that case, install the CUDA 11.3 build into the environment:
>
> ```bash
> conda activate ssl_qalas_crossvendor
> pip install torch==1.11.0+cu113 torchvision==0.12.0+cu113 torchaudio==0.11.0 --extra-index-url https://download.pytorch.org/whl/cu113
> ```
>
> Very recent GPUs (for example H100) may not be supported by PyTorch 1.11 at all.

---

## What happens inside each job

Each job runs `submit_CPU.sh` for one 3D-QALAS run. You don't need to start it yourself: `run_ssl.sh` and `exceptions_manual_run_ssl.sh` submit it for you. It does the following:

1. **Skull-stripping.** FreeSurfer's `mri_synthstrip` makes a brain mask from the third 3D-QALAS contrast (`inv-2`). The mask is saved in `$dir_tool/synthstrip_mask/`. If a mask already exists, it is reused, so to redo the mask, delete it first. The option `-b 2` sets the border of the mask to 2 mm around the brain.
2. **Training**, in one of three ways:
   - **Scanner baseline exists** → the data is converted to h5 (`ssl_qalas_save_h5.py`), and training starts from the scanner's baseline weights for 100 epochs.
   - **An earlier, interrupted run of this same session exists** → training continues from where it stopped, for 100 more epochs.
   - **Nothing exists yet** → the data is converted to h5, and training starts from scratch for 500 epochs.
3. **Making the maps.** `inference_qalas_map.py` uses the checkpoint with the lowest validation loss to produce the maps. If training did not save a checkpoint, the job stops with an error message instead.
4. **Archiving.** The checkpoint and a copy of the 3D-QALAS JSON are stored in `old/` inside the run's folder in `$dir_tool/qalas_log/`. Archived checkpoints are not used if the run is processed again.
5. **Saving the maps as NIfTI.** `h5_to_maps.py` writes the final maps to `$dir_tool/main_data/maps/`.
6. **Saving the scanner baseline.** If this scanner has no baseline weights yet, this run's checkpoint is copied to `$dir_tool/qalas_log/scanner_checkpoints/`.

---

## Output

The maps are saved in `$dir_tool/main_data/maps/sub-*/ses-*/anat/`:

- `sub-*_ses-*_run-*_T1map.nii.gz`: T1 map
- `sub-*_ses-*_run-*_T2map.nii.gz`: T2 map
- `sub-*_ses-*_run-*_PDmap.nii.gz`: proton density (PD) map
- `sub-*_ses-*_run-*_IEmap.nii.gz`: inversion efficiency (IE) map

The maps are saved in the space of the original 3D-QALAS image, so you can view them on top of it in any NIfTI viewer (for example FreeSurfer's `freeview`). It's a good idea to look at the first maps from each scanner before processing a large dataset.

---

## Checking progress and re-running failed sessions

- **See running jobs:** `squeue -u $USER`
- **See what a job did:** open its log file in `$dir_tool/logs/` (one log per 3D-QALAS run).

Because log files work as locks, a run is never submitted twice, including runs that failed. To re-run failed runs, use `post_fix_failed_logs.sh`. It goes through your session list, finds the runs that were not completed, and deletes their log files so they can be submitted again.

> [!WARNING]
> Only run `post_fix_failed_logs.sh` **after all submitted jobs have finished**. Otherwise it also deletes the log files of jobs that are still running.

1. Fill in the paths in lines 12-14 (the same as in `run_ssl.sh`).
2. Run it, then run `run_ssl.sh` again:

   ```bash
   cd $dir_tool
   source post_fix_failed_logs.sh
   source run_ssl.sh
   ```

If a job was stopped because it ran out of time, the re-run does not start from zero: it starts again from the scanner's baseline weights (100 epochs), or, if the stopped job was itself a baseline run, continues from its own last checkpoint.

---

## Folders created by the tool

All of these are created inside `$dir_tool`:

| Folder | Contents |
|---|---|
| `main_data/maps/` | **Your results:** the final T1, T2, PD and IE maps |
| `logs/` | One log file per 3D-QALAS run (also used as a lock) |
| `overview/` | Summaries of submitted and unmatched pairs |
| `synthstrip_mask/` | Brain masks from SynthStrip |
| `afi_b1_maps/` | B1 maps estimated from AFI data (GE, Philips) |
| `coreg_b1_maps/` | B1 maps aligned to the 3D-QALAS images |
| `main_data/h5_data/` | Intermediate files used for training |
| `qalas_log/` | Training checkpoints for each run (archived in `old/`) |
| `qalas_log/scanner_checkpoints/` | Baseline weights, one folder per scanner |

---

## Supported vendors

| Vendor | B1 map | Status |
|---|---|---|
| Siemens | TFL (`TB1TFL`) | Supported |
| GE | AFI (`TB1AFI`) | Supported |
| Philips | AFI (`TB1AFI`) | Supported |
| Canon | - | Prepared, not yet active |

The vendor is read from the `Manufacturer` field in the JSON file. The sequence timing for each vendor is set in `main_data/ssl_qalas_save_h5.py` (lines 265-357) and assumes that nothing except the resolution was changed in the standard 3D-QALAS protocol.

For **Canon**, the timing values are still empty (lines 336-348). Canon data stops with a clear error message until they are filled in. The image orientation for Canon has also not been checked yet, so compare the first Canon maps with the original images.

---

## Troubleshooting

- **No internet on the cluster (air-gapped systems).** Create the environment on another computer and move it over with [conda-pack](https://conda.github.io/conda-pack/). You can use the unpacked environment with or without adding it to Conda.
- **Using a standalone environment outside Conda.** Place the unpacked environment folder next to the tool and set `dir_conda` to that folder instead of to Conda.
- **`conda-unpack: command not found` in the output.** This is harmless if you installed the environment normally with Conda (the command is only needed for conda-pack environments).
- **Your terminal closes right after `source run_ssl.sh`.** One of the required commands (`jq`, `python3`, `sbatch`, `conda`) was not found. Check with `which jq python3 sbatch conda`, or run `bash run_ssl.sh` to see the error message.
- **Unexpected package versions.** Packages installed in your home folder can override the environment. Turn this off with `export PYTHONNOUSERSITE=1` (you can add this line to the environment's activation script).
- **Error: "A module that was compiled using NumPy 1.x cannot be run in NumPy 2..."** The tool needs NumPy 1.x. Run `conda activate ssl_qalas_crossvendor` and then `pip install "numpy<2"`.
- **A job stops with "training wrote no checkpoint".** Training did not finish properly. Look higher up in the log file for the first error message.

---

## Adapting the pipeline

Some things you can change yourself:

- **Output names.** The file names and folder of the maps are set in `main_data/h5_to_maps.py`, lines 111-117. JSON sidecar files describing the maps can be added there too.
- **Modified 3D-QALAS protocol or another vendor.** Update or add the sequence timing in `main_data/ssl_qalas_save_h5.py`, lines 265-357.
- **Different AFI settings.** The AFI B1 estimation assumes a nominal flip angle of 60° and a TR ratio of 5 (`calculate_afi_b1.py`, line 9). Change these if your AFI protocol is different.
- **Training length.** Set the number of epochs in `submit_CPU.sh`, lines 75-77.
- **Config files.** Instead of editing the scripts, you can make `run_ssl.sh` (lines 18-25) and `exceptions_manual_run_ssl.sh` (lines 15-23) read an external config file, which avoids accidental changes to the code.
- **Lock files.** Log files also work as lock files. This can be changed in `run_ssl.sh` (lines 146 and 165).

---

## Future work

- Estimate the AFI B1 map only when it is actually used (it is currently estimated for every candidate).
- Accept DICOM input and read the metadata from the DICOM headers.
- Stop processing cleanly after an error.
- Remove randomness from the B1 map coregistration.
- Add sanity checks to `exceptions_manual_run_ssl.sh`.
- Allow more than one 3D-QALAS/B1 map combination per run in the log (lock) files, e.g. to compare combinations.
- Support more flexible BIDS naming.
- Make the summaries in `overview/` more complete.
- Fill in and validate the Canon timing and orientation.

---

## Citation

If you have questions, comments or suggestions, please contact yjun@mgh.harvard.edu or maksimsl@uio.no.

If you use this code, please cite the SSL-QALAS paper:

```BibTeX
@article{jun2023SSL-QALAS,
  title={{SSL-QALAS}: Self-Supervised Learning for rapid multiparameter estimation in quantitative {MRI} using {3D-QALAS}},
  author={Jun, Yohan and Cho, Jaejin and Wang, Xiaoqing and Gee, Michael and Grant, P. Ellen and Bilgic, Berkin and Gagoski, Borjan},
  journal={Magnetic Resonance in Medicine},
  volume={90},
  number={5},
  pages={2019--2032},
  year={2023},
  doi={10.1002/mrm.29786}
}
```

The paper describing the cross-vendor processing is coming soon.

The skull-stripping uses SynthStrip, so please also cite:

```BibTeX
@article{hoopes2022synthstrip,
  title={{SynthStrip}: Skull-stripping for any brain image},
  author={Hoopes, Andrew and Mora, Jocelyn S. and Dalca, Adrian V. and Fischl, Bruce and Hoffmann, Malte},
  journal={NeuroImage},
  volume={260},
  pages={119474},
  year={2022},
  doi={10.1016/j.neuroimage.2022.119474}
}
```

If you use AFI B1 maps (GE, Philips) and the actual flip angle estimation, please cite:

```BibTeX
@article{yarnykh2007afi,
  title={Actual flip-angle imaging in the pulsed steady state: A method for rapid three-dimensional mapping of the transmitted radiofrequency field},
  author={Yarnykh, Vasily L.},
  journal={Magnetic Resonance in Medicine},
  volume={57},
  number={1},
  pages={192--200},
  year={2007},
  doi={10.1002/mrm.21120}
}
```
