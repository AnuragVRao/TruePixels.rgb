# TruePixels: this file is NOT from upstream. It provides the handful of
# symbols the vendored SPAI code imports from timm, torchvision and einops, so
# that none of those packages is a dependency of the inference path.
#
# Each replacement is the standard definition of the thing it replaces. They
# are used only in eval mode, where DropPath is the identity anyway.

from __future__ import annotations

import collections.abc
from itertools import repeat

import torch
from torch import nn

# timm.data.IMAGENET_DEFAULT_MEAN / IMAGENET_DEFAULT_STD
IMAGENET_DEFAULT_MEAN = (0.485, 0.456, 0.406)
IMAGENET_DEFAULT_STD = (0.229, 0.224, 0.225)


def to_2tuple(value):
    """timm.models.layers.to_2tuple."""
    if isinstance(value, collections.abc.Iterable) and not isinstance(value, str):
        return tuple(value)
    return tuple(repeat(value, 2))


def trunc_normal_(tensor: torch.Tensor, mean: float = 0.0, std: float = 1.0,
                  a: float = -2.0, b: float = 2.0) -> torch.Tensor:
    """timm.models.layers.trunc_normal_ - same call as torch's own.

    Only ever reached during construction; every tensor it touches is then
    overwritten by the checkpoint under a strict load.
    """
    return nn.init.trunc_normal_(tensor, mean=mean, std=std, a=a, b=b)


class DropPath(nn.Module):
    """timm.models.layers.DropPath (stochastic depth). Identity in eval mode."""

    def __init__(self, drop_prob: float = 0.0) -> None:
        super().__init__()
        self.drop_prob = drop_prob

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if self.drop_prob == 0.0 or not self.training:
            return x
        keep_prob = 1.0 - self.drop_prob
        shape = (x.shape[0],) + (1,) * (x.ndim - 1)
        mask = x.new_empty(shape).bernoulli_(keep_prob)
        return x * mask / keep_prob


class Normalize(nn.Module):
    """torchvision.transforms.Normalize for a (B, C, H, W) or (C, H, W) tensor."""

    def __init__(self, mean, std) -> None:
        super().__init__()
        self.register_buffer("mean", torch.tensor(mean, dtype=torch.float32).view(-1, 1, 1),
                             persistent=False)
        self.register_buffer("std", torch.tensor(std, dtype=torch.float32).view(-1, 1, 1),
                             persistent=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return (x - self.mean.to(x.dtype)) / self.std.to(x.dtype)


def five_crop(img: torch.Tensor, size: list[int]) -> tuple[torch.Tensor, ...]:
    """torchvision.transforms.functional.five_crop for a (..., H, W) tensor.

    Returns (top-left, top-right, bottom-left, bottom-right, centre), in the
    order torchvision uses.
    """
    crop_height, crop_width = int(size[0]), int(size[1])
    height, width = img.shape[-2], img.shape[-1]
    if crop_width > width or crop_height > height:
        raise ValueError(
            f"Requested crop size {size} is bigger than input size {(height, width)}"
        )

    tl = img[..., :crop_height, :crop_width]
    tr = img[..., :crop_height, width - crop_width:]
    bl = img[..., height - crop_height:, :crop_width]
    br = img[..., height - crop_height:, width - crop_width:]

    top = int(round((height - crop_height) / 2.0))
    left = int(round((width - crop_width) / 2.0))
    center = img[..., top:top + crop_height, left:left + crop_width]

    return tl, tr, bl, br, center
