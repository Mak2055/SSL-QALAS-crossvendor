"""
Copyright (c) Facebook, Inc. and its affiliates.

This source code is licensed under the MIT license found in the
LICENSE file in the root directory of this source tree.
"""

from argparse import ArgumentParser

import fastmri
import torch
from fastmri.data import transforms_qalas
from fastmri.models import QALAS

from .mri_module_qalas import MriModuleQALAS
import numpy as np


class QALASModule(MriModuleQALAS):
    """
    QALAS training module.

    This can be used to train variational networks from the paper:

    A. Sriram et al. End-to-end variational networks for accelerated MRI
    reconstruction. In International Conference on Medical Image Computing and
    Computer-Assisted Intervention, 2020.

    which was inspired by the earlier paper:

    K. Hammernik et al. Learning a variational network for reconstruction of
    accelerated MRI data. Magnetic Resonance inMedicine, 79(6):3055–3071, 2018.
    """

    def __init__(
        self,
        num_cascades: int = 12,
        pools: int = 4,
        chans: int = 18,
        sens_pools: int = 4,
        sens_chans: int = 8,
        maps_chans: int = 32,
        maps_layers: int = 10,
        lr: float = 0.0003,
        lr_step_size: int = 40,
        lr_gamma: float = 0.1,
        weight_decay: float = 0.0,
        **kwargs,
    ):
        """
        Args:
            num_cascades: Number of cascades (i.e., layers) for variational
                network.
            pools: Number of downsampling and upsampling layers for cascade
                U-Net.
            chans: Number of channels for cascade U-Net.
            sens_pools: Number of downsampling and upsampling layers for
                sensitivity map U-Net.
            sens_chans: Number of channels for sensitivity map U-Net.
            lr: Learning rate.
            lr_step_size: Learning rate step size.
            lr_gamma: Learning rate gamma decay.
            weight_decay: Parameter for penalizing weights norm.
            num_sense_lines: Number of low-frequency lines to use for sensitivity map
                computation, must be even or `None`. Default `None` will automatically
                compute the number from masks. Default behaviour may cause some slices to
                use more low-frequency lines than others, when used in conjunction with
                e.g. the EquispacedMaskFunc defaults. To prevent this, either set
                `num_sense_lines`, or set `skip_low_freqs` and `skip_around_low_freqs`
                to `True` in the EquispacedMaskFunc. Note that setting this value may
                lead to undesired behaviour when training on multiple accelerations
                simultaneously.
        """
        super().__init__(**kwargs)
        self.save_hyperparameters()

        self.num_cascades = num_cascades
        self.pools = pools
        self.chans = chans
        self.sens_pools = sens_pools
        self.sens_chans = sens_chans
        self.maps_chans = maps_chans
        self.maps_layers = maps_layers
        self.lr = lr
        self.lr_step_size = lr_step_size
        self.lr_gamma = lr_gamma
        self.weight_decay = weight_decay

        self.qalas = QALAS(
            num_cascades=self.num_cascades,
            maps_chans=self.maps_chans,
            maps_layers=self.maps_layers,
            sens_chans=self.sens_chans,
            sens_pools=self.sens_pools,
            chans=self.chans,
            pools=self.pools,
        )

        self.loss_ssim_t1 = fastmri.SSIMLoss()
        self.loss_ssim_t2 = fastmri.SSIMLoss()
        self.loss_ssim_pd = fastmri.SSIMLoss()
        self.loss_ssim_ie = fastmri.SSIMLoss()
        self.loss_ssim_img1 = fastmri.SSIMLoss()
        self.loss_ssim_img2 = fastmri.SSIMLoss()
        self.loss_ssim_img3 = fastmri.SSIMLoss()
        self.loss_ssim_img4 = fastmri.SSIMLoss()
        self.loss_ssim_img5 = fastmri.SSIMLoss()
        # self.loss_l1_img1 = torch.nn.L1Loss()
        # self.loss_l1_img2 = torch.nn.L1Loss()
        # self.loss_l1_img3 = torch.nn.L1Loss()
        # self.loss_l1_img4 = torch.nn.L1Loss()
        # self.loss_l1_img5 = torch.nn.L1Loss()
        self.loss_ssim_fin_img1 = fastmri.SSIMLoss()
        self.loss_ssim_fin_img2 = fastmri.SSIMLoss()
        self.loss_ssim_fin_img3 = fastmri.SSIMLoss()
        self.loss_ssim_fin_img4 = fastmri.SSIMLoss()
        self.loss_ssim_fin_img5 = fastmri.SSIMLoss()

    def forward(self, masked_kspace_acq1, masked_kspace_acq2, masked_kspace_acq3, masked_kspace_acq4, masked_kspace_acq5, \
                mask_acq1, mask_acq2, mask_acq3, mask_acq4, mask_acq5, mask_brain, coil_sens, b1, \
                max_value_t1, max_value_t2, max_value_pd, max_value_ie, num_low_frequencies):
        return self.qalas(masked_kspace_acq1, masked_kspace_acq2, masked_kspace_acq3, masked_kspace_acq4, masked_kspace_acq5, \
                        mask_acq1, mask_acq2, mask_acq3, mask_acq4, mask_acq5, mask_brain, coil_sens, \
                        max_value_t1, max_value_t2, max_value_pd, max_value_ie, num_low_frequencies)

    def training_step(self, batch, batch_idx):
        output_t1, output_t2, output_pd, output_ie, \
        output_img1, output_img2, output_img3, output_img4, output_img5, \
        output_fin_img1, output_fin_img2, output_fin_img3, output_fin_img4, output_fin_img5 = \
            self(batch.masked_kspace_acq1, batch.masked_kspace_acq2, batch.masked_kspace_acq3, batch.masked_kspace_acq4, batch.masked_kspace_acq5, \
                batch.mask_acq1, batch.mask_acq2, batch.mask_acq3, batch.mask_acq4, batch.mask_acq5, batch.mask_brain, \
                batch.coil_sens, batch.b1, \
                batch.max_value_t1, batch.max_value_t2, batch.max_value_pd, batch.max_value_ie, batch.num_low_frequencies)

        img_acq1 = fastmri.complex_abs(fastmri.complex_mul(fastmri.ifft2c(batch.masked_kspace_acq1), fastmri.complex_conj(batch.coil_sens)).sum(dim=1, keepdim=True)) / np.sqrt(batch.masked_kspace_acq1.shape[2] * batch.masked_kspace_acq1.shape[3])
        img_acq2 = fastmri.complex_abs(fastmri.complex_mul(fastmri.ifft2c(batch.masked_kspace_acq2), fastmri.complex_conj(batch.coil_sens)).sum(dim=1, keepdim=True)) / np.sqrt(batch.masked_kspace_acq2.shape[2] * batch.masked_kspace_acq2.shape[3])
        img_acq3 = fastmri.complex_abs(fastmri.complex_mul(fastmri.ifft2c(batch.masked_kspace_acq3), fastmri.complex_conj(batch.coil_sens)).sum(dim=1, keepdim=True)) / np.sqrt(batch.masked_kspace_acq3.shape[2] * batch.masked_kspace_acq3.shape[3])
        img_acq4 = fastmri.complex_abs(fastmri.complex_mul(fastmri.ifft2c(batch.masked_kspace_acq4), fastmri.complex_conj(batch.coil_sens)).sum(dim=1, keepdim=True)) / np.sqrt(batch.masked_kspace_acq4.shape[2] * batch.masked_kspace_acq4.shape[3])
        img_acq5 = fastmri.complex_abs(fastmri.complex_mul(fastmri.ifft2c(batch.masked_kspace_acq5), fastmri.complex_conj(batch.coil_sens)).sum(dim=1, keepdim=True)) / np.sqrt(batch.masked_kspace_acq5.shape[2] * batch.masked_kspace_acq5.shape[3])

        target_t1, output_t1 = transforms_qalas.center_crop_to_smallest(batch.target_t1, output_t1)
        target_t2, output_t2 = transforms_qalas.center_crop_to_smallest(batch.target_t2, output_t2)
        target_pd, output_pd = transforms_qalas.center_crop_to_smallest(batch.target_pd, output_pd)
        target_ie, output_ie = transforms_qalas.center_crop_to_smallest(batch.target_ie, output_ie)

        target_t1, img_acq1 = transforms_qalas.center_crop_to_smallest(batch.target_t1, img_acq1.squeeze(1))
        target_t1, img_acq2 = transforms_qalas.center_crop_to_smallest(batch.target_t1, img_acq2.squeeze(1))
        target_t1, img_acq3 = transforms_qalas.center_crop_to_smallest(batch.target_t1, img_acq3.squeeze(1))
        target_t1, img_acq4 = transforms_qalas.center_crop_to_smallest(batch.target_t1, img_acq4.squeeze(1))
        target_t1, img_acq5 = transforms_qalas.center_crop_to_smallest(batch.target_t1, img_acq5.squeeze(1))

        target_t1, output_img1 = transforms_qalas.center_crop_to_smallest(batch.target_t1, output_img1.squeeze(1))
        target_t1, output_img2 = transforms_qalas.center_crop_to_smallest(batch.target_t1, output_img2.squeeze(1))
        target_t1, output_img3 = transforms_qalas.center_crop_to_smallest(batch.target_t1, output_img3.squeeze(1))
        target_t1, output_img4 = transforms_qalas.center_crop_to_smallest(batch.target_t1, output_img4.squeeze(1))
        target_t1, output_img5 = transforms_qalas.center_crop_to_smallest(batch.target_t1, output_img5.squeeze(1))

        target_t1, output_fin_img1 = transforms_qalas.center_crop_to_smallest(batch.target_t1, output_fin_img1.squeeze(1))
        target_t1, output_fin_img2 = transforms_qalas.center_crop_to_smallest(batch.target_t1, output_fin_img2.squeeze(1))
        target_t1, output_fin_img3 = transforms_qalas.center_crop_to_smallest(batch.target_t1, output_fin_img3.squeeze(1))
        target_t1, output_fin_img4 = transforms_qalas.center_crop_to_smallest(batch.target_t1, output_fin_img4.squeeze(1))
        target_t1, output_fin_img5 = transforms_qalas.center_crop_to_smallest(batch.target_t1, output_fin_img5.squeeze(1))

        target_t1 = target_t1 * batch.mask_brain
        target_t2 = target_t2 * batch.mask_brain
        target_pd = target_pd * batch.mask_brain
        target_ie = target_ie * batch.mask_brain

        output_t1 = output_t1 * batch.mask_brain
        output_t2 = output_t2 * batch.mask_brain
        output_pd = output_pd * batch.mask_brain
        output_ie = output_ie * batch.mask_brain

        img_acq1 = img_acq1 * batch.mask_brain
        img_acq2 = img_acq2 * batch.mask_brain
        img_acq3 = img_acq3 * batch.mask_brain
        img_acq4 = img_acq4 * batch.mask_brain
        img_acq5 = img_acq5 * batch.mask_brain

        output_img1 = output_img1 * batch.mask_brain
        output_img2 = output_img2 * batch.mask_brain
        output_img3 = output_img3 * batch.mask_brain
        output_img4 = output_img4 * batch.mask_brain
        output_img5 = output_img5 * batch.mask_brain

        output_fin_img1 = output_fin_img1 * batch.mask_brain
        output_fin_img2 = output_fin_img2 * batch.mask_brain
        output_fin_img3 = output_fin_img3 * batch.mask_brain
        output_fin_img4 = output_fin_img4 * batch.mask_brain
        output_fin_img5 = output_fin_img5 * batch.mask_brain

        if batch.mask_brain.sum() == 0:
            target_t1 = target_t1 + 1e-5
            target_t2 = target_t2 + 1e-5
            target_pd = target_pd + 1e-5
            target_ie = target_ie + 1e-5
            output_t1 = output_t1 + 1e-5
            output_t2 = output_t2 + 1e-5
            output_pd = output_pd + 1e-5
            output_ie = output_ie + 1e-5
            img_acq1 = img_acq1 + 1e-5
            img_acq2 = img_acq2 + 1e-5
            img_acq3 = img_acq3 + 1e-5
            img_acq4 = img_acq4 + 1e-5
            img_acq5 = img_acq5 + 1e-5
            output_img1 = output_img1 + 1e-5
            output_img2 = output_img2 + 1e-5
            output_img3 = output_img3 + 1e-5
            output_img4 = output_img4 + 1e-5
            output_img5 = output_img5 + 1e-5
            output_fin_img1 = output_fin_img1 + 1e-5
            output_fin_img2 = output_fin_img2 + 1e-5
            output_fin_img3 = output_fin_img3 + 1e-5
            output_fin_img4 = output_fin_img4 + 1e-5
            output_fin_img5 = output_fin_img5 + 1e-5

        loss_t1 = self.loss_ssim_t1(output_t1.unsqueeze(1), target_t1.unsqueeze(1), data_range=batch.max_value_t1)
        loss_t2 = self.loss_ssim_t2(output_t2.unsqueeze(1), target_t2.unsqueeze(1), data_range=batch.max_value_t2)
        loss_pd = self.loss_ssim_pd(output_pd.unsqueeze(1), target_pd.unsqueeze(1), data_range=batch.max_value_pd)
        loss_ie = self.loss_ssim_ie(output_ie.unsqueeze(1), target_ie.unsqueeze(1), data_range=batch.max_value_ie)
        loss_img1 = self.loss_ssim_img1(output_img1.unsqueeze(1), img_acq1.unsqueeze(1), data_range=torch.ones_like(batch.max_value_t1)*img_acq1.max())
        loss_img2 = self.loss_ssim_img2(output_img2.unsqueeze(1), img_acq2.unsqueeze(1), data_range=torch.ones_like(batch.max_value_t1)*img_acq2.max())
        loss_img3 = self.loss_ssim_img3(output_img3.unsqueeze(1), img_acq3.unsqueeze(1), data_range=torch.ones_like(batch.max_value_t1)*img_acq3.max())
        loss_img4 = self.loss_ssim_img4(output_img4.unsqueeze(1), img_acq4.unsqueeze(1), data_range=torch.ones_like(batch.max_value_t1)*img_acq4.max())
        loss_img5 = self.loss_ssim_img5(output_img5.unsqueeze(1), img_acq5.unsqueeze(1), data_range=torch.ones_like(batch.max_value_t1)*img_acq5.max())
        # loss_img1 = self.loss_l1_img1(output_img1.unsqueeze(1), img_acq1.unsqueeze(1))
        # loss_img2 = self.loss_l1_img2(output_img2.unsqueeze(1), img_acq2.unsqueeze(1))
        # loss_img3 = self.loss_l1_img3(output_img3.unsqueeze(1), img_acq3.unsqueeze(1))
        # loss_img4 = self.loss_l1_img4(output_img4.unsqueeze(1), img_acq4.unsqueeze(1))
        # loss_img5 = self.loss_l1_img5(output_img5.unsqueeze(1), img_acq5.unsqueeze(1))
        loss_fin_img1 = self.loss_ssim_fin_img1(output_fin_img1.unsqueeze(1), img_acq1.unsqueeze(1), data_range=torch.ones_like(batch.max_value_t1)*img_acq1.max())
        loss_fin_img2 = self.loss_ssim_fin_img2(output_fin_img2.unsqueeze(1), img_acq2.unsqueeze(1), data_range=torch.ones_like(batch.max_value_t1)*img_acq2.max())
        loss_fin_img3 = self.loss_ssim_fin_img3(output_fin_img3.unsqueeze(1), img_acq3.unsqueeze(1), data_range=torch.ones_like(batch.max_value_t1)*img_acq3.max())
        loss_fin_img4 = self.loss_ssim_fin_img4(output_fin_img4.unsqueeze(1), img_acq4.unsqueeze(1), data_range=torch.ones_like(batch.max_value_t1)*img_acq4.max())
        loss_fin_img5 = self.loss_ssim_fin_img5(output_fin_img5.unsqueeze(1), img_acq5.unsqueeze(1), data_range=torch.ones_like(batch.max_value_t1)*img_acq5.max())
        loss_weight_t1 = 1
        loss_weight_t2 = 1
        loss_weight_pd = 1
        loss_weight_ie = 1
        loss_weight_img1 = 1
        loss_weight_img2 = 1
        loss_weight_img3 = 1
        loss_weight_img4 = 1
        loss_weight_img5 = 1
        loss_weight_fin_img1 = 1
        loss_weight_fin_img2 = 1
        loss_weight_fin_img3 = 1
        loss_weight_fin_img4 = 1
        loss_weight_fin_img5 = 1
        loss = (loss_t1 * loss_weight_t1 + loss_t2 * loss_weight_t2 + loss_pd * loss_weight_pd + loss_ie * loss_weight_ie + \
                loss_img1 * loss_weight_img1 + loss_img2 * loss_weight_img2 + loss_img3 * loss_weight_img3 + loss_img4 * loss_weight_img4 + loss_img5 * loss_weight_img5 + \
                loss_fin_img1 * loss_weight_fin_img1 + loss_fin_img2 * loss_weight_fin_img2 + loss_fin_img3 * loss_weight_fin_img3 + loss_fin_img4 * loss_weight_fin_img4 + loss_fin_img5 * loss_weight_fin_img5) \
                 / (loss_weight_t1 + loss_weight_t2 + loss_weight_pd + loss_weight_ie + \
                    loss_weight_img1 + loss_weight_img2 + loss_weight_img3 + loss_weight_img4 + loss_weight_img5 + \
                    loss_weight_fin_img1 + loss_weight_fin_img2 + loss_weight_fin_img3 + loss_weight_fin_img4 + loss_weight_fin_img5)

        self.log("train_loss_t1", loss_t1)
        self.log("train_loss_t2", loss_t2)
        self.log("train_loss_pd", loss_pd)
        self.log("train_loss_ie", loss_ie)
        self.log("train_loss_img1", loss_img1)
        self.log("train_loss_img2", loss_img2)
        self.log("train_loss_img3", loss_img3)
        self.log("train_loss_img4", loss_img4)
        self.log("train_loss_img5", loss_img5)
        self.log("train_loss_fin_img1", loss_fin_img1)
        self.log("train_loss_fin_img2", loss_fin_img2)
        self.log("train_loss_fin_img3", loss_fin_img3)
        self.log("train_loss_fin_img4", loss_fin_img4)
        self.log("train_loss_fin_img5", loss_fin_img5)

        return loss


    def validation_step(self, batch, batch_idx):
        output_t1, output_t2, output_pd, output_ie, \
        output_img1, output_img2, output_img3, output_img4, output_img5, \
        output_fin_img1, output_fin_img2, output_fin_img3, output_fin_img4, output_fin_img5 = \
            self.forward(batch.masked_kspace_acq1, batch.masked_kspace_acq2, batch.masked_kspace_acq3, batch.masked_kspace_acq4, batch.masked_kspace_acq5, \
                        batch.mask_acq1, batch.mask_acq2, batch.mask_acq3, batch.mask_acq4, batch.mask_acq5, batch.mask_brain, \
                        batch.coil_sens, batch.b1, \
                        batch.max_value_t1, batch.max_value_t2, batch.max_value_pd, batch.max_value_ie, batch.num_low_frequencies)

        img_acq1 = fastmri.complex_abs(fastmri.complex_mul(fastmri.ifft2c(batch.masked_kspace_acq1), fastmri.complex_conj(batch.coil_sens)).sum(dim=1, keepdim=True)) / np.sqrt(batch.masked_kspace_acq1.shape[2] * batch.masked_kspace_acq1.shape[3])
        img_acq2 = fastmri.complex_abs(fastmri.complex_mul(fastmri.ifft2c(batch.masked_kspace_acq2), fastmri.complex_conj(batch.coil_sens)).sum(dim=1, keepdim=True)) / np.sqrt(batch.masked_kspace_acq2.shape[2] * batch.masked_kspace_acq2.shape[3])
        img_acq3 = fastmri.complex_abs(fastmri.complex_mul(fastmri.ifft2c(batch.masked_kspace_acq3), fastmri.complex_conj(batch.coil_sens)).sum(dim=1, keepdim=True)) / np.sqrt(batch.masked_kspace_acq3.shape[2] * batch.masked_kspace_acq3.shape[3])
        img_acq4 = fastmri.complex_abs(fastmri.complex_mul(fastmri.ifft2c(batch.masked_kspace_acq4), fastmri.complex_conj(batch.coil_sens)).sum(dim=1, keepdim=True)) / np.sqrt(batch.masked_kspace_acq4.shape[2] * batch.masked_kspace_acq4.shape[3])
        img_acq5 = fastmri.complex_abs(fastmri.complex_mul(fastmri.ifft2c(batch.masked_kspace_acq5), fastmri.complex_conj(batch.coil_sens)).sum(dim=1, keepdim=True)) / np.sqrt(batch.masked_kspace_acq5.shape[2] * batch.masked_kspace_acq5.shape[3])

        target_t1, output_t1 = transforms_qalas.center_crop_to_smallest(batch.target_t1, output_t1)
        target_t2, output_t2 = transforms_qalas.center_crop_to_smallest(batch.target_t2, output_t2)
        target_pd, output_pd = transforms_qalas.center_crop_to_smallest(batch.target_pd, output_pd)
        target_ie, output_ie = transforms_qalas.center_crop_to_smallest(batch.target_ie, output_ie)

        target_t1, img_acq1 = transforms_qalas.center_crop_to_smallest(batch.target_t1, img_acq1.squeeze(1))
        target_t1, img_acq2 = transforms_qalas.center_crop_to_smallest(batch.target_t1, img_acq2.squeeze(1))
        target_t1, img_acq3 = transforms_qalas.center_crop_to_smallest(batch.target_t1, img_acq3.squeeze(1))
        target_t1, img_acq4 = transforms_qalas.center_crop_to_smallest(batch.target_t1, img_acq4.squeeze(1))
        target_t1, img_acq5 = transforms_qalas.center_crop_to_smallest(batch.target_t1, img_acq5.squeeze(1))

        target_t1, output_img1 = transforms_qalas.center_crop_to_smallest(batch.target_t1, output_img1.squeeze(1))
        target_t1, output_img2 = transforms_qalas.center_crop_to_smallest(batch.target_t1, output_img2.squeeze(1))
        target_t1, output_img3 = transforms_qalas.center_crop_to_smallest(batch.target_t1, output_img3.squeeze(1))
        target_t1, output_img4 = transforms_qalas.center_crop_to_smallest(batch.target_t1, output_img4.squeeze(1))
        target_t1, output_img5 = transforms_qalas.center_crop_to_smallest(batch.target_t1, output_img5.squeeze(1))

        target_t1, output_fin_img1 = transforms_qalas.center_crop_to_smallest(batch.target_t1, output_fin_img1.squeeze(1))
        target_t1, output_fin_img2 = transforms_qalas.center_crop_to_smallest(batch.target_t1, output_fin_img2.squeeze(1))
        target_t1, output_fin_img3 = transforms_qalas.center_crop_to_smallest(batch.target_t1, output_fin_img3.squeeze(1))
        target_t1, output_fin_img4 = transforms_qalas.center_crop_to_smallest(batch.target_t1, output_fin_img4.squeeze(1))
        target_t1, output_fin_img5 = transforms_qalas.center_crop_to_smallest(batch.target_t1, output_fin_img5.squeeze(1))

        target_t1 = target_t1 * batch.mask_brain
        target_t2 = target_t2 * batch.mask_brain
        target_pd = target_pd * batch.mask_brain
        target_ie = target_ie * batch.mask_brain

        output_t1 = output_t1 * batch.mask_brain
        output_t2 = output_t2 * batch.mask_brain
        output_pd = output_pd * batch.mask_brain
        output_ie = output_ie * batch.mask_brain

        img_acq1 = img_acq1 * batch.mask_brain
        img_acq2 = img_acq2 * batch.mask_brain
        img_acq3 = img_acq3 * batch.mask_brain
        img_acq4 = img_acq4 * batch.mask_brain
        img_acq5 = img_acq5 * batch.mask_brain

        output_img1 = output_img1 * batch.mask_brain
        output_img2 = output_img2 * batch.mask_brain
        output_img3 = output_img3 * batch.mask_brain
        output_img4 = output_img4 * batch.mask_brain
        output_img5 = output_img5 * batch.mask_brain

        output_fin_img1 = output_fin_img1 * batch.mask_brain
        output_fin_img2 = output_fin_img2 * batch.mask_brain
        output_fin_img3 = output_fin_img3 * batch.mask_brain
        output_fin_img4 = output_fin_img4 * batch.mask_brain
        output_fin_img5 = output_fin_img5 * batch.mask_brain

        ### Temp. ###
        import scipy.io
        scipy.io.savemat('/autofs/space/marduk_003/users/yohan/python_code/fastMRI/qalas/qalas_log/recon_check/masked_kspace_check.mat', \
                        mdict={'masked_kspace_acq1':np.squeeze(transforms_qalas.tensor_to_complex_np(batch.masked_kspace_acq1.cpu())), \
                                'masked_kspace_acq2':np.squeeze(transforms_qalas.tensor_to_complex_np(batch.masked_kspace_acq2.cpu())), \
                                'masked_kspace_acq3':np.squeeze(transforms_qalas.tensor_to_complex_np(batch.masked_kspace_acq3.cpu())), \
                                'masked_kspace_acq4':np.squeeze(transforms_qalas.tensor_to_complex_np(batch.masked_kspace_acq4.cpu())), \
                                'masked_kspace_acq5':np.squeeze(transforms_qalas.tensor_to_complex_np(batch.masked_kspace_acq5.cpu()))})
        scipy.io.savemat('/autofs/space/marduk_003/users/yohan/python_code/fastMRI/qalas/qalas_log/recon_check/target_init_img_check.mat', \
                            mdict={'target_img1':np.squeeze(img_acq1.cpu().numpy()), 'target_img2':np.squeeze(img_acq2.cpu().numpy()), \
                                    'target_img3':np.squeeze(img_acq3.cpu().numpy()), 'target_img4':np.squeeze(img_acq4.cpu().numpy()), \
                                    'target_img5':np.squeeze(img_acq5.cpu().numpy())})
        scipy.io.savemat('/autofs/space/marduk_003/users/yohan/python_code/fastMRI/qalas/qalas_log/recon_check/output_init_img_check.mat', \
                            mdict={'output_img1':np.squeeze(output_img1.cpu().numpy()), 'output_img2':np.squeeze(output_img2.cpu().numpy()), \
                                    'output_img3':np.squeeze(output_img3.cpu().numpy()), 'output_img4':np.squeeze(output_img4.cpu().numpy()), \
                                    'output_img5':np.squeeze(output_img5.cpu().numpy())})
        scipy.io.savemat('/autofs/space/marduk_003/users/yohan/python_code/fastMRI/qalas/qalas_log/recon_check/output_fin_img_check.mat', \
                            mdict={'output_fin_img1':np.squeeze(output_fin_img1.cpu().numpy()), 'output_fin_img2':np.squeeze(output_fin_img2.cpu().numpy()), \
                                    'output_fin_img3':np.squeeze(output_fin_img3.cpu().numpy()), 'output_fin_img4':np.squeeze(output_fin_img4.cpu().numpy()), \
                                    'output_fin_img5':np.squeeze(output_fin_img5.cpu().numpy())})
        scipy.io.savemat('/autofs/space/marduk_003/users/yohan/python_code/fastMRI/qalas/qalas_log/recon_check/target_check.mat', \
                            mdict={'target_t1':np.squeeze(target_t1.cpu().numpy()), 'target_t2':np.squeeze(target_t2.cpu().numpy()), 'target_pd':np.squeeze(target_pd.cpu().numpy()), 'target_ie':np.squeeze(target_ie.cpu().numpy())})
        scipy.io.savemat('/autofs/space/marduk_003/users/yohan/python_code/fastMRI/qalas/qalas_log/recon_check/output_check.mat', \
                            mdict={'output_t1':np.squeeze(output_t1.cpu().numpy()), 'output_t2':np.squeeze(output_t2.cpu().numpy()), 'output_pd':np.squeeze(output_pd.cpu().numpy()), 'output_ie':np.squeeze(output_ie.cpu().numpy())})
        ###

        loss_weight_t1 = 1
        loss_weight_t2 = 1
        loss_weight_pd = 1
        loss_weight_ie = 1
        loss_weight_img1 = 1
        loss_weight_img2 = 1
        loss_weight_img3 = 1
        loss_weight_img4 = 1
        loss_weight_img5 = 1
        loss_weight_fin_img1 = 1
        loss_weight_fin_img2 = 1
        loss_weight_fin_img3 = 1
        loss_weight_fin_img4 = 1
        loss_weight_fin_img5 = 1

        return {
            "batch_idx": batch_idx,
            "fname": batch.fname,
            "slice_num": batch.slice_num,
            "max_value_t1": batch.max_value_t1,
            "max_value_t2": batch.max_value_t2,
            "max_value_pd": batch.max_value_pd,
            "max_value_ie": batch.max_value_ie,
            "output_t1": output_t1,
            "output_t2": output_t2,
            "output_pd": output_pd,
            "output_ie": output_ie,
            "output_img1": output_img1,
            "output_img2": output_img2,
            "output_img3": output_img3,
            "output_img4": output_img4,
            "output_img5": output_img5,
            "output_fin_img1": output_fin_img1,
            "output_fin_img2": output_fin_img2,
            "output_fin_img3": output_fin_img3,
            "output_fin_img4": output_fin_img4,
            "output_fin_img5": output_fin_img5,
            "target_t1": target_t1,
            "target_t2": target_t2,
            "target_pd": target_pd,
            "target_ie": target_ie,
            "target_img1": img_acq1,
            "target_img2": img_acq2,
            "target_img3": img_acq3,
            "target_img4": img_acq4,
            "target_img5": img_acq5,
            "val_loss_t1": self.loss_ssim_t1(output_t1.unsqueeze(1), target_t1.unsqueeze(1), data_range=batch.max_value_t1),
            "val_loss_t2": self.loss_ssim_t2(output_t2.unsqueeze(1), target_t2.unsqueeze(1), data_range=batch.max_value_t2),
            "val_loss_pd": self.loss_ssim_pd(output_pd.unsqueeze(1), target_pd.unsqueeze(1), data_range=batch.max_value_pd),
            "val_loss_ie": self.loss_ssim_ie(output_ie.unsqueeze(1), target_ie.unsqueeze(1), data_range=batch.max_value_ie),
            "val_loss_img1": self.loss_ssim_img1(output_img1.unsqueeze(1), img_acq1.unsqueeze(1), data_range=torch.ones_like(batch.max_value_t1)*img_acq1.max()),
            "val_loss_img2": self.loss_ssim_img2(output_img2.unsqueeze(1), img_acq2.unsqueeze(1), data_range=torch.ones_like(batch.max_value_t1)*img_acq2.max()),
            "val_loss_img3": self.loss_ssim_img3(output_img3.unsqueeze(1), img_acq3.unsqueeze(1), data_range=torch.ones_like(batch.max_value_t1)*img_acq3.max()),
            "val_loss_img4": self.loss_ssim_img4(output_img4.unsqueeze(1), img_acq4.unsqueeze(1), data_range=torch.ones_like(batch.max_value_t1)*img_acq4.max()),
            "val_loss_img5": self.loss_ssim_img5(output_img5.unsqueeze(1), img_acq5.unsqueeze(1), data_range=torch.ones_like(batch.max_value_t1)*img_acq5.max()),
            # "val_loss_img1": self.loss_l1_img1(output_img1.unsqueeze(1), img_acq1.unsqueeze(1)),
            # "val_loss_img2": self.loss_l1_img2(output_img2.unsqueeze(1), img_acq2.unsqueeze(1)),
            # "val_loss_img3": self.loss_l1_img3(output_img3.unsqueeze(1), img_acq3.unsqueeze(1)),
            # "val_loss_img4": self.loss_l1_img4(output_img4.unsqueeze(1), img_acq4.unsqueeze(1)),
            # "val_loss_img5": self.loss_l1_img5(output_img5.unsqueeze(1), img_acq5.unsqueeze(1)),
            "val_loss_fin_img1": self.loss_ssim_img1(output_fin_img1.unsqueeze(1), img_acq1.unsqueeze(1), data_range=torch.ones_like(batch.max_value_t1)*img_acq1.max()),
            "val_loss_fin_img2": self.loss_ssim_img2(output_fin_img2.unsqueeze(1), img_acq2.unsqueeze(1), data_range=torch.ones_like(batch.max_value_t1)*img_acq2.max()),
            "val_loss_fin_img3": self.loss_ssim_img3(output_fin_img3.unsqueeze(1), img_acq3.unsqueeze(1), data_range=torch.ones_like(batch.max_value_t1)*img_acq3.max()),
            "val_loss_fin_img4": self.loss_ssim_img4(output_fin_img4.unsqueeze(1), img_acq4.unsqueeze(1), data_range=torch.ones_like(batch.max_value_t1)*img_acq4.max()),
            "val_loss_fin_img5": self.loss_ssim_img5(output_fin_img5.unsqueeze(1), img_acq5.unsqueeze(1), data_range=torch.ones_like(batch.max_value_t1)*img_acq5.max()),
            "loss_weight_t1": loss_weight_t1,
            "loss_weight_t2": loss_weight_t2,
            "loss_weight_pd": loss_weight_pd,
            "loss_weight_ie": loss_weight_ie,
            "loss_weight_img1": loss_weight_img1,
            "loss_weight_img2": loss_weight_img2,
            "loss_weight_img3": loss_weight_img3,
            "loss_weight_img4": loss_weight_img4,
            "loss_weight_img5": loss_weight_img5,
            "loss_weight_fin_img1": loss_weight_fin_img1,
            "loss_weight_fin_img2": loss_weight_fin_img2,
            "loss_weight_fin_img3": loss_weight_fin_img3,
            "loss_weight_fin_img4": loss_weight_fin_img4,
            "loss_weight_fin_img5": loss_weight_fin_img5,
        }


    def test_step(self, batch, batch_idx):
        output_t1, output_t2, output_pd, output_ie, \
        output_img1, output_img2, output_img3, output_img4, output_img5, \
        output_fin_img1, output_fin_img2, output_fin_img3, output_fin_img4, output_fin_img5 = \
            self(batch.masked_kspace_acq1, batch.masked_kspace_acq2, batch.masked_kspace_acq3, batch.masked_kspace_acq4, batch.masked_kspace_acq5, \
                batch.mask_acq1, batch.mask_acq2, batch.mask_acq3, batch.mask_acq4, batch.mask_acq5, batch.mask_brain, \
                batch.coil_sens, batch.b1, \
                batch.max_value_t1, batch.max_value_t2, batch.max_value_pd, batch.max_value_ie, batch.num_low_frequencies)

        # check for FLAIR 203
        if output_t1.shape[-1] < batch.crop_size[1]:
            crop_size = (output_t1.shape[-1], output_t1.shape[-1])
        else:
            crop_size = batch.crop_size

        output_t1 = transforms_qalas.center_crop(output_t1, crop_size)
        output_t2 = transforms_qalas.center_crop(output_t2, crop_size)
        output_pd = transforms_qalas.center_crop(output_pd, crop_size)
        output_ie = transforms_qalas.center_crop(output_ie, crop_size)

        output_t1 = output_t1 * batch.mask_brain
        output_t2 = output_t2 * batch.mask_brain
        output_pd = output_pd * batch.mask_brain
        output_ie = output_ie * batch.mask_brain

        return {
            "fname": batch.fname,
            "slice": batch.slice_num,
            "output_t1": output_t1.cpu().numpy(),
            "output_t2": output_t2.cpu().numpy(),
            "output_pd": output_pd.cpu().numpy(),
            "output_ie": output_ie.cpu().numpy(),
        }

    def configure_optimizers(self):
        optim = torch.optim.Adam(
            self.parameters(), lr=self.lr, weight_decay=self.weight_decay
        )
        scheduler = torch.optim.lr_scheduler.StepLR(
            optim, self.lr_step_size, self.lr_gamma
        )

        return [optim], [scheduler]

    @staticmethod
    def add_model_specific_args(parent_parser):  # pragma: no-cover
        """
        Define parameters that only apply to this model
        """
        parser = ArgumentParser(parents=[parent_parser], add_help=False)
        parser = MriModuleQALAS.add_model_specific_args(parser)

        # param overwrites

        # network params
        parser.add_argument(
            "--num_cascades",
            default=12,
            type=int,
            help="Number of QALAS cascades",
        )
        parser.add_argument(
            "--pools",
            default=4,
            type=int,
            help="Number of U-Net pooling layers in QALAS blocks",
        )
        parser.add_argument(
            "--chans",
            default=18,
            type=int,
            help="Number of channels for U-Net in QALAS blocks",
        )
        parser.add_argument(
            "--sens_pools",
            default=4,
            type=int,
            help="Number of pooling layers for sense map estimation U-Net in QALAS",
        )
        parser.add_argument(
            "--sens_chans",
            default=8,
            type=float,
            help="Number of channels for sense map estimation U-Net in QALAS",
        )
        parser.add_argument(
            "--maps_chans",
            default=32,
            type=int,
            help="Number of channels for mapping CNN in QALAS",
        )
        parser.add_argument(
            "--maps_layers",
            default=5,
            type=float,
            help="Number of layers for mapping CNN in QALAS",
        )

        # training params (opt)
        parser.add_argument(
            "--lr", default=0.0003, type=float, help="Adam learning rate"
        )
        parser.add_argument(
            "--lr_step_size",
            default=40,
            type=int,
            help="Epoch at which to decrease step size",
        )
        parser.add_argument(
            "--lr_gamma",
            default=0.1,
            type=float,
            help="Extent to which step size should be decreased",
        )
        parser.add_argument(
            "--weight_decay",
            default=0.0,
            type=float,
            help="Strength of weight decay regularization",
        )

        return parser
