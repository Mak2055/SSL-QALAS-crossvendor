function [ ] = h5_to_maps(sub_ses, f_QALAS, dir_bids)
%%

addpath(genpath('utils'));

%% Reading

pattern = 'run-\d+';
sub_ses_run = [sub_ses, '/', char(regexp(f_QALAS, pattern, 'match'))];
sub_ses_run_ = strrep(sub_ses_run, '/', '_');

display(sub_ses_run)

T1 = h5read(['h5_data/',strrep(sub_ses_run, '-', ''),'/reconstructions/val_data.h5'],'/reconstruction_t1');
T2 = h5read(['h5_data/',strrep(sub_ses_run, '-', ''),'/reconstructions/val_data.h5'],'/reconstruction_t2');
PD = h5read(['h5_data/',strrep(sub_ses_run, '-', ''),'/reconstructions/val_data.h5'],'/reconstruction_pd');
IE = h5read(['h5_data/',strrep(sub_ses_run, '-', ''),'/reconstructions/val_data.h5'],'/reconstruction_ie');
manufacturer = h5readatt(['h5_data/',strrep(sub_ses_run, '-', ''),'/multicoil_val/val_data.h5'], '/', 'scan_manufacturer');

info_NIFTI = niftiinfo([dir_bids, '/', sub_ses, '/anat/', f_QALAS]);

%% Fixing dimensions and info

if strcmpi(manufacturer, 'GE')
    % Dimensions
    T1 = permute(T1,[3,2,1]);
    T1 = flip(T1, 3);
    T1 = flip(T1, 2);
    T1 = flip(T1, 1);
    
    T2 = permute(T2,[3,2,1]);
    T2 = flip(T2, 3);
    T2 = flip(T2, 2);
    T2 = flip(T2, 1);
    
    PD = permute(PD,[3,2,1]);
    PD = flip(PD, 3);
    PD = flip(PD, 2);
    PD = flip(PD, 1);
    
    IE = permute(IE,[3,2,1]);
    IE = flip(IE, 3);
    IE = flip(IE, 2);
    IE = flip(IE, 1);
    
    % Info
    info_NIFTI.Datatype = 'single';
else
    % Dimensions
    T1 = permute(T1,[2,1,3]);
    T1 = flip(T1, 3);
    T1 = flip(T1, 2);

    T2 = permute(T2,[2,1,3]);
    T2 = flip(T2, 3);
    T2 = flip(T2, 2);

    PD = permute(PD,[2,1,3]);
    PD = flip(PD, 3);
    PD = flip(PD, 2);

    IE = permute(IE,[2,1,3]);
    IE = flip(IE, 3);
    IE = flip(IE, 2);
    
    % Info
    info_NIFTI.Datatype = 'single';
    if length(info_NIFTI.ImageSize)==4 % If 3D-QALAS is a 4D image
        info_NIFTI.ImageSize(4) = [];
        info_NIFTI.PixelDimensions(4) = [];
        info_NIFTI.raw.dim(5) = 1;
    end
end


% Set MultiplicativeScaling and AdditiveOffset in the metadata 
info_NIFTI.AdditiveOffset=0;
info_NIFTI.MultiplicativeScaling=1;


%% Saving

mkdir(['maps/',sub_ses, '/anat'])

niftiwrite(T1,['maps/',sub_ses,'/anat/',sub_ses_run_,'_T1map'], info_NIFTI, "Compressed", true)
niftiwrite(T2,['maps/',sub_ses,'/anat/',sub_ses_run_,'_T2map'], info_NIFTI, "Compressed", true)
niftiwrite(PD,['maps/',sub_ses,'/anat/',sub_ses_run_,'_PDmap'], info_NIFTI, "Compressed", true)
niftiwrite(IE,['maps/',sub_ses,'/anat/',sub_ses_run_,'_IEmap'], info_NIFTI, "Compressed", true)


