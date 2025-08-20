#!/bin/sh

#SBATCH --job-name=SSL_QALAS
#SBATCH --time=72:00:00
#SBATCH --mem-per-cpu=2G
#SBATCH --cpus-per-task=4
#SBATCH --ntasks=1

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
dir_matlab="$7"
lic_matlab="$8"

# === Prepare the alias for running MATLAB ===
if [[ -z "$lic_matlab" ]]; then
    # If no license was provided
    alias run_matlab='$dir_matlab/bin/matlab -nodisplay -nosplash -r'
else
    # If license was provided
    alias run_matlab='$dir_matlab/bin/matlab -nodisplay -nosplash -c $lic_matlab -r'
fi


# === Construcs the sub_ses_run and prepare the environment
sub_ses_run=${sub_ses}'/'$(echo $f_QALAS | grep -oP 'run-\d+(?=_)')

source $dir_conda/bin/activate ssl_qalas_crossvendor
cd $dir_tool

# === Check if the processing hasn't been completed previously ===
if [ -e qalas_log/$sub_ses_run/checkpoints/epoch*.ckpt ]; then

    echo "CHECKPOINT FOUND, RESUMING PROCESSING"
    ls -lrt qalas_log/$sub_ses_run/checkpoints/epoch*.ckpt
    python train_qalas.py --data_path matlab/h5_data/${sub_ses_run//-/} --check_val_every_n_epoch 4 --default_root_dir qalas_log/$sub_ses_run --use_dataset_cache_file False --resume_from_checkpoint qalas_log/$sub_ses_run/checkpoints/epoch*.ckpt
    echo "PROCESSING WAS MADE STARTING FROM A CHECKPOINT"
    ls -lrt qalas_log/$sub_ses_run/checkpoints/epoch*.ckpt

# === If no checkpoint found, start a new processing ===
else

    # Process NIfTI files into h5
    cd matlab/
    run_matlab "ssl_qalas_save_h5('$sub_ses', '$f_QALAS', '$f_fmap', '$dir_bids', '$dir_tool'); exit"
    cd -

    # Train the model
    python train_qalas.py --data_path matlab/h5_data/${sub_ses_run//-/} --check_val_every_n_epoch 4 --default_root_dir qalas_log/$sub_ses_run --use_dataset_cache_file False

fi

# === Produce maps ===
python inference_qalas_map.py --data_path matlab/h5_data/${sub_ses_run//-/}/multicoil_val --state_dict_file qalas_log/$sub_ses_run/checkpoints/epoch*.ckpt --output_path matlab/h5_data/${sub_ses_run//-/}

# === Move the last checkpoint ===
mkdir qalas_log/$sub_ses_run/checkpoints/old/
mv qalas_log/$sub_ses_run/checkpoints/epoch*.ckpt qalas_log/$sub_ses_run/checkpoints/old/

# === Extract maps from the h5 file ===
cd matlab/
run_matlab "h5_to_maps('$sub_ses', '$f_QALAS', '$dir_bids'); exit"

echo 'Processing ' $sub_ses_run ' is done.'


