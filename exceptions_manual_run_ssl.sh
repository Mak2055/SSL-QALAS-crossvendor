
##########################################################################################
#                                                                                        #
# exceptions_manual_run_ssl.sh:                                                          #
# This script is used for handling the exceptions that did not pass the sanity check in  #
# run_ssl.sh by processing any 3D-QALAS and B1 map pair provided. It performs analogous  # 
# to run_ssl.sh pre-processing steps - AFI B1 maps estimation from the 2-echo raw images #
# and B1 map coregistration to 3D-QALAS. Then the selected B1 maps are coregistered with #
# 3D-QALAS images and the selected couple is processed by submit_CPU.sh script.          #
#                                                                                        #
########################################################################################## 

IFS=$'\n\t'

# === PROVIDE (ONLY THE) FILENAMES ===
f_QALAS="sub-*_ses-*_run-?_inv-0_QALAS.nii.gz"   # inv-0 for ungrouped 3D-QALAS NIfTI
f_fmap="sub-*_ses-*_acq-tr1_run-?_TB1AFI.nii.gz" # acq-tr1 for AFI; acq-famp for TFL

# === CONFIGURATION ===
dir_tool='/path/to/SSL-QALAS-main-crossvendor'   # Path to the folder where SSL-QALAS-main-crossvendor is stored
dir_bids='/path/to/bids'                         # Path to BIDS where all the participants to be processed are stored
afi_out=$dir_tool'/afi_b1_maps'                  # Path to the folder where estimated AFI maps should be saved (if applicable) - can be within the tool folder
dir_conda='/path/to/conda'                       # Path to (mini)conda on your machine
dir_matlab='/path/to/MATLAB'                     # Path to MATLAB on your machine
lic_matlab=''                                    # Leave empty if the licence is provided in MATLAB folder (most likely scenario), otherwise provide the license file or the license server

# === PREPARATION ===

# Ensure summary and log directories exist
mkdir -p "$dir_tool/logs"

# === HELPER FUNCTIONS ===

# Check that required commands exist in the PATH
function check_dependencies {
    for cmd in jq python3 sbatch conda; do
        if ! command -v "$cmd" &>/dev/null; then
            echo "Error: Required command '$cmd' not found in PATH"
            exit 1
        fi
    done
}

# Activate the conda environment used for QALAS processing
function activate_env {
    source "$dir_conda/bin/activate" ssl_qalas_crossvendor
}

# Deactivate the conda environment
function deactivate_env {
    conda deactivate || true
}

# Estimate AFI-based B1+ map
function estimate_afi {
    local fmap1="$1"
    local fmap2="$2"
    local output="$3"
    mkdir -p "$(dirname "$output")"
    activate_env
    python3 "$dir_tool/calculate_afi_b1.py" "$fmap1" "$fmap2" "$output"
    deactivate_env
}

# Coregister B1 map to QALAS image and submit a processing job
function run_coregistration_and_submit_manual_pick {
    local sub_ses="$1" f_QALAS="$2" f_fmap="$3"
    local fmap_coreg_output="$dir_tool/coreg_b1_maps/$sub_ses/fmap/$(echo "$f_fmap" | sed -e 's/acq-famp/acq-coreg/g' -e 's/acq-est/acq-coreg/g' -e 's/part-phase/part-coreg/g')"

    if [[ ! -f "$fmap_coreg_output" ]]; then

        mkdir -p "$(dirname "$fmap_coreg_output")"

        # Coregister the fieldmaps to the 3D-QALAS
        activate_env
        python3 "$dir_tool/coreg_b1.py" "$dir_bids/$fmap_contrast" "$dir_bids/$sub_ses/anat/$f_QALAS" "$path_precoreg_f_fmap/$sub_ses/fmap/$f_fmap" "$fmap_coreg_output"
        deactivate_env
    fi

    # Submit job only if not already submitted
    if [[ -e "$dir_tool/logs/$f_QALAS.log" ]]; then
        echo "$f_QALAS has already been submitted"
    else
        f_fmap=$(basename "$fmap_coreg_output")
        echo "This run was submitted by manually choosing the B1 map and 3D-QALAS pair" >> $dir_tool/logs/$f_QALAS.log
        sbatch --output="$dir_tool/logs/$f_QALAS.log" "$dir_tool/submit_CPU.sh" "$sub_ses" "$f_QALAS" "$f_fmap" "$dir_bids" "$dir_tool" "$dir_conda" "$dir_matlab" "$lic_matlab"
        echo $sub_ses 'submitted successfully'
        echo "---------------------------------------------"
    fi
}

# Main subject/session processing logic
function process_subject_manual_pick {
    local f_fmap="$1"
    local f_QALAS="$2"

    # === Exctract the subject and session and see if they match in both files ===
    sub_ses=$(echo "$f_QALAS" | sed -n 's|.*\(sub-[^_]*_ses-[^_]*\).*|\1|p' | sed 's|_|/|')
    sub_ses_test=$(echo "$f_fmap" | sed -n 's|.*\(sub-[^_]*_ses-[^_]*\).*|\1|p' | sed 's|_|/|')
    if [[ "$sub_ses" != "$sub_ses_test" ]]; then
        echo "Subject and session do not match in the two provided files"
        exit 1
    fi

    # === Handle AFI (2-echo) fieldmaps ===
    fmap="${sub_ses}/fmap/${f_fmap}"
    if [[ "$f_fmap" == *TB1AFI.nii.gz ]]; then
        fmap_tr2=$(echo "$fmap" | sed 's/acq-tr1/acq-tr2/')
        path_fmap_output="$afi_out/$sub_ses/fmap/$(basename "$f_fmap" | sed 's/acq-tr1/acq-est/')"

        # Estimate AFI map if it doesn't exist
        if [[ ! -f "$path_fmap_output" ]]; then
            estimate_afi "$dir_bids/$fmap" "$dir_bids/$fmap_tr2" "$path_fmap_output"
        fi

        fmap_contrast="$fmap"                              # Save original tr1 path
        f_fmap="$(basename "$path_fmap_output")"           # Use estimated map as input
        path_precoreg_f_fmap="$afi_out"
    else
        fmap_contrast=$(echo "$fmap" | sed 's/acq-famp/acq-anat/' | sed 's/part-phase/part-mag/')
        path_precoreg_f_fmap="$dir_bids"                   # Use TFL directly
    fi

    # === Submit the picked 3D-QALAS/B1 map pair ===
    echo 'The 3D-QALAS and B1 map pair was selected manually:'
    echo "$f_QALAS"
    echo "$f_fmap"
    run_coregistration_and_submit_manual_pick "$sub_ses" "$f_QALAS" "$f_fmap"
}

# === MAIN EXECUTION ===

# Check required tools are available
check_dependencies

# Start processing the subject
process_subject_manual_pick "$f_fmap" "$f_QALAS"

# Return to tool directory
cd "$dir_tool"



