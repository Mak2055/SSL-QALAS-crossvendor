#!/bin/bash

#SBATCH --job-name=SSL_QALAS
#SBATCH --time=24:00:00
#SBATCH --mem-per-cpu=2G
#SBATCH --cpus-per-task=4
#SBATCH --ntasks=1
#SBATCH --account=---                    # Replace with your own Slurm billing/allocation account

##########################################################################################
#                                                                                        #
# submit_CPU.sh:                                                                         #
# This script is submitted to a cluster using slurm by run_ssl.sh. The goal is to        #
# completely process one 3D-QALAS run according to provided variables.                   #
#                                                                                        #
##########################################################################################


# === Read all the input variables ===
sub_ses="$1"
f_QALAS="$2"
f_fmap="$3"
dir_bids="$4"
dir_tool="$5"
dir_conda="$6"
dir_freesurfer="$7"

# === Source FreeSurfer ===
export FREESURFER_HOME=$dir_freesurfer
source $FREESURFER_HOME/SetUpFreeSurfer.sh

# === Activate the environment ===
source $dir_conda/bin/activate ssl_qalas_crossvendor

# === Construct the sub_ses_run and prepare the environment ===
sub_ses_run=${sub_ses}'/'$(echo $f_QALAS | grep -oP 'run-\d+(?=_)')

# === Check for B1+ map availability ===
# run_ssl.sh's no_b1_map=1 path submits jobs with f_fmap="NONE" when no B1+
# fieldmap was acquired/found for this session. Nothing else in this script
# needs to change for that case - skull-stripping is QALAS-image-based, not
# B1-map-based, so it proceeds exactly as usual below, and f_fmap is only
# ever consumed further down by ssl_qalas_save_h5.py, which recognizes the
# same sentinel and falls back to a uniform B1_map of 1.0 instead of trying
# to load a B1 map file. If a real B1 map filename was provided, this whole
# block is a no-op and behavior is unchanged.
if [ "$f_fmap" = "NONE" ]; then
    echo ''
    echo 'No B1+ map provided for this run (no_b1_map=1) - a uniform B1map of 1.0 will be used instead.'
fi

# === Skullstripping 3D-QALAS ===
if [ ! -f $dir_tool/synthstrip_mask/${f_QALAS//inv-0/inv-2} ]; then
    mkdir -p $dir_tool/synthstrip_mask
    NFRAMES=$($dir_freesurfer/bin/mri_info --nframes $dir_bids/$sub_ses/anat/${f_QALAS//inv-0/inv-2})
    if [ "$NFRAMES" -gt 1 ]; then
        echo "4D image detected. Extracting Frame 2..."
        $dir_freesurfer/bin/mri_convert $dir_bids/$sub_ses/anat/${f_QALAS//inv-0/inv-2} --frame 2 $dir_tool/synthstrip_mask/${f_QALAS//QALAS/QALAS_frame}
        $dir_freesurfer/bin/mri_synthstrip -i $dir_tool/synthstrip_mask/${f_QALAS//QALAS/QALAS_frame} -m $dir_tool/synthstrip_mask/${f_QALAS//inv-0/inv-2} -b 2
        rm $dir_tool/synthstrip_mask/${f_QALAS//QALAS/QALAS_frame}
    else
        $dir_freesurfer/bin/mri_synthstrip -i $dir_bids/$sub_ses/anat/${f_QALAS//inv-0/inv-2} -m $dir_tool/synthstrip_mask/${f_QALAS//inv-0/inv-2} -b 2
    fi
else
    echo ''
    echo 'A mask was detected and used:'
    ls $dir_tool/synthstrip_mask/${f_QALAS//inv-0/inv-2}
fi

cd $dir_tool

# === Training length ===
# Lightning's --max_epochs is an ABSOLUTE stopping point on the global epoch
# counter, not "this many more epochs". It therefore only means what it says
# when the epoch counter starts at 0, which is the case for a fresh run and
# for the weights-only warm start below. For a genuine resume of this run it
# has to be added to the epoch stored in the checkpoint (see epochs_after).
EPOCHS_FRESH=500        # brand-new run, nothing to start from
EPOCHS_WARMSTART=100    # starting from another session's weights for this scanner
EPOCHS_RESUME=100       # continuing an interrupted run of THIS session

# === Checkpoint helpers ===
newest_ckpt() {
    ls -t "$1"/epoch*.ckpt 2>/dev/null | head -n 1
}

# Absolute --max_epochs for a resume: the checkpoint's own epoch plus $2.
epochs_after() {
    python - "$1" "$2" <<'PY'
import sys, torch
try:
    # torch >= 2.6 defaults to weights_only=True, which cannot load a Lightning
    # checkpoint (it holds loop/callback state, not just tensors).
    ck = torch.load(sys.argv[1], map_location="cpu", weights_only=False)
except TypeError:
    ck = torch.load(sys.argv[1], map_location="cpu")   # torch < 1.13
print(int(ck.get("epoch", 0)) + int(sys.argv[2]))
PY
}

# === Check if the processing hasn't been completed previously for this scanner ===
DSN=$(cat "$dir_bids/$sub_ses/anat/${f_QALAS/\.nii*/.json}" | grep "DeviceSerialNumber" | tr -cd '[:alnum:]')

if [ -z "$DSN" ]; then
    echo "WARNING: no DeviceSerialNumber in ${f_QALAS/\.nii*/.json} -- scanner-specific weights are disabled for this run."
    SCANNER_CKPT_DIR=""
    SCANNER_CKPT=""
else
    SCANNER_CKPT_DIR="$dir_tool/qalas_log/scanner_checkpoints/$DSN"
    SCANNER_CKPT=$(newest_ckpt "$SCANNER_CKPT_DIR")
fi

RUN_CKPT_DIR="$dir_tool/qalas_log/$sub_ses_run/checkpoints"
RUN_CKPT=$(newest_ckpt "$RUN_CKPT_DIR")

if [ -n "$SCANNER_CKPT" ]; then

    echo "DATA FROM THIS SCANNER HAS ALREADY BEEN PROCESSED, INITIALISING FROM ITS WEIGHTS"
    ls "$SCANNER_CKPT"
    # Process NIfTI files into h5
    cd main_data/
    python3 ssl_qalas_save_h5.py "$sub_ses" "$f_QALAS" "$f_fmap" "$dir_bids" "$dir_tool"
    cd -
    # NOTE: weights-only warm start. --init_from_checkpoint (added to train_qalas.py)
    # copies the network weights out of the scanner checkpoint and then starts a NEW fit: 
    # epoch counter at 0, fresh optimizer state, fresh LR schedule, fresh ModelCheckpoint 
    # state. So --max_epochs means exactly that many epochs for this session.
    #
    # --resume_from_checkpoint is deliberately NOT used here. It continues
    # ANOTHER subject's fit: it restores that subject's optimizer moments and
    # decayed learning rate, its epoch counter and its ModelCheckpoint best-score
    # state, which can stop this run from ever writing a checkpoint of its own. Resume 
    # is for continuing an interrupted fit on the SAME data -- that is the elif below.
    python train_qalas.py --data_path main_data/h5_data/${sub_ses_run//-/} --check_val_every_n_epoch 4 --max_epochs $EPOCHS_WARMSTART --default_root_dir qalas_log/$sub_ses_run --use_dataset_cache_file False --init_from_checkpoint "$SCANNER_CKPT"
    echo "PROCESSING WAS DONE STARTING FROM SCANNER-SPECIFIC WEIGHTS PRODUCED ON A PREVIOUS RUN"
    ls -lrt "$SCANNER_CKPT"

# === Check if the processing hasn't been completed previously ===
elif [ -n "$RUN_CKPT" ]; then

    echo "CHECKPOINT FOUND FOR THIS RUN, RESUMING PROCESSING (ONLY $EPOCHS_RESUME EPOCHS)"
    ls -lrt "$RUN_CKPT"
    # A real resume of this session's own fit, so the epoch counter continues
    # where it stopped and --max_epochs has to be the absolute target.
    MAX_EPOCHS=$(epochs_after "$RUN_CKPT" "$EPOCHS_RESUME")
    if [ -z "$MAX_EPOCHS" ]; then
        echo "ERROR: could not read the epoch out of $RUN_CKPT -- stopping."
        exit 1
    fi
    echo "Resuming at the checkpoint's epoch and running $EPOCHS_RESUME more (--max_epochs $MAX_EPOCHS)"
    python train_qalas.py --data_path main_data/h5_data/${sub_ses_run//-/} --check_val_every_n_epoch 4 --max_epochs "$MAX_EPOCHS" --default_root_dir qalas_log/$sub_ses_run --use_dataset_cache_file False --resume_from_checkpoint "$RUN_CKPT"
    echo "PROCESSING WAS MADE STARTING FROM A CHECKPOINT"
    ls -lrt "$RUN_CKPT_DIR"

# === If no checkpoint found, start a new processing ===
else

    # Process NIfTI files into h5
    cd main_data/
    python3 ssl_qalas_save_h5.py "$sub_ses" "$f_QALAS" "$f_fmap" "$dir_bids" "$dir_tool"
    cd -

    # Train the model
    python train_qalas.py --data_path main_data/h5_data/${sub_ses_run//-/} --check_val_every_n_epoch 4 --max_epochs $EPOCHS_FRESH --default_root_dir qalas_log/$sub_ses_run --use_dataset_cache_file False

fi

# === Produce maps ===
# Re-resolve: this must be a checkpoint that the training above actually wrote.
RUN_CKPT=$(newest_ckpt "$RUN_CKPT_DIR")
if [ -z "$RUN_CKPT" ]; then
    echo "ERROR: training wrote no checkpoint in $RUN_CKPT_DIR."
    echo "       Not running inference -- an unresolved epoch*.ckpt glob here is what"
    echo "       produces a grid of NaN for every map instead of failing."
    exit 1
fi
echo "Using checkpoint for inference:"
ls -lrt "$RUN_CKPT"
python inference_qalas_map.py --data_path main_data/h5_data/${sub_ses_run//-/}/multicoil_val --state_dict_file "$RUN_CKPT" --output_path main_data/h5_data/${sub_ses_run//-/}

# === Move the last checkpoint and the corresponding .json ===
mkdir -p "$RUN_CKPT_DIR/old"
mv "$RUN_CKPT_DIR"/epoch*.ckpt "$RUN_CKPT_DIR/old/"
cp "$dir_bids/$sub_ses/anat/${f_QALAS/\.nii*/.json}" "$RUN_CKPT_DIR/old/"
LAST_CKPT="$RUN_CKPT_DIR/old/$(basename "$RUN_CKPT")"

# === Extract maps from the h5 file ===
cd main_data/
python3 h5_to_maps.py "$sub_ses" "$f_QALAS" "$dir_bids"
cd -

# === Save weights for a new scanner ===

if [ -n "$DSN" ] && [ -z "$(newest_ckpt "$SCANNER_CKPT_DIR")" ]; then
    mkdir -p "$SCANNER_CKPT_DIR"
    cp "$LAST_CKPT" "$SCANNER_CKPT_DIR/"
    echo "SCANNER-SPECIFIC WEIGHTS WERE SAVED FOR" $DSN "IN qalas_log/scanner_checkpoints"
fi

echo 'Processing ' $sub_ses_run ' is done.'
