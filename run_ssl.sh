##########################################################################################
#                                                                                        #
# run_ssl.sh:                                                                            #
# This script automatically handles all the 3D-QALAS processing from the BIDS files to   #
# the parametric maps. It takes a list of subject/session IDs as input and performs a    #
# set of sanity checks on each B1 map and 3D-QALAS image pair to determine the best      #
# match for each 3D-QALAS run. If the selected B1 map is an AFI image, it estimates the  #
# actual B1 image from the 2-echo raw images with various TR. Then the selected B1 maps  # 
# are coregistered with 3D-QALAS images and the selected pair is processed by            # 
# submit_CPU.sh script.                                                                  #
#                                                                                        #
##########################################################################################


IFS=$'\n\t'

# === CONFIGURATION ===
dir_tool='/path/to/SSL-QALAS-main-crossvendor'   # Path to the folder where SSL-QALAS-crossvendor is stored
sub_ses_list=$dir_tool'/lists/sub_ses_list.txt'  # Path to the list of sessions to process (each entry should be a BIDS-compliant name, i.e. "sub-*/ses-*") - can be saved within the tool folder
dir_bids='/path/to/bids'                         # Path to BIDS where all the participants to be processed are stored
afi_out=$dir_tool'/afi_b1_maps'                  # Path to the folder where estimated AFI maps should be saved (if applicable) - can be saved within the tool folder
sum_out=$dir_tool'/overview'                     # Path to the folder where general summaries are stored - can be saved within the tool folder
dir_conda='/path/to/conda'                       # Path to (mini)conda or to a standalone environment directory (if the environment is not registered in Conda, see Troubleshooting in README.md).
dir_matlab='/path/to/MATLAB'                     # Path to MATLAB on your machine
lic_matlab=''                                    # Leave empty if the licence is provided in MATLAB folder (most likely scenario), otherwise provide the license file or the license server

# === PREPARATION ===

# Ensure summary and log directories exist
mkdir -p "$sum_out" "$dir_tool/logs"

# Clear previous summary output files
rm -f "$sum_out"/*

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

# Find QALAS JSON files
function get_qalas_jsons_lists {
    local sub_ses="$1"
    local qalas_jsons_list
    qalas_jsons_list=$(ls "$sub_ses/anat/"*inv-0*_QALAS.json 2>/dev/null || true)
    [[ -z "$qalas_jsons_list" ]] && qalas_jsons_list=$(ls "$sub_ses/anat/"*_QALAS.json 2>/dev/null || true)
    echo "$qalas_jsons_list"
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

# Check if runs are in the correct order
function date_run_check {
    local jsons_list="$1"
    for json_current in $jsons_list; do
        for json_to_check in $jsons_list; do
            if [[ "$json_to_check" != "$json_current" ]]; then
                # Extract the AcquisitionDateTime strings
                date_current=$(jq -r '.AcquisitionDateTime' $json_current)
                date_to_check=$(jq -r '.AcquisitionDateTime' $json_to_check)
                # Convert to Unix timestamps for comparison
                ts_current=$(date -d "$date_current" +%s)
                ts_to_check=$(date -d "$date_to_check" +%s)
                # Extract the run number
                run_current=$(echo $json_current | sed -n 's/.*run-\(.\).*/\1/p')
                run_to_check=$(echo $json_to_check | sed -n 's/.*run-\(.\).*/\1/p')
                # Compare
                if (( ts_current > ts_to_check && run_current < run_to_check )); then
                    run_time_difference_flag=true
                    break
                fi
            fi
        done
    done
}

# Check if ShimSetting of the B1 map is unique
function check_identical_shims {
    local fmap_jsons_list="$1"
    local json_fmap="$2"
    local dir_bids="$3"
    # Initialize the flag variable to true — we'll assume shim settings are different unless proven otherwise
    shim_identical_flag=false
    # This will store the ShimSetting of the current json_fmap to compare against others
    current_shim_b1=$(jq -c '.ShimSetting' "$dir_bids/$json_fmap" 2>/dev/null)
    # Loop through each JSON file in the list
    for file in $fmap_jsons_list; do
        # Skip the current json_fmap
        if [[ "$file" == "$json_fmap" ]]; then
            continue
        fi
        # Extract the ShimSetting field as a compact JSON array
        shim=$(jq -c '.ShimSetting' "$dir_bids/$file" 2>/dev/null)
        # Compare current shim to the one from the list; if they are the same, set flag to true and exit the loop
        if [[ "$shim" == "$current_shim_b1" ]]; then
            echo 'An identical ShimSetting has been encountered in' "$json_fmap" 'and' "$file"
            shim_identical_flag=true
            break
        fi
    done
}

# Coregister B1 map to QALAS image and submit a processing job
function run_coregistration_and_submit {
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
        echo "$json_fmap;$json_QALAS" >> "$4" # Append the processed runs to the log (same log as submitted)
    else
        f_fmap=$(basename "$fmap_coreg_output")
        echo "$json_fmap;$json_QALAS" >> "$4" # Append the submitted runs to the log
        sbatch --output="$dir_tool/logs/$f_QALAS.log" "$dir_tool/submit_CPU.sh" "$sub_ses" "$f_QALAS" "$f_fmap" "$dir_bids" "$dir_tool" "$dir_conda" "$dir_matlab" "$lic_matlab" 
        echo $sub_ses 'submitted successfully'
        echo "---------------------------------------------"
    fi
}

# Main subject/session processing logic
function process_subject {
    local sub_ses="$1"

    # Try different patterns to find candidate fieldmaps
    local fmap_patterns=(
        "$sub_ses/fmap/*tr1_run-*_TB1AFI.json"
        "$sub_ses/fmap/*acq-famp_run-*_TB1TFL.json"
        "$sub_ses/fmap/*part-phase_TB1TFL.json"
    )

    # Find all the candidate B1 maps within the session
    local fmap_jsons_list=""
    for pattern in "${fmap_patterns[@]}"; do
        fmap_jsons_list=$(ls $pattern 2>/dev/null || true)
        [[ -n "$fmap_jsons_list" ]] && break
    done
    fmap_jsons_list_nelem=$(echo "$fmap_jsons_list" | wc -w)

    [[ -z "$fmap_jsons_list" ]] && echo "No B1 map found for" $sub_ses && return

    # Find candidate 3D-QALAS images
    qalas_jsons_list=$(get_qalas_jsons_lists "$sub_ses")
    qalas_jsons_list_nelem=$(echo "$qalas_jsons_list" | wc -w)

    # Check if there is a ShimSetting that is matched in both B1 and 3D-QALAS
    matching_shim_flag=false
    shims_qalas_list=$(jq -c '.ShimSetting' "$sub_ses/anat/"*_QALAS.json)
    for json_fmap in $fmap_jsons_list; do
        shim_b1_check=$(jq -c '.ShimSetting' $json_fmap)
        if [[ "$shims_qalas_list" == *"$shim_b1_check"* && "$shim_b1_check" != "null" ]]; then
            matching_shim_flag=true
        fi
    done

    # Loop over each found fieldmap
    for json_fmap in $fmap_jsons_list; do
        shim_fmap=$(jq -r ".ShimSetting" "$json_fmap")  # Extract shim info
        fmap=$(echo "$json_fmap" | grep -oP 'sub.*/.*\.json' | sed 's/\.json$/.nii.gz/')
        f_fmap="${fmap##*/}"

        # === Handle AFI (2-echo) fieldmaps ===
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

        # === Match with QALAS images ===
        for json_QALAS in $qalas_jsons_list; do
            shim_QALAS=$(jq -r ".ShimSetting" "$json_QALAS")
            qalas=$(echo "$json_QALAS" | grep -oP 'ses.*\.json' | sed 's/\.json$/.nii.gz/')
            f_QALAS="${qalas##*/}"

            # === Shim matching logic ===

            # Check if B1 map can be rather matched by the ShimSetting
            current_shim_b1=$(jq -c '.ShimSetting' "$json_fmap" 2>/dev/null)
            if [[ "$matching_shim_flag" == true && "$shims_qalas_list" != *"$current_shim_b1"* ]]; then
                continue
            fi

            # If multiple fmaps are available, check if their ShimSetting is not identical and if the run number is adequate
            run_time_difference_flag=false
            if [[ "$fmap_jsons_list_nelem" != 1 && "$current_shim_b1" != "null" ]]; then

                # See if the current shim is not null
                check_identical_shims "$fmap_jsons_list" "$json_fmap" "$dir_bids"

                # See is the run number is adequate when compared to the AcquisitionDateTime (relevant for "Run matching logic")
                date_run_check "$fmap_jsons_list"
                [[ "$run_time_difference_flag" == true ]] && echo $sub_ses "has B1 maps in a wrong order, may require manual inspection"

            fi

            # === Run matching logic ===
            run_fmap=$(echo "$json_fmap" | grep -oP 'run-\d+(?=_)')
            run_qalas=$(echo "$json_QALAS" | grep -oP 'run-\d+(?=_)')

            # If multiple 3D-QALAS runs are available, check if the run number is adequate
            if [[ "$qalas_jsons_list_nelem" != 1 ]]; then
                date_run_check "$qalas_jsons_list"
                [[ "$run_time_difference_flag" == true ]] && echo $sub_ses "has 3D-QALAS runs in a wrong order, may require manual inspection"
            fi

            # === Submit the matched 3D-QALAS/B1 map pair ===
            if [[ "$qalas_jsons_list_nelem" == "$fmap_jsons_list_nelem" && "$fmap_jsons_list_nelem" == 1 ]]; then
                # Only one combination of files is possible
                echo 'Only one pair of 3D-QALAS and B1 map was found:'
                echo "$f_QALAS"
                echo "$f_fmap"
                run_coregistration_and_submit "$sub_ses" "$f_QALAS" "$f_fmap" "$sum_out/multi_submitted.txt"
            elif [[ "$shim_fmap" == "$shim_QALAS" && "$shim_QALAS" != "null" && $shim_identical_flag == false ]]; then
                # Exact unique shim match
                echo 'The match was made based on the unique ShimSetting of 3D-QALAS and B1 map:'
                echo "$f_QALAS"
                echo "$f_fmap"
                run_coregistration_and_submit "$sub_ses" "$f_QALAS" "$f_fmap" "$sum_out/multi_submitted.txt"
            elif [[ "$run_fmap" == "$run_qalas" && "$run_time_difference_flag" == false ]]; then
                # Shim info missing or not unique – try fallback: match by run number
                echo 'The match was made based on the run number of 3D-QALAS and B1 map:'
                echo "$f_QALAS"
                echo "$f_fmap"
                run_coregistration_and_submit "$sub_ses" "$f_QALAS" "$f_fmap" "$sum_out/multi_submitted.txt"
            else
                # Shim mismatch – log for manual inspection (the pipeline has to run to the end for the log to work adequately)
                echo "$json_fmap;$json_QALAS" >> "$sum_out/no_clear_match.txt"
            fi
            unset shim_identical_flag
            unset run_time_difference_flag
            unset matching_shim_flag
        done
    done
}

# === MAIN EXECUTION ===

# Check required tools are available
check_dependencies

# Loop over subject-session entries in the list
cd "$dir_bids"
while IFS= read -r line || [[ -n "$line" ]]; do
    process_subject "$line"
done < "$sub_ses_list"

# === POSTPROCESSING ===

# Extract successfully submitted QALAS files
awk -F";" '{print $2}' "$sum_out/multi_submitted.txt" > "$sum_out/QALAS_multi_submitted.txt"

# Remove QALAS entries from the "different" list that were already submitted
grep -Fv -f "$sum_out/QALAS_multi_submitted.txt" "$sum_out/no_clear_match.txt" > "$sum_out/no_clear_match_filtered.txt"
mv "$sum_out/no_clear_match_filtered.txt" "$sum_out/no_clear_match.txt"

echo "Processing of the following sessions has failed:"
cat "$sum_out/no_clear_match.txt" | cut -d"/" -f1-2 | sort | uniq

# Return to tool directory
cd "$dir_tool"


