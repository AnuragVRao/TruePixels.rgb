"""Pretrained content detectors - the semantic branch.

TruePixels.rgb does not train models. Every score exposed as an AI-generated
probability comes from a checkpoint someone else trained for exactly that
task. There is no randomly initialised layer anywhere in this path.

The content branch is one of a fixed, pinned set (config.SEMANTIC_BACKBONES),
chosen by the active D3 semantic row - ``semantic(checkpoint)`` returns the
cached detector:

- ``PretrainedDetector``: an ordinary Hugging Face image classifier
  (``AutoModelForImageClassification`` + ``AutoImageProcessor``) - SigLIP 2;
- ``CommForDetector``: Community Forensics, a timm ViT-S/16 with one logit
  (vendor/commfor), the content detector since 2026-10-09.

The frequency branch is a different kind of model with its own loader - see
``frequency_detector.py``; ``BranchResult`` is shared so the pipeline treats
all of them alike.

----------------------------------------------------------------------------
THE LABEL-ORDER HAZARD
----------------------------------------------------------------------------
Checkpoints do not agree on which index means "AI":

    prithivMLmods/AIorNot-SigLIP2      {0: "Real",       1: "AI"}     -> 1
    Organika/sdxl-detector             {0: "artificial", 1: "human"}  -> 0
    Ateeqq/ai-vs-human-image-detector  {0: "ai",         1: "hum"}    -> 0

Hard-coding ``probs[1]`` would silently invert a checkpoint of the second
kind and produce confident, plausible, wrong scores - the same failure class
as the confidence inversion in fusion.py. So the index is always resolved
from the checkpoint's own ``id2label`` and never assumed. See
``resolve_ai_index``. (The SPAI frequency detector has no labels at all; its
sign convention is a documented config flag verified by a canary - see
frequency_detector.py.)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import torch
from PIL import Image

from app.shared import config
from app.shared.contracts.errors import InferenceError, ModelUnavailableError

# Label vocabularies, compared case-insensitively after stripping separators.
# Deliberately conservative: an unrecognised label set raises rather than
# guessing, because guessing wrong here is invisible at runtime.
_AI_LABELS = frozenset(
    {"ai", "aigenerated", "artificial", "fake", "synthetic", "deepfake", "generated"}
)
_REAL_LABELS = frozenset(
    {"real", "hum", "human", "authentic", "nature", "natural", "genuine"}
)


@dataclass
class BranchResult:
    """One branch's verdict, plus whatever internal state was captured.

    ``activations`` is None unless the caller asked for ``capture=True``
    (explainability); see ``HFImageDetector.score``.
    """

    score: float
    activations: dict | None = None


def _normalise(label: str) -> str:
    """Lowercase and strip separators so 'AI_Generated' matches 'aigenerated'."""
    return "".join(character for character in label.lower() if character.isalnum())


def resolve_ai_index(id2label: dict) -> int:
    """Find which output index means "AI generated", from the labels themselves.

    Args:
        id2label: the checkpoint's own mapping, e.g. ``{0: "Real", 1: "AI"}``.

    Returns:
        The index whose label denotes AI-generated content.

    Raises:
        ModelUnavailableError: if the labels are not a clean binary AI/real
            pair. Refusing to guess is the point - a mislabelled index inverts
            every prediction the branch makes, and nothing downstream would
            notice.
    """
    ai_indices = []
    real_indices = []

    for index, label in id2label.items():
        normalised = _normalise(str(label))
        if normalised in _AI_LABELS:
            ai_indices.append(int(index))
        elif normalised in _REAL_LABELS:
            real_indices.append(int(index))

    if len(ai_indices) != 1 or len(real_indices) != 1:
        raise ModelUnavailableError(
            f"cannot resolve the AI class from labels {dict(id2label)!r}: "
            f"matched {len(ai_indices)} AI label(s) and {len(real_indices)} "
            "real label(s), expected exactly one of each. Refusing to guess - "
            "a wrong index would invert every prediction silently."
        )

    return ai_indices[0]


class PretrainedDetector:
    """A cached, lazily loaded Hugging Face image classifier.

    NF.4: loaded once per process, never per request. The lock guards the
    first load against concurrent requests.
    """

    def __init__(self, checkpoint: str, *, role: str, revision: str | None = None) -> None:
        self.checkpoint = checkpoint
        self.revision = revision
        self.role = role  # "primary", for error messages
        self._lock = threading.Lock()
        self._model = None
        self._processor = None
        self._ai_index: int | None = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def ai_index(self) -> int | None:
        return self._ai_index

    def load(self) -> None:
        """Load and cache the checkpoint. Idempotent, thread-safe."""
        if self._model is not None:
            return

        with self._lock:
            if self._model is not None:
                return

            # Imported lazily so importing this module does not pull in the
            # whole transformers stack for tests that never run inference.
            from transformers import AutoImageProcessor, AutoModelForImageClassification

            try:
                processor, model = self._from_pretrained(AutoImageProcessor,
                                                         AutoModelForImageClassification)
            except Exception as exc:  # noqa: BLE001
                raise ModelUnavailableError(
                    f"could not load the {self.role} detector "
                    f"{self.checkpoint!r}: {exc}"
                ) from exc

            # Resolve BEFORE publishing the model, so a checkpoint with labels
            # we cannot interpret never becomes usable.
            ai_index = resolve_ai_index(model.config.id2label)

            model.eval()  # PRD2 8.4: dropout off, batch-norm statistics frozen
            self._model = model.to(config.DEVICE)
            self._processor = processor
            self._ai_index = ai_index

    def _from_pretrained(self, processor_cls, model_cls):
        """Load the pinned revision - from the local cache when it is there.

        local_files_only first, so a cached model never touches the network
        (startup works offline); only an uncached revision is downloaded.
        """
        kwargs = {"revision": self.revision, "use_safetensors": True}
        try:
            return (processor_cls.from_pretrained(self.checkpoint, revision=self.revision,
                                                  local_files_only=True),
                    model_cls.from_pretrained(self.checkpoint, local_files_only=True, **kwargs))
        except OSError:
            return (processor_cls.from_pretrained(self.checkpoint, revision=self.revision),
                    model_cls.from_pretrained(self.checkpoint, **kwargs))

    def score(self, image_path: str, *, capture: bool = False, head=None) -> BranchResult:
        """Return P(AI Generated) for an image on disk.

        ``head`` (Phase 4, F.19): an uploaded classification head
        (``heads.LoadedHead``) to use instead of the checkpoint's own. The
        backbone and pooling are unchanged; a forward hook on the published
        classifier replaces its output with the uploaded head's for this one
        call (the hook is always removed). With ``head=None`` the forward pass
        is exactly the published model's - no hook at all.

        Reads the native-resolution original and applies the checkpoint's own
        preprocessing. Deterministic: eval mode, inference mode, no sampling,
        no test-time augmentation (PRD2 section 8.4).
        """
        self.load()
        assert self._model is not None and self._processor is not None
        assert self._ai_index is not None

        try:
            with Image.open(image_path) as handle:
                image = handle.convert("RGB")
                inputs = self._processor(images=image, return_tensors="pt")
        except Exception as exc:  # noqa: BLE001
            raise InferenceError(
                f"{self.role} detector could not preprocess {image_path!r}: {exc}"
            ) from exc

        inputs = {key: value.to(config.DEVICE) for key, value in inputs.items()}

        captured: list[torch.Tensor] = []
        handles = self._attach_attention_capture(captured) if capture else []
        ai_index = self._ai_index
        if head is not None:
            handles.append(self._model.classifier.register_forward_hook(
                lambda _m, inputs, _out: head.module(inputs[0])))
            ai_index = head.ai_index
        try:
            with torch.inference_mode():
                logits = self._model(**inputs).logits
                probabilities = torch.softmax(logits, dim=-1)
                # Only the raw inputs are kept here; the weights are recomputed
                # later by attention_maps(), outside the pipeline's timed
                # region, so latency_ms stays inference-only with xai on.
                activations = {"hidden_states": captured} if capture else None
        finally:
            for handle in handles:
                handle.remove()

        return BranchResult(
            score=float(probabilities[0, ai_index].item()),
            activations=activations,
        )

    # ------------------------------------------------------------------
    # Explainability capture (Phase 3)
    # ------------------------------------------------------------------
    #
    # The scoring forward pass is left exactly as it is (SDPA attention, which
    # does not return weights). Instead, a forward PRE-hook on every encoder
    # layer's self_attn records that module's input - layer_norm1(h), shape
    # (1, 196, 768) - and the attention weights are recomputed from it with
    # the module's own q_proj / k_proj, exactly as transformers'
    # eager_attention_forward computes them (no mask for vision):
    #
    #     softmax(q @ k^T * head_dim**-0.5, dim=-1, dtype=float32)
    #
    # The hooks only read; the forward pass and so the score are unchanged
    # bit for bit (asserted by test and by regression_check --xai). Hooks are
    # attached for one call and always removed.

    def classifier_state(self) -> dict:
        """The published head's tensors (for the quality gate's reference path)."""
        self.load()
        return {k: v.detach() for k, v in self._model.classifier.state_dict().items()}

    # The quality gate's view of a content detector (shared with CommForDetector):
    # the module whose INPUT is cached per reference image, how its outputs
    # become P(AI), and what preprocessing the cached inputs depend on.
    supports_uploaded_heads = True

    def head_module(self):
        self.load()
        return self._model.classifier

    def head_probabilities(self, outputs: torch.Tensor, ai_index: int | None = None) -> torch.Tensor:
        return torch.softmax(outputs, dim=-1)[:, self._ai_index if ai_index is None else ai_index]

    def preprocess_signature(self) -> dict:
        self.load()
        return self._processor.to_dict()

    def _encoder_layers(self):
        return self._model.vision_model.encoder.layers

    def _attach_attention_capture(self, captured: list) -> list:
        def record(_module, args, kwargs):
            hidden = args[0] if args else kwargs["hidden_states"]
            captured.append(hidden.detach())

        return [layer.self_attn.register_forward_pre_hook(record, with_kwargs=True)
                for layer in self._encoder_layers()]

    def attention_maps(self, activations: dict) -> dict:
        """Attention weights + bundle fields from what ``score(capture=True)`` kept."""
        captured: list[torch.Tensor] = activations["hidden_states"]
        layers = self._encoder_layers()
        if len(captured) != len(layers):
            raise InferenceError(
                f"attention capture saw {len(captured)} of {len(layers)} layers"
            )
        maps = []
        with torch.inference_mode():
            for layer, hidden in zip(layers, captured):
                attention = layer.self_attn
                batch, tokens, _ = hidden.shape
                q = attention.q_proj(hidden).view(batch, tokens, attention.num_heads, attention.head_dim).transpose(1, 2)
                k = attention.k_proj(hidden).view(batch, tokens, attention.num_heads, attention.head_dim).transpose(1, 2)
                weights = torch.softmax(torch.matmul(q, k.transpose(-1, -2)) * attention.scale,
                                        dim=-1, dtype=torch.float32)
                maps.append(weights[0])
        stacked = torch.stack(maps).cpu().numpy()  # (layers, heads, tokens, tokens)
        side = int(round(stacked.shape[-1] ** 0.5))
        if side * side != stacked.shape[-1]:
            raise InferenceError(f"{stacked.shape[-1]} tokens do not form a square patch grid")
        return {
            "attention": stacked,
            "patch_grid": (side, side),
            # SiglipForImageClassification mean-pools ALL patch tokens before its
            # classifier (no CLS token exists), so rollout must aggregate over all
            # query tokens rather than read a CLS row.
            "pooling": "mean",
            "backbone": "siglip_b16",
        }

    def reset_cache(self) -> None:
        """Drop the cached model. For tests and Step 5 reactivation."""
        with self._lock:
            self._model = None
            self._processor = None
            self._ai_index = None


class _ExactPatchProjection(torch.nn.Module):
    """The ViT patch embedding (Conv2d, kernel = stride = 16) computed as
    unfold + matmul - the same linear map, without cuDNN.

    Why: on CUDA, PyTorch runs convolutions in TF32 by default
    (torch.backends.cudnn.allow_tf32 = True), and for this model that alone
    moved a published reference score from 0.7860 to 0.7655 (measured
    2026-10-09; CPU and the authors' notebook agree on 0.7860). Matmul TF32 is
    off by default, so this projection reproduces the full-precision result on
    every device - without touching the process-wide cuDNN flags, which SPAI and
    SigLIP 2 also run under.
    """

    def __init__(self, conv: torch.nn.Conv2d) -> None:
        super().__init__()
        assert conv.kernel_size == conv.stride and conv.padding == (0, 0) and conv.groups == 1
        self.kernel = conv.kernel_size
        self.weight = conv.weight  # shared Parameters: the loaded tensors, unchanged
        self.bias = conv.bias

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        batch, _, height, width = x.shape
        kh, kw = self.kernel
        patches = torch.nn.functional.unfold(x, kernel_size=self.kernel, stride=self.kernel)  # (B, C*kh*kw, N)
        out = torch.matmul(self.weight.reshape(self.weight.shape[0], -1), patches)  # (B, D, N)
        if self.bias is not None:
            out = out + self.bias[None, :, None]
        return out.reshape(batch, -1, height // kh, width // kw)


class CommForDetector:
    """Community Forensics (Park & Owens, CVPR 2025) as the content branch.

    A timm ViT-S/16 at 384 px with a single-logit head (vendor/commfor). Same
    interface as PretrainedDetector, so the pipeline, gate and warm-up treat
    both alike. Loading is fail-closed: the safetensors file at the pinned
    revision must match the pinned SHA-256, and load_state_dict is strict.
    There is no id2label; the sign is config's documented convention
    (SEMANTIC_COMMFOR_AI_IS_POSITIVE), verified by tests/test_commfor.py.
    """

    supports_uploaded_heads = False
    # The authors' test transform (dataloader.get_transform(mode="test")).
    RESIZE, CROP = 440, 384
    MEAN, STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)

    def __init__(self, checkpoint: str, *, revision: str, weights_digest: str, ai_is_positive: bool,
                 role: str = "primary") -> None:
        self.checkpoint = checkpoint
        self.revision = revision
        self.weights_digest = weights_digest
        self.ai_is_positive = ai_is_positive
        self.role = role
        self._lock = threading.Lock()
        self._model = None
        self._transform = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def ai_index(self) -> None:
        return None  # single logit: see ai_is_positive

    def _weights_path(self) -> str:
        from huggingface_hub import hf_hub_download

        try:
            return hf_hub_download(self.checkpoint, "model.safetensors", revision=self.revision,
                                   local_files_only=True)
        except Exception:  # noqa: BLE001 - not cached yet: fetch the pinned revision once
            return hf_hub_download(self.checkpoint, "model.safetensors", revision=self.revision)

    def load(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            import hashlib

            from safetensors.torch import load_file
            from torchvision import transforms as T

            from app.m2_analysis.vendor.commfor.models import ViTClassifier

            try:
                path = self._weights_path()
                digest = hashlib.sha256()
                with open(path, "rb") as handle:
                    for block in iter(lambda: handle.read(1 << 20), b""):
                        digest.update(block)
                if digest.hexdigest() != self.weights_digest:
                    raise ModelUnavailableError(
                        f"{self.checkpoint}@{self.revision[:12]} weights digest {digest.hexdigest()} "
                        f"!= pinned {self.weights_digest}; refusing to load")
                model = ViTClassifier(model_size="small", input_size=384, patch_size=16)
                # The checkpoint's keys are the wrapper's ("vit.*"); strict=True
                # refuses any missing or unexpected tensor.
                model.load_state_dict(load_file(path), strict=True)
            except ModelUnavailableError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise ModelUnavailableError(
                    f"could not load the {self.role} detector {self.checkpoint!r}: {exc}") from exc
            model.eval()
            # Exact patch projection (no cuDNN TF32) - see _ExactPatchProjection.
            model.vit.patch_embed.proj = _ExactPatchProjection(model.vit.patch_embed.proj)
            self._transform = T.Compose([
                T.Resize(self.RESIZE),
                T.CenterCrop(self.CROP),
                T.ToTensor(),
                T.Normalize(mean=self.MEAN, std=self.STD),
            ])
            self._model = model.to(config.DEVICE)

    def _probability(self, logits: torch.Tensor) -> torch.Tensor:
        p = torch.sigmoid(logits.reshape(-1))
        return p if self.ai_is_positive else 1.0 - p

    def score(self, image_path: str, *, capture: bool = False, head=None) -> BranchResult:
        """P(AI Generated) for an image on disk, by the authors' test transform."""
        if head is not None:
            raise InferenceError("uploaded heads are not supported for the Community Forensics detector")
        self.load()
        try:
            with Image.open(image_path) as handle:
                image_size = handle.size
                x = self._transform(handle.convert("RGB")).unsqueeze(0)
        except Exception as exc:  # noqa: BLE001
            raise InferenceError(f"{self.role} detector could not preprocess {image_path!r}: {exc}") from exc
        x = x.to(config.DEVICE)
        captured: list[torch.Tensor] = []
        handles = self._attach_attention_capture(captured) if capture else []
        try:
            with torch.inference_mode():
                probability = self._probability(self._model(x))
        finally:
            for handle in handles:
                handle.remove()
        return BranchResult(score=float(probability[0].item()),
                            activations={"hidden_states": captured, "image_size": image_size}
                            if capture else None)

    def crop_region(self, width: int, height: int) -> tuple[float, float, float, float]:
        """The centre crop the model sees, as fractions of the original image:
        shortest side scaled to RESIZE, then a CROP x CROP centre square."""
        side = self.CROP * min(width, height) / self.RESIZE  # crop side in original pixels
        fx, fy = min(1.0, side / width), min(1.0, side / height)
        return ((1 - fx) / 2, (1 - fy) / 2, (1 + fx) / 2, (1 + fy) / 2)

    # Gate interface (see PretrainedDetector) -----------------------------
    def head_module(self):
        self.load()
        return self._model.vit.head

    def head_probabilities(self, outputs: torch.Tensor, ai_index: int | None = None) -> torch.Tensor:
        return self._probability(outputs)

    def preprocess_signature(self) -> dict:
        return {"transform": "Resize(440) -> CenterCrop(384) -> ToTensor -> Normalize",
                "mean": list(self.MEAN), "std": list(self.STD), "weights_digest": self.weights_digest,
                "ai_is_positive": self.ai_is_positive}

    # Explainability -------------------------------------------------------
    # Same passive scheme as SigLIP: a forward PRE-hook on each block's attn
    # records its input (norm1(x), shape (1, 577, 384)); the weights are
    # recomputed afterwards with the module's own qkv, as timm's non-fused
    # path does: softmax((q * scale) @ k^T). The score is untouched.
    def _blocks(self):
        return self._model.vit.blocks

    def _attach_attention_capture(self, captured: list) -> list:
        def record(_module, args):
            captured.append(args[0].detach())

        return [block.attn.register_forward_pre_hook(record) for block in self._blocks()]

    def attention_maps(self, activations: dict) -> dict:
        captured: list[torch.Tensor] = activations["hidden_states"]
        blocks = self._blocks()
        if len(captured) != len(blocks):
            raise InferenceError(f"attention capture saw {len(captured)} of {len(blocks)} layers")
        maps = []
        with torch.inference_mode():
            for block, hidden in zip(blocks, captured):
                attn = block.attn
                batch, tokens, _ = hidden.shape
                qkv = attn.qkv(hidden).reshape(batch, tokens, 3, attn.num_heads, attn.head_dim).permute(2, 0, 3, 1, 4)
                q, k = attn.q_norm(qkv[0]), attn.k_norm(qkv[1])
                weights = torch.softmax(torch.matmul(q * attn.scale, k.transpose(-2, -1)),
                                        dim=-1, dtype=torch.float32)
                maps.append(weights[0])
        stacked = torch.stack(maps).cpu().numpy()  # (layers, heads, 1 + patches, 1 + patches)
        prefix = int(getattr(self._model.vit, "num_prefix_tokens", 1))
        side = int(round((stacked.shape[-1] - prefix) ** 0.5))
        if prefix != 1 or side * side != stacked.shape[-1] - prefix:
            raise InferenceError(f"{stacked.shape[-1]} tokens do not form CLS + a square patch grid")
        return {
            "attention": stacked,
            "patch_grid": (side, side),
            # global_pool="token": the head reads the CLS token only.
            "pooling": "cls",
            "backbone": "commfor_vits16",
            "region": self.crop_region(*activations["image_size"]) if activations.get("image_size") else None,
        }

    def reset_cache(self) -> None:
        with self._lock:
            self._model = None
            self._transform = None


def _build(checkpoint: str):
    spec = config.SEMANTIC_BACKBONES.get(checkpoint)
    if spec is None:
        raise ModelUnavailableError(f"{checkpoint!r} is not one of the pinned content detectors "
                                    f"{sorted(config.SEMANTIC_BACKBONES)}")
    if spec["kind"] == "commfor-vit":
        return CommForDetector(checkpoint, revision=spec["revision"], weights_digest=spec["weights_digest"],
                               ai_is_positive=spec["ai_is_positive"])
    return PretrainedDetector(checkpoint, role="primary", revision=spec["revision"])


# One cached instance per pinned content detector, created on first use, so the
# weights are shared across all requests. Which one RUNS is decided by the
# active D3 semantic row: callers use semantic(models.primary.checkpoint).
_SEMANTIC: dict[str, object] = {}
_SEMANTIC_LOCK = threading.Lock()


def semantic(checkpoint: str):
    with _SEMANTIC_LOCK:
        if checkpoint not in _SEMANTIC:
            _SEMANTIC[checkpoint] = _build(checkpoint)
        return _SEMANTIC[checkpoint]


# The published BASELINE content detector (config.DETECTOR_PRIMARY).
primary = semantic(config.DETECTOR_PRIMARY)


def reset_cache() -> None:
    """Drop every cached detector, both content detectors and the frequency branch."""
    from app.m2_analysis import frequency_detector

    for detector in list(_SEMANTIC.values()):
        detector.reset_cache()
    frequency_detector.frequency.reset_cache()
