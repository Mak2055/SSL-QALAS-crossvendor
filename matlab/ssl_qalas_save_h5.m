function [ ] = ssl_qalas_save_h5_from_dicom(sub_ses, f_QALAS, f_fmap, dir_bids, dir_tool)

%% Prepare tje environment

%clear; clc; close all;
set(0,'DefaultFigureWindowStyle','docked')
addpath(genpath('utils'));

%% Set main variables

dfold=dir_bids;
ffold = [dir_tool, '/coreg_b1_maps/'];

pattern = 'run-\d+';
sub_ses_run = [sub_ses, '/', char(regexp(f_QALAS, pattern, 'match'))];

%% Set output variabøes

savepath = [dir_tool, '/matlab/h5_data/', strrep(sub_ses_run, '-', ''), '/multicoil_train/'];
savename = 'train_data.h5';
savepath_val = [dir_tool, '/matlab/h5_data/', strrep(sub_ses_run, '-', ''), '/multicoil_val/'];
savename_val = 'val_data.h5';
mkdir(savepath)
mkdir(savepath_val)
mkdir([savepath, '/../multicoil_test'])
mkdir([savepath, '/../reconstructions'])

%% Provide info on on B1 map

compare_ref_map     = 0;
% 1 (compare ssl-qalas with reference maps (e.g., dictionary matching) during training)
% 0 (no comparison > will use zeros)

load_b1_map         = 1;
% 1 (load pre-acquired b1 map)
% 0 (no b1 map)


if contains(f_fmap, 'TFL')
    b1_type         = 1;
elseif contains(f_fmap, 'AFI')
    b1_type         = 2;
end
% 1 (TFL-based)
% 2 (AFI-based)


input_type          = 2;
% 1 (DICOM)
% 2 (NIFTI)


%% Load data

if compare_ref_map == 1
    load('map_data/ref_map.mat');
end

fprintf('loading data ... ');
tic

if input_type == 1 % for DICOM data, not fully implemented yet
    dpath       = [dfold, '/', sub_ses_run, '/', f_QALAS];
    b1path      = [ffold, '/', sub_ses_run, '/', f_fmap];
    input_img   = single(dicomread_dir(dpath));
    input_img   = reshape(input_img,[size(input_img,1),size(input_img,2),size(input_img,3)/5,1,5]);

    %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
    %%%%%%%%%%%% TODO ADD HEADER READING FROM DICOM FILES %%%%%%%%%%%%
    %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

elseif input_type == 2 % for NIFTI data
    dpath       = [dfold, '/', sub_ses, '/anat/', f_QALAS];
    b1path      = [ffold, '/', sub_ses, '/fmap/', f_fmap];
    
    if contains(dpath, '_inv-') % assuming that this is going to be a BIDS standard for when 3D-QALAS images are divided
        loaded_nifti=load_nifti(dpath);
        input_inv = single(loaded_nifti.vol);
        input_img = zeros([size(input_inv), 5]);
        input_img(:,:,:,1)=input_inv;
        % Loop over the "inv-" values 0 to 4
        for i = 1:4
            % Create a replacement string for the current iteration
            replacement = ['_inv-' num2str(i)];
            % Replace "inv-[0-4]" with the current value
            dpath_inv = strrep(dpath, '_inv-0', replacement);
            loaded_nifti=load_nifti(dpath_inv);
            input_inv = single(loaded_nifti.vol);
            input_img(:,:,:,i+1)=input_inv;
        end
    else % for when 3D-QALAS images are nested
        input_nifti = load_nifti(dpath);
        input_img = single(input_nifti.vol);
    end


    % Loading .json
    filename = regexprep(dpath, '\.nii.*$', '.json');
    json_contents = jsondecode(fileread(filename));

    % NIFTI are rotated compared to DICOM files, here rotation is done to
    % bring NIFTI into the same space
    if contains(json_contents.Manufacturer, 'GE', 'IgnoreCase', true)
        input_img = permute(input_img,[3,2,1,4]);
        input_img = reshape(input_img,[size(input_img,1),size(input_img,2),size(input_img,3),1,size(input_img,4)]);
        input_img = flip(input_img, 1);
        input_img = flip(input_img, 2);
        input_img = flip(input_img, 3);
    else
        input_img = permute(input_img,[2,1,3,4]);
        input_img = reshape(input_img,[size(input_img,1),size(input_img,2),size(input_img,3),1,size(input_img,4)]);
        input_img = flip(input_img, 1);
        input_img = flip(input_img, 3);
    end

end

if load_b1_map == 1
    if input_type == 1 % for DICOM data
        B1_map = single(dicomread_dir(b1path));
    elseif input_type == 2 % for NIFTI data
        if contains(json_contents.Manufacturer, 'Siemens', 'IgnoreCase', true)
            loaded_nifti_b1=load_nifti(b1path);
            B1_map = single(loaded_nifti_b1.vol);
            % NIFTI are rotated compared to DICOM files, here rotation is done
            % to bring NIFTI into the same space
            B1_map = permute(B1_map,[2,1,3]);
            B1_map = flip(B1_map, 1);
            B1_map = flip(B1_map, 3);
        else
            loaded_nifti_b1=load_nifti(b1path); % For whatever reason the AFI estimation code rotates Philips maps into the same orientation like GE
            B1_map = single(loaded_nifti_b1.vol);
            % NIFTI are rotated compared to DICOM files, here rotation is done
            % to bring NIFTI into the same space
            B1_map = permute(B1_map,[3,2,1]);
            B1_map = flip(B1_map, 1);
            B1_map = flip(B1_map, 2);
            B1_map = flip(B1_map, 3);
        end
    end
    % Normalize TFL maps (for AFI it is performed at the estimation step)
    if b1_type == 1
        B1_map = B1_map./800; % for TFL-based B1
%    elseif b1_type == 2
%        B1_map = B1_map./60; % for AFI-based B1
    end
    B1_map = imresize3(B1_map,[size(input_img,1),size(input_img,2),size(input_img,3)]);
    B1_map(B1_map>1.35) = 1.35;
    B1_map(B1_map<0.65) = 0.65;
end
toc

%% Brain Mask (simple thresholding mask) -> may not be accurate

threshold = 50;

[Nx,Ny,Nz,~,~]  = size(input_img);
bmask           = zeros(Nx,Ny,Nz,'single');

for slc = 1:size(input_img,3)
   bmask(:,:,slc) = imfill(squeeze(rsos(input_img(:,:,slc,1,:),5)) > threshold, 'holes');
end

%% Organize the variables

input_img       = input_img./max(input_img(:));

sens            = ones(Nx,Ny,Nz,1,'single');
mask            = ones(Nx,Ny,'single');
if compare_ref_map == 0
    T1_map = ones(Nx,Ny,Nz,'single').*5;
    T2_map = ones(Nx,Ny,Nz,'single').*2.5;
    PD_map = ones(Nx,Ny,Nz,'single');
    IE_map = ones(Nx,Ny,Nz,'single');
end
if load_b1_map == 0
    B1_map = ones(Nx,Ny,Nz,'single');
end

input_img   = permute(input_img,[2,1,4,3,5]);
sens        = permute(sens,[2,1,4,3]);

T1_map      = permute(T1_map,[2,1,3]);
T2_map      = permute(T2_map,[2,1,3]);
PD_map      = permute(PD_map,[2,1,3]);
IE_map      = permute(IE_map,[2,1,3]);
B1_map      = permute(B1_map,[2,1,3]);

bmask       = permute(bmask,[2,1,3]);
mask        = permute(mask,[2,1]);

kspace_acq1 = single(input_img(:,:,:,:,1));
kspace_acq2 = single(input_img(:,:,:,:,2));
kspace_acq3 = single(input_img(:,:,:,:,3));
kspace_acq4 = single(input_img(:,:,:,:,4));
kspace_acq5 = single(input_img(:,:,:,:,5));


%% Save data

fprintf('save h5 data ... ');

tic

file_name   = strcat(savepath,savename);
file_name_val   = strcat(savepath_val,savename_val);

att_patient = '0000';
att_seq     = 'QALAS';

kspace_acq1     = permute(kspace_acq1,[4,3,2,1]);
kspace_acq2     = permute(kspace_acq2,[4,3,2,1]);
kspace_acq3     = permute(kspace_acq3,[4,3,2,1]);
kspace_acq4     = permute(kspace_acq4,[4,3,2,1]);
kspace_acq5     = permute(kspace_acq5,[4,3,2,1]);
coil_sens       = permute(sens,[4,3,2,1]);

saveh5(struct('kspace_acq1', kspace_acq1, 'kspace_acq2', kspace_acq2, ...
              'kspace_acq3', kspace_acq3, 'kspace_acq4', kspace_acq4, ...
              'kspace_acq5', kspace_acq5), ...
              file_name, 'ComplexFormat',{'r','i'});

h5create(file_name,'/reconstruction_t1',[Ny,Nx,Nz],'Datatype','single');
h5write(file_name, '/reconstruction_t1', T1_map);
h5create(file_name,'/reconstruction_t2',[Ny,Nx,Nz],'Datatype','single');
h5write(file_name, '/reconstruction_t2', T2_map);
h5create(file_name,'/reconstruction_pd',[Ny,Nx,Nz],'Datatype','single');
h5write(file_name, '/reconstruction_pd', PD_map);
h5create(file_name,'/reconstruction_ie',[Ny,Nx,Nz],'Datatype','single');
h5write(file_name, '/reconstruction_ie', IE_map);
h5create(file_name,'/reconstruction_b1',[Ny,Nx,Nz],'Datatype','single');
h5write(file_name, '/reconstruction_b1', B1_map);

h5create(file_name,'/mask_acq1',[Ny,1],'Datatype','single');
h5write(file_name, '/mask_acq1', mask(:,1));
h5create(file_name,'/mask_acq2',[Ny,1],'Datatype','single');
h5write(file_name, '/mask_acq2', mask(:,1));
h5create(file_name,'/mask_acq3',[Ny,1],'Datatype','single');
h5write(file_name, '/mask_acq3', mask(:,1));
h5create(file_name,'/mask_acq4',[Ny,1],'Datatype','single');
h5write(file_name, '/mask_acq4', mask(:,1));
h5create(file_name,'/mask_acq5',[Ny,1],'Datatype','single');
h5write(file_name, '/mask_acq5', mask(:,1));

h5create(file_name,'/mask_brain',[Ny,Nx,Nz],'Datatype','single');
h5write(file_name, '/mask_brain', single(bmask));

att_norm_t1 = norm(T1_map(:));
att_max_t1  = max(T1_map(:));
att_norm_t2 = norm(T2_map(:));
att_max_t2  = max(T2_map(:));
att_norm_pd = norm(PD_map(:));
att_max_pd  = max(PD_map(:));
att_norm_ie = norm(IE_map(:));
att_max_ie  = max(IE_map(:));
att_norm_b1 = norm(B1_map(:));
att_max_b1  = max(B1_map(:));

h5writeatt(file_name,'/','norm_t1',att_norm_t1);
h5writeatt(file_name,'/','max_t1',att_max_t1);
h5writeatt(file_name,'/','norm_t2',att_norm_t2);
h5writeatt(file_name,'/','max_t2',att_max_t2);
h5writeatt(file_name,'/','norm_pd',att_norm_pd);
h5writeatt(file_name,'/','max_pd',att_max_pd);
h5writeatt(file_name,'/','norm_ie',att_norm_ie);
h5writeatt(file_name,'/','max_ie',att_max_ie);
h5writeatt(file_name,'/','norm_b1',att_norm_b1);
h5writeatt(file_name,'/','max_b1',att_max_b1);
h5writeatt(file_name,'/','patient_id',att_patient);
h5writeatt(file_name,'/','acquisition',att_seq);

# Provide metadata describing the parameters of the 3D-QALAS sequence 
% For now it assumes that there are only three sequences, one for each vendor -> hardcoded

if contains(json_contents.Manufacturer, 'SIEMENS', 'IgnoreCase', true)

    att_flip_ang              = 4;
    att_tf                    = json_contents.EchoTrainLength;
    att_esp                   = json_contents.RepetitionTime;
    att_t2_prep               = 0.1097;
    att_gap_bw_ro             = 0.9;
    att_tr                    = 4.5;
    att_time_relax_end        = 0;
    att_echo2use              = 1;
    att_crusher_after_T2prep  = 9.7e-3;
    att_inv_pulse             = 12.8e-3;                             % delT_M4_M5
    att_gap_inv_readout       = 100e-3 - 6.45e-3;                    % delT_M5_M6
    att_manufacturer          = 'SIEMENS';

elseif contains(json_contents.Manufacturer, 'PHILIPS', 'IgnoreCase', true)

    att_flip_ang              = 4;
    att_tf                    = json_contents.EchoTrainLength;
    att_esp                   = json_contents.RepetitionTime;
    att_t2_prep               = 106.98e-3;
    att_gap_bw_ro             = 0.9;
    att_tr                    = 4.5;
    att_time_relax_end        = 0;
    att_echo2use              = 1;
    att_crusher_after_T2prep  = 6.22e-3;
    att_inv_pulse             = 13.059e-3;                           % delT_M4_M5
%    att_inv_pulse             = 9.494e-3;                            % delT_M4_M5
    att_gap_inv_readout       = 106.98e-3;                           % delT_M5_M6
    att_manufacturer          = 'PHILIPS';

elseif contains(json_contents.Manufacturer, 'GE', 'IgnoreCase', true)

    att_flip_ang              = 4;
%    att_tf                    = json_contents.ImagingFrequency;
    att_tf                    = 128;
    att_esp                   = json_contents.RepetitionTime;
    att_t2_prep               = 0.0928;
    heartbeat                 = 66.67;
    att_gap_bw_ro             = 60 / heartbeat;
    att_tr                    = 4.5;
    att_time_relax_end        = 0;
    att_echo2use              = 3;
    att_crusher_after_T2prep  = 2.34e-3;
    att_inv_pulse             = 16.2e-3;                             % delT_M4_M5
    att_gap_inv_readout       = 97.34e-3 + 160e-6 - att_inv_pulse/2; % delT_M5_M6
    att_manufacturer          = 'GE';

end


h5writeatt(file_name,'/','scan_flip_ang',att_flip_ang);
h5writeatt(file_name,'/','scan_tf',att_tf);
h5writeatt(file_name,'/','scan_esp',att_esp);
h5writeatt(file_name,'/','scan_t2_prep',att_t2_prep);
h5writeatt(file_name,'/','scan_gap_bw_ro',att_gap_bw_ro);
h5writeatt(file_name,'/','scan_tr',att_tr);
h5writeatt(file_name,'/','scan_time_relax_end',att_time_relax_end);
h5writeatt(file_name,'/','scan_echo2use',att_echo2use);
h5writeatt(file_name,'/','scan_crusher_after_T2prep',att_crusher_after_T2prep);
h5writeatt(file_name,'/','scan_inv_pulse',att_inv_pulse);
h5writeatt(file_name,'/','scan_gap_inv_readout',att_gap_inv_readout);
h5writeatt(file_name,'/','scan_manufacturer',att_manufacturer);

%% Save additional information about the sequence

dset = ismrmrd.Dataset(file_name);

header = [];

% Experimental Conditions (Required)
header.experimentalConditions.H1resonanceFrequency_Hz   = 128000000; % 3T

% Acquisition System Information (Optional)
header.acquisitionSystemInformation.receiverChannels    = 32;

% The Encoding (Required)
header.encoding.trajectory = 'cartesian';
header.encoding.encodedSpace.fieldOfView_mm.x   = Nx;
header.encoding.encodedSpace.fieldOfView_mm.y   = Ny;
header.encoding.encodedSpace.fieldOfView_mm.z   = Nz;
header.encoding.encodedSpace.matrixSize.x       = Nx*2;
header.encoding.encodedSpace.matrixSize.y       = Ny;
header.encoding.encodedSpace.matrixSize.z       = Nz;

% Recon Space
header.encoding.reconSpace.fieldOfView_mm.x     = Nx;
header.encoding.reconSpace.fieldOfView_mm.y     = Ny;
header.encoding.reconSpace.fieldOfView_mm.z     = Nz;
header.encoding.reconSpace.matrixSize.x         = Nx;
header.encoding.reconSpace.matrixSize.y         = Ny;
header.encoding.reconSpace.matrixSize.z         = Nz;

% Encoding Limits
header.encoding.encodingLimits.kspace_encoding_step_1.minimum   = 0;
header.encoding.encodingLimits.kspace_encoding_step_1.maximum   = Nx-1;
header.encoding.encodingLimits.kspace_encoding_step_1.center    = Nx/2;
header.encoding.encodingLimits.kspace_encoding_step_2.minimum   = 0;
header.encoding.encodingLimits.kspace_encoding_step_2.maximum   = 0;
header.encoding.encodingLimits.kspace_encoding_step_2.center    = 0;

% Serialize and write to the data set
xmlstring = ismrmrd.xml.serialize(header);
dset.writexml(xmlstring);

% Write the dataset
dset.close();
copyfile(file_name, file_name_val)

toc



