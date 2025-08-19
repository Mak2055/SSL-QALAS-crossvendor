# SSL-QALAS: Self-Supervised Learning for Rapid Multiparameter Estimation in Quantitative MRI Using 3D-QALAS

![Alt text](figure/SSL-QALAS.jpg?raw=true "SSL-QALAS")


This is the wrapper script for **"SSL-QALAS: Self-Supervised Learning for Rapid Multiparameter Estimation in Quantitative MRI Using 3D-QALAS"**.

The original SSL-QALAS paper is published at [Magnetic Resonance in Medicine](https://doi.org/10.1002/mrm.29786).

The baseline code is based on fastMRI code, which is forked from [here](https://github.com/facebookresearch/fastMRI).

## Description
This wrapper uses the SSL-QALAS scripts (https://github.com/yohan-jun/SSL-QALAS) and builds uppon them:
  - BIDS-compliant processing of NIfTI 3D-QALAS and the corresponding B1 maps into the parametric map.
  - Added multivendor processing: the script looks into the corresponding .json files to choose the appropriate processing parameters (based on the vendor, assuming no modifications beyond resolution were made to the sequence ).
  - Added estimation of the actual AFI B1 maps from the 2-echo raw images.
  - Added B1 maps coregistration with 3D-QALAS images as described [here](https://pubmed.ncbi.nlm.nih.gov/17191242/).
  - Simple and straightforward usage with the possibility for automated and manual selection of 3D-QALAS and B1 map pairs.
  - CPU instead of GPU processing.
  - Automatic converting of the parametric maps from h5 to NIfTI format (see [Modifications and future work](#modifications-and-future-work) for possible modifications).
  - Output of the processing summary.

## Requirements
- [Conda](https://docs.conda.io/) for managing Python environments
- [MATLAB](https://www.mathworks.com/) for input and output handling
- [Slurm](https://slurm.schedmd.com/) workload manager for job submission on HPC clusters

No minimal requirements are known, the pipeline has been tested with miniconda3, anaconda3 and MATLAB 2023a.

## Installation
For dependencies and installation, please follow below:

```bash
conda env create -f environment.yml
conda activate ssl_qalas_crossvendor
pip install -e .
```

Note: the envoronment is different than the one in the original SSL-QALAS repository 

## General idea
This is the general idea of this README with straightforward references to chapters:
- If your goal is to process a batch of sessions at once use [`run_ssl.sh`](#processing-with-run_sslsh).
- If you want to manually match B1 map and 3D-QALAS pairs use [`exceptions_manual_run_ssl.sh`](#processing-with-exceptions_manual_run_sslsh).
- Whichever method you choose, you will either get the [output](#output) or run [`post_fix_failed_logs.sh`](#clean-up-with-post_fix_failed_logssh) to clean up, fix bugs and re-run the processing.

## BIDS standard assumprions for running SSL-QALAS-crossvendor
Your input data should be BIDS-complant with the following naming logic:

```
anat/
    sub-*_ses-*_*_run-*_inv-[0-4]_QALAS.[nii.gz;json]          # For ungrouped 3D-QALAS images, where each inverse is a separate NIfTI file
    sub-*_ses-*_*_run-*_QALAS.[nii.gz;json]                    # For nested 3D-QALAS images, where all inverses aree concatinated in one NIfTI file
fmap/
    sub-*_ses-*_*_acq-tr[1,2]_run-*_TB1AFI.[nii.gz;json]       # For raw AFI B1 maps
    sub-*_ses-*_*_acq-[anat,famp]_run-*_TB1TFL.[nii.gz;json]   # For TFL B1 maps, acq-famp is used for processing, acq-anat is used for coregistration
    sub-*_ses-*_*_run-*_part-[mag;phase]_TB1TFL.[nii.gz;json]  # For TFL B1 maps (alternative), acq-phase is used for processing, part-mag is used for coregistration
```

## Processing with `run_ssl.sh`
Executing `run_ssl.sh` allows for automated processing of multiple sessions that contain 3D-QALAS runs. For this, paths have to be provided to various files and directories:

```
dir_tool='/path/to/SSL-QALAS-main-crossvendor'   # Path to the folder where SSL-QALAS-crossvendor is stored
sub_ses_list=$dir_tool'/lists/sub_ses_list.txt'  # Path to the list of sessions to process (each entry should be a BIDS-compliant name, i.e. "sub-\*/ses-\*") - can be saved within the tool folder
dir_bids='/path/to/bids'                         # Path to BIDS where all the participants to be processed are stored
afi_out=$dir_tool'/afi_b1_maps'                  # Path to the folder where estimated AFI maps should be saved (if applicable) - can be saved within the tool folder
sum_out=$dir_tool'/overview'                     # Path to the folder where general summaries are stored - can be saved within the tool folder
dir_conda='/path/to/conda'                       # Path to (mini)conda on your machine
dir_matlab='/path/to/MATLAB'                     # Path to MATLAB on your machine
lic_matlab=''                                    # Leave empty if the licence is provided in MATLAB folder (most likely scenario), otherwise provide the license file or the license server
```

To run the script processing create a list of participants that you want to process. The easiest way of doing that may be:

```bash
cd $dir_bids
ls sub-*/ses-*/anat/*QALAS*nii.gz | cut -d"/" -f1-2 | sort | uniq > $sub_ses_list
```

Once this is done `run_ssl.sh` can be executed:

```bash
cd $dir_tool
source run_ssl.sh
```

The script is going to automatically pre-process all the provided sessions, except for those that already have a log file in `$dir_tool/logs`. Log files act like lock files in this workflow and have to be removed if a 3D-QALAS run should be reprocessed (see [Clean up with `post_fix_failed_logs.sh`](#clean-up-with-post_fix_failed_logssh)). The pre-processing includes the actual AFI B1 map estimation (if aplicable), the sanity check for B1 map and 3D-QALAS matching and images coregistration. The matching hierarchy is the following:
1) Only one possible pair exists
  - If there is exactly one 3D-QALAS and one B1 map then the script assumes they must belong together.
    → Run the pipeline with this pair.
2) Unique shim setting match
  - If both files contain ShimSetting values that are identical and
  - not "null" and shim settings across all B1 maps are not identical (so this one is unique), then
  - the script concludes the pair matches based on shim configuration.
    → Run the pipeline with this pair.
3) Run number match
  - If shim info is missing or not unique, but the run number (e.g. run-2) matches between 3D-QALAS and B1 map, and
  - no suspicious time difference was found (runs are saved in order of acquisition), then
  - the script uses run number as the matching criterion.
    → Run the pipeline with this pair.
4) No clear match
  - If none of the above conditions are satisfied,
  - the script cannot confidently match the files.
    → Append the unmatched pair into a log (`no_clear_match.txt`) for manual inspection.

The pipeline automatically submits `submit_CPU.sh` script to the cluster using Slurm. Each job processes one 3D-QALAS run. The processing can be tracked in `$dir_tool/logs`. 

## Processing with `exceptions_manual_run_ssl.sh`
The workflow in `exceptions_manual_run_ssl.sh` is analogous to that in `run_ssl.sh`, but it skips the sanity check for the matching, assuming that the user has provided an adequate pair. Here the user should not provide a list of sessions to process, but only the names of the selected NIfTI files, the code will extract the subject and session ID automatically:

```
f_QALAS="sub-*_ses-*_run-?_inv-0_QALAS.nii.gz"   # inv-0 for ungrouped 3D-QALAS NIfTI
f_fmap="sub-*_ses-*_acq-tr1_run-?_TB1AFI.nii.gz" # acq-tr1 for AFI; acq-famp for TFL
```

Furthermore, just like in `run_ssl.sh`, paths to different files and directories should be provided:

```
dir_tool='/path/to/SSL-QALAS-main-crossvendor'   # Path to the folder where SSL-QALAS-main-crossvendor is stored
dir_bids='/path/to/bids'                         # Path to BIDS where all the participants to be processed are stored
afi_out=$dir_tool'/afi_b1_maps'                  # Path to the folder where estimated AFI maps should be saved (if applicable) - can be within the tool folder
dir_conda='/path/to/conda'                       # Path to (mini)conda on your machine
dir_matlab='/path/to/MATLAB'                     # Path to MATLAB on your machine
lic_matlab=''                                    # Leave empty if the licence is provided in MATLAB folder (most likely scenario), otherwise provide the license file or the license server
```

Once this is done `run_ssl.sh` can be executed:

```bash
cd $dir_tool
source exceptions_manual_run_ssl.sh
```

The script is going to automatically pre-process the provided pair, unless it already has a log file in `$dir_tool/logs`. Log files act like lock files in this workflow and have to be removed if a 3D-QALAS run should be reprocessed (see [Clean up with `post_fix_failed_logs.sh`](#clean-up-with-post_fix_failed_logssh)). The pre-processing includes the actual AFI B1 map estimation (if aplicable) and B1 map coregistration with 3D-QALAS images. It automatically submits `submit_CPU.sh` script for processing the selected 3D-QALAS run to the cluster using Slurm. The processing can be tracked in `$dir_tool/logs`. 

## Workflow in `submit_CPU.sh`
The Slurm batch script `submit_CPU.sh` is designed to be submitted to the cluster, so it performs all the processing automatically. The processing has two possibilities: if a checkpoint for a given 3D-QALAS run exists (the 3D-QALAS processing has been interrupted previously) or if a checkpoint doesn't exist. 
- When a checkpoint doesn't exist, the processing starts anew. The pipeline executes:
  - `ssl_qalas_save_h5.m` that converts the 3D-QALAS and B1 maps as well as their metadata into the h5 format that is used for the main SSL-QALAS processing;
  - `train_qalas.py` that processes the data in the h5 file and estimates the parametric maps;
  - `inference_qalas_map.py` that produces the parametric maps from the checkpoint with the lowest validation loss;
  - moving the checkpoint to the archive folder `old/` within each run in `$dir_tool/qalas_log/`, that checkpoint won't be considered if re-processing of the rrun is needed;
  - 'h5_to_maps.m` that extracts the parametric maps from the h5 file and saves them as NIfTI files in `$dir_tool/matlab/maps`.
- When a checkpoint exists, the proceessing continues from the available checkpoint. The pipeline executes:
  - `train_qalas.py` that processes the data in the h5 file and estimates the parametric maps starting from the available checkpoint;
  - `inference_qalas_map.py` that produces the parametric maps from the checkpoint with the lowest validation loss;
  - moving the checkpoint to the archive folder `old/` within each run in `$dir_tool/qalas_log/`;
  - `h5_to_maps.m` that extracts the parametric maps from the h5 file and saves them as NIfTI files in `$dir_tool/matlab/maps`.

## Summary in `overview/`
Files in `overview/` keep track of what was and wasn't successfully submitted. They are not in a very comprehensive shape yet, but looking on the list of unmatched sessions durring execution of `run_ssl.sh` may be useful (it may not be reliable yet):

```bash
cat "$sum_out/no_clear_match.txt" | cut -d"/" -f1-2 | sort | uniq
```

## Output
Output is saved in `$dir_tool/matlab/maps/sub-*/ses-*/run-*/`, there
- `T1_map.nii` - T1 parametric map
- `T2_map.nii` - T2 parametric map
- `IE_map.nii` - Inversion Efficiency parametric map
- `PD_map.nii` - Proton Density parametric map

## Clean up with `post_fix_failed_logs.sh`
Currently log files act as lock files. This was done to avoid re-submitting the same processing twice before it was completed as well as preventing the re-submission of the processed participant in the future. That also means that in order to re-run processing of any participant, the corresponding log file has to be removed, which is handled by `post_fix_failed_logs.sh`. **The script should only be implemented after all the submitted SSL-QALAS jobs have been completed.** The only input required is:

```
dir_tool='/path/to/SSL-QALAS-main-crossvendor'   # Path to the folder where SSL-QALAS-crossvendor is stored
sub_ses_list=$dir_tool'/lists/sub_ses_list.txt'  # Path to the list of sessions to process (each entry should be a BIDS-compliant name, i.e. "sub-*/ses-*") - can be within the tool folder
dir_bids='/path/to/bids'                         # Path to BIDS where all the participants to be processed are stored
```

## Modifications and future work
There are possible modifications to the pipeline available to the user:
- The output can be BIDS-compliant. For this `h5_to_maps.m` has to be modified at the very end (l. 85-88) to fit your desired naming convention. JSON files may be added there to describe the parametric maps.
- Working with config files instead of in-script modifications is possible. This can ensure an accidental modification of the code. For this `run_ssl.sh` (l. 17-25) and `exceptions_manual_run_ssl.sh` (l. 15-25) can be modified to source an external config file instead.
- If modifications to the 3D-QALAS acquisition sequence were made, the parameters should be updated in `ssl_qalas_save_h5.m` (l. 275-323, according to the vendor). In the same part the parameters of any alternative vendor can be added .
- Currently the log files also act as lock files (see [Processing with `run_ssl.sh`](#processing-with-run_sslsh), [Processing with `exceptions_manual_run_ssl.sh`](#processing-with-exceptions_manual_run_sslsh) and [Clean up with `post_fix_failed_logs.sh`](#clean-up-with-post_fix_failed_logssh)). This is an imperfect practice that can be changed in `run_ssl.sh` (l. 144).

Some additional work can be done in the future to improve the experience and make the tool more flexible:
- Currently the actual AFI B1 map is being estimated despite if it was or wasn't used. The estimation may only be done if the B1 map passed the sanity check (see [Processing with `run_ssl.sh`](#processing-with-run_sslsh)).
- Currently only NIfTI images are accepted as input. Adding DICOM images as input with reading the metadata from DICOM headers is possible.
- Currently processing is happening on CPU, implementing processing on GPU is possible.
- Implementation of sanity checks in `exceptions_manual_run_ssl.sh` (comparing the subject and session IDs in the B1 map and 3D-QALAS) can be implemented.
- Currently only one combination of 3D-QALAS and B1 map is considered in log (lock) files, which may be an issue if a user wants to determine the optimal combination by actually running SSL-QALAS processing. Adding more flexibility to log file namings and output may be useful.
- Expanded or more fleexible input BIDS naming logic is possible.
- More comprehensive files in `overview/` are needed

## Cite
If you have any questions/comments/suggestions, please contact at yjun@mgh.harvard.edu or maksimsl@uio.no

If you use the SSL-QALAS code in your project, please cite the following paper:

```BibTeX
@article{jun2023SSL-QALAS,
  title={{SSL-QALAS}: Self-Supervised Learning for rapid multiparameter estimation in quantitative {MRI} using {3D-QALAS}},
  author={Jun, Yohan and Cho, Jaejin and Wang, Xiaoqing and Gee, Michael and Grant, P. Ellen and Bilgic, Berkin and Gagoski, Borjan},
  journal={Magnetic resonance in medicine},
  volume={90},
  number={5},
  pages={2019--2032},
  year={2023},
  publisher={Wiley Online Library}
}
```

If you use AFI B1 map and performed the actual B1 map estimation, please cite the following paper:

```BibTeX
@article{Yarnykh_2006, 
  title={Actual flip‐angle imaging in the pulsed steady state: A method for rapid three‐dimensional mapping of the transmitted radiofrequency field}, 
  volume={57}, DOI={10.1002/mrm.21120}, 
  number={1}, 
  journal={Magnetic Resonance in Medicine}, 
  author={Yarnykh, Vasily L.}, 
  year={2006}, 
  month={Dec}, 
  pages={192–200}
} 
```

