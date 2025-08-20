##########################################################################################
#                                                                                        #
# post_fix_failed_logs.sh:                                                               #
# This script scans through a list of subject/session IDs, checks for the presence of    #
# 3D-QALAS runs and their corresponding h5 reconstruction files, and identifies runs     #
# that have not been successfully processed. For any failed runs, it removes the         #
# associated log files, so they can be reprocessed by run_ssl.sh.                        #
#                                                                                        #
##########################################################################################


dir_tool='/path/to/SSL-QALAS-main-crossvendor'   # Path to the folder where SSL-QALAS-crossvendor is stored
sub_ses_list=$dir_tool'/lists/sub_ses_list.txt'  # Path to the list of sessions to process (each entry should be a BIDS-compliant name, i.e. "sub-*/ses-*") - can be within the tool folder
dir_bids='/path/to/bids'                         # Path to BIDS where all the participants to be processed are stored

# === Loop through each subject/session in the list ===
while read p; do sub_ses=$(echo $p)   # Read a line from the session list and store it in variable 'sub_ses'

        # === Identify relevant files for this session ===
        cd $dir_bids
        list_QALAS=$(ls "$sub_ses/anat/"*inv-0*_QALAS.nii.gz 2>/dev/null || true)                   # List 3D-QALAS NIfTI files for this session
        [[ -z "$list_QALAS" ]] && list_QALAS=$(ls "$sub_ses/anat/"*_QALAS.nii.gz 2>/dev/null || true) # List 3D-QALAS nested NIfTI files for this session (different inversions are concatinated) 

        # === If no QALAS file found ===
        if [[ -z "$list_QALAS" ]]; then
              echo "No QALAS file for $sub_ses was found"

        # === If maps have already been generated for this session ===
        elif [[ -e $dir_tool/matlab/maps/$sub_ses/ ]]; then
              echo "$sub_ses has already been submitted"

        # === Otherwise, check each QALAS run ===
        else
              cd $dir_tool
              for dir in $list_QALAS
                 do qalas=$(echo ${dir} | grep -oP '(ses.*)')              # Extract substring starting with 'ses'
                 f_QALAS=$(echo $qalas | awk -F"/" '{print $3}')           # Get file name (3rd field)
                 sub_ses_run=${sub_ses}'/'$(echo $f_QALAS | grep -o 'run-[1-9]')  # Combine sub/ses with run number

                 # === If corresponding HDF5 reconstruction exists ===
                 if [[ -e $dir_tool/matlab/h5_data/${sub_ses_run//-/}/reconstructions/val_data.h5 ]]; then
                    # MATLAB processing command (currently commented out)
                    echo $f_QALAS   # Just print file name

                 # === If HDF5 file missing ===
                 else
                    echo '!!!!!!!!!!!!!!!!!!!!!!!!!!!!!'
                    echo $f_QALAS has not been processed
                    echo '!!!!!!!!!!!!!!!!!!!!!!!!!!!!!'
                    rm $dir_tool/logs/$f_QALAS.log   # Remove log file for this run
                 fi
              done
        fi

# Read next subject/session from the list
done < $sub_ses_list

# Return to tool's root directory
cd $dir_tool


