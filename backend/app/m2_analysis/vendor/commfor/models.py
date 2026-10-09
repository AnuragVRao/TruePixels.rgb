"""Community Forensics classifier - vendored from
github.com/JeongsooP/Community-Forensics @ ee5b71d43db0f3779e1edd64ee927b13f2dd6ad4,
models.py, MIT licence (see LICENSE). Edits are listed in NOTICE; none changes
the arithmetic of the forward pass.
"""

import torch
import torch.nn as nn
import timm


class ViTClassifier(nn.Module):
    # TruePixels: PyTorchModelHubMixin removed (weights are loaded strictly from
    # a digest-checked safetensors file by app/m2_analysis/detectors.py, never
    # via from_pretrained).
    def __init__(self,
                 model_size="small",
                 input_size=384,
                 patch_size=16,
                 device='cpu', dtype=torch.float32):
        """
        ViT Classifier based on huggingface timm module
        """
        super(ViTClassifier, self).__init__()
        self.device = device
        self.dtype = dtype
        # TruePixels: only the configuration of the released checkpoint
        # (small / 384 / 16) is kept, and pretrained=False - upstream used
        # pretrained=True to start TRAINING from ImageNet weights; for
        # inference every tensor is overwritten by the checkpoint, so nothing
        # is downloaded. freeze_backbone (a training option) removed.
        if not (model_size == "small" and input_size == 384 and patch_size == 16):
            raise ValueError("only the released configuration (small, 384, patch 16) is vendored")
        self.vit = timm.create_model('vit_small_patch16_384.augreg_in21k_ft_in1k', pretrained=False).to(device)
        self.vit.head = nn.Linear(in_features=384, out_features=1, bias=True, device=device, dtype=dtype)

    def forward(self, x):
        return self.vit(x)
