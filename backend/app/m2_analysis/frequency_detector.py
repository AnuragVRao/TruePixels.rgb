"""FR-02 - Frequency-domain artifact detection, realised with a PRETRAINED model.

PRD2 FR-02 ends its pipeline with "a classifier over the spectral feature
vector". Training that classifier is permanently out of scope (CLAUDE.md
section 0), so for a while this branch produced features and no score. What
produces the score now is SPAI - a published, Apache-2.0 detector that asks
the same physical question FR-02 asked, with weights someone else trained:

    Karageorgiou et al., "Any-Resolution AI-Generated Image Detection by
    Spectral Learning", CVPR 2025.  https://github.com/mever-team/spai

How it works, in one paragraph. The image is tiled into 224x224 patches at
NATIVE resolution. Each patch is split by FFT into a low-pass and a high-pass
component (circular mask, radius 16). A ViT-B/16 that was pretrained by
reconstructing masked frequency bands of real images encodes the original,
the low and the high version; the cosine similarities between those encodings
- "spectral reconstruction similarity" - are the evidence. A model that has
only ever learned the spectral statistics of real images reconstructs a
generated image differently. A learned cross-attention aggregates the patches
("spectral context attention") and one logit decides.

The model code is vendored under ``vendor/spai`` exactly as published (see its
NOTICE); the weights are converted once, offline, from the authors' pickled
training checkpoint into a tensors-only safetensors file by
``scripts/convert_spai_checkpoint.py``. This module loads only that file,
verifies the weights against a pinned digest, and loads them STRICTLY - every
parameter in the architecture must be present in the file. Upstream loads
with ``strict=False``; we do not, because a lenient load that leaves a layer
randomly initialised would fail silently and plausibly, which is the one
failure shape this project refuses to tolerate.

THE SIGN CONVENTION. SPAI has no ``id2label``. It is a single-logit BCE
classifier whose training data labels generated images 1, and whose
inference script emits ``sigmoid(logit)`` as the AI probability. That is a
convention, not something the weights can tell us, so it lives in config as
``DETECTOR_FREQUENCY_AI_IS_POSITIVE`` and is checked by the smoke-image
canary in CLAUDE.md rather than assumed.

Reads ``PreprocessedImage.source_reference`` - the native original - and never
resizes by default. Contract C1 section 4.3: a downsample is a low-pass
filter, and it erases exactly the high-frequency evidence this branch exists
to find.
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from app.m2_analysis.detectors import BranchResult
from app.shared import config
from app.shared.contracts.errors import InferenceError, ModelUnavailableError

# SPAI tiles its input into 224x224 patches. Below that in either dimension
# ``Tensor.unfold`` raises, so there is no spectral evidence to be had - not a
# degraded answer, none at all. M1 accepts images down to 64px (PRD C.9), so
# this is reachable from a normal upload.
MIN_SIDE = 224


class SpectralBranchUnavailable(Exception):
    """This image cannot be scored by the frequency branch at all.

    Deliberately NOT an InferenceError: it must not fail the request. The
    caller drops to the documented passthrough - a verdict from the semantic
    branch alone, with ``frequency_score`` null - exactly as when the branch
    is switched off in config. Null is the honest answer; a fabricated number
    would not be.
    """


def weights_digest(tensors: dict[str, torch.Tensor]) -> str:
    """SHA-256 over the weights themselves: name, dtype, shape and bytes.

    Pinning the file's own hash does not work - safetensors writes its header
    metadata in arbitrary order, so two conversions of the same weights give
    two different files. What we need to pin is the weights, so this hashes
    exactly those, in sorted key order, and nothing else. Shared with the
    conversion script so both sides compute the same number.
    """
    digest = hashlib.sha256()
    for key in sorted(tensors):
        tensor = tensors[key].detach().cpu().contiguous()
        digest.update(key.encode("utf-8"))
        digest.update(str(tensor.dtype).encode("utf-8"))
        digest.update(str(tuple(tensor.shape)).encode("utf-8"))
        digest.update(tensor.numpy().tobytes())
    return digest.hexdigest()


def prepare_image(image: Image.Image, *, resize_to: int | None) -> torch.Tensor:
    """PIL image -> (1, 3, H, W) float tensor in [0, 1], as SPAI expects.

    - RGB, values scaled to [0, 1]; the model applies ImageNet normalisation
      itself, after the FFT split (``REQUIRED_NORMALIZATION: positive_0_1``).
    - No resize unless ``resize_to`` is set AND the longest side exceeds it -
      the authors' own ``--resize-to`` semantics. Never enlarges.
    - Height and width trimmed to even numbers (one row/column at most): the
      circular frequency mask is defined on an even grid.
    """
    image = image.convert("RGB")

    if resize_to is not None and max(image.size) > resize_to:
        scale = resize_to / max(image.size)
        new_size = (
            max(1, round(image.width * scale)),
            max(1, round(image.height * scale)),
        )
        image = image.resize(new_size, Image.Resampling.BICUBIC)

    array = np.asarray(image, dtype=np.float32) / 255.0  # H x W x 3
    height, width = array.shape[:2]
    array = array[: height - height % 2, : width - width % 2, :]

    tensor = torch.from_numpy(np.ascontiguousarray(array)).permute(2, 0, 1)
    return tensor.unsqueeze(0)


class SpectralDetector:
    """The cached, lazily loaded SPAI model.

    NF.4: loaded once per process, never per request. The lock guards the
    first load against concurrent requests. Mirrors ``PretrainedDetector``
    so the pipeline treats both branches alike.
    """

    def __init__(
        self,
        *,
        filename: str,
        digest: str,
        ai_is_positive: bool,
        resize_to: int | None,
        feature_batch: int,
    ) -> None:
        self.name = config.DETECTOR_FREQUENCY_NAME
        self.filename = filename
        self.digest = digest
        self.ai_is_positive = ai_is_positive
        self.resize_to = resize_to
        self.feature_batch = feature_batch
        self._lock = threading.Lock()
        self._model = None

    @property
    def path(self) -> Path:
        return config.MODELS_DIR / self.filename

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def present_on_disk(self) -> bool:
        return self.path.is_file()

    def load(self) -> None:
        """Build the architecture, verify and strictly load the weights.

        Raises:
            ModelUnavailableError: the file is missing, its weights do not
                match the pinned digest, or the architecture and the file
                disagree on a single key. In every case nothing is cached: a
                model that could not be verified never becomes usable.
        """
        if self._model is not None:
            return

        with self._lock:
            if self._model is not None:
                return

            # Imported lazily so that importing this module stays cheap for
            # tests that never run inference.
            from safetensors.torch import load_file

            from app.m2_analysis.vendor.spai import build_config, build_mf_vit

            if not self.present_on_disk:
                raise ModelUnavailableError(
                    f"the {self.name} frequency detector weights are not present at "
                    f"{self.path}. One-time setup: download spai.pth from "
                    f"{config.DETECTOR_FREQUENCY_SOURCE_URL} into "
                    f"{config.MODELS_DIR}, then run "
                    "`cd backend && python scripts/convert_spai_checkpoint.py`."
                )

            try:
                tensors = load_file(str(self.path), device="cpu")
            except Exception as exc:  # noqa: BLE001
                raise ModelUnavailableError(
                    f"could not read the {self.name} weights at {self.path}: {exc}"
                ) from exc

            actual = weights_digest(tensors)
            if actual != self.digest:
                raise ModelUnavailableError(
                    f"the {self.name} weights at {self.path} do not match the pinned "
                    f"digest: expected {self.digest}, got {actual}. Refusing to load "
                    "weights of unknown provenance."
                )

            model = build_mf_vit(
                build_config(feature_extraction_batch=self.feature_batch)
            )

            # Equivalent to strict=True, with an error message we control.
            # Upstream loads with strict=False; a missing key there leaves a
            # randomly initialised layer in a model that still produces
            # plausible numbers.
            missing, unexpected = model.load_state_dict(tensors, strict=False)
            if missing or unexpected:
                raise ModelUnavailableError(
                    f"the {self.name} weights do not match the vendored architecture "
                    f"exactly: {len(missing)} missing key(s) {sorted(missing)[:5]}, "
                    f"{len(unexpected)} unexpected key(s) {sorted(unexpected)[:5]}. "
                    "Refusing a partial load - it would leave layers randomly "
                    "initialised."
                )

            head = model.cls_head.head[-1]
            if head.out_features != 1:
                raise ModelUnavailableError(
                    f"the {self.name} classification head has {head.out_features} "
                    "outputs; this loader implements the single-logit BCE convention."
                )

            model.eval()  # dropout and stochastic depth off - PRD2 section 8.4
            self._model = model.to(config.DEVICE)

    def score(
        self,
        image_path: str,
        *,
        capture: bool = False,
        head=None,
        ai_is_positive: bool | None = None,
    ) -> BranchResult:
        """Return P(AI Generated) for an image on disk.

        Phase 4 (F.19): ``head`` is an uploaded classification head
        (``heads.LoadedHead``) used instead of the published one - a forward
        hook on ``cls_head`` replaces its output for this one call, and is
        always removed. ``ai_is_positive`` is the sign convention of the ACTIVE
        D3 row; None falls back to this detector's configured default.

        Deterministic: eval mode, inference mode, no sampling, no test-time
        augmentation. The patch tiling is a fixed function of the image size.
        """
        self.load()
        assert self._model is not None

        try:
            with Image.open(image_path) as handle:
                tensor = prepare_image(handle, resize_to=self.resize_to)
        except Exception as exc:  # noqa: BLE001
            raise InferenceError(
                f"{self.name} detector could not preprocess {image_path!r}: {exc}"
            ) from exc

        # Checked here rather than left to the model, which would raise a bare
        # tensor-shape RuntimeError from four frames deep in vendored code.
        height, width = tensor.shape[-2], tensor.shape[-1]
        if min(height, width) < MIN_SIDE:
            raise SpectralBranchUnavailable(
                f"{width}x{height} is smaller than the {MIN_SIDE}px patch the "
                f"{self.name} branch needs in both dimensions"
            )

        tensor = tensor.to(config.DEVICE)

        hook = None
        if head is not None:
            hook = self._model.cls_head.register_forward_hook(
                lambda _m, inputs, _out: head.module(inputs[0]))
        try:
            with torch.inference_mode():
                # A list of one image takes the arbitrary-resolution path,
                # which is the one the authors evaluate with
                # (TEST.ORIGINAL_RESOLUTION).
                logit = self._model([tensor], self.feature_batch)
                probability = torch.sigmoid(logit).reshape(-1)[0].item()
        finally:
            # Patchifying a large native image makes two transient copies of
            # it on the device; the caching allocator then keeps those blocks
            # reserved. On a 6 GB card the reserve was measured at 5.2 GB
            # after an 8192x4096 image, and on Windows (WDDM) exhausting VRAM
            # does not raise - CUDA spills into system memory and throughput
            # collapses silently. Returning the cache after every request
            # costs milliseconds and keeps each request's footprint bounded
            # by its own image, not by the largest image seen so far.
            if hook is not None:
                hook.remove()
            if tensor.is_cuda:
                del tensor
                torch.cuda.empty_cache()

        positive = self.ai_is_positive if ai_is_positive is None else ai_is_positive
        if not positive:
            probability = 1.0 - probability

        return BranchResult(score=float(probability), activations=None)

    def cls_head_state(self) -> dict:
        """The published head's tensors, keys relative to ``cls_head``."""
        self.load()
        return {k: v.detach() for k, v in self._model.cls_head.state_dict().items()}

    def cls_head_module(self):
        self.load()
        return self._model.cls_head

    def reset_cache(self) -> None:
        """Drop the cached model. For tests and Step 5 reactivation."""
        with self._lock:
            self._model = None


# Module-level instance, so the weights are shared across all requests.
frequency = SpectralDetector(
    filename=config.DETECTOR_FREQUENCY_FILENAME,
    digest=config.DETECTOR_FREQUENCY_WEIGHTS_DIGEST,
    ai_is_positive=config.DETECTOR_FREQUENCY_AI_IS_POSITIVE,
    resize_to=config.DETECTOR_FREQUENCY_RESIZE_TO,
    feature_batch=config.DETECTOR_FREQUENCY_FEATURE_BATCH,
)
