"""Pretrained Hugging Face image classifiers - the semantic branch.

TruePixels.rgb does not train models. Every score exposed as an AI-generated
probability comes from a checkpoint someone else trained for exactly that
task. There is no randomly initialised layer anywhere in this path.

The primary detector is an ordinary Hugging Face image classifier
(``AutoModelForImageClassification`` + ``AutoImageProcessor``). The frequency
branch is a different kind of model with its own loader - see
``frequency_detector.py``; ``BranchResult`` is shared so the pipeline treats
both alike.

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

    def __init__(self, checkpoint: str, *, role: str) -> None:
        self.checkpoint = checkpoint
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
                processor = AutoImageProcessor.from_pretrained(self.checkpoint)
                model = AutoModelForImageClassification.from_pretrained(
                    self.checkpoint,
                    use_safetensors=True,
                )
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

    def score(self, image_path: str, *, capture: bool = False) -> BranchResult:
        """Return P(AI Generated) for an image on disk.

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
            score=float(probabilities[0, self._ai_index].item()),
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


# Module-level instance, so the weights are shared across all requests.
primary = PretrainedDetector(config.DETECTOR_PRIMARY, role="primary")


def reset_cache() -> None:
    """Drop every cached detector, this branch and the frequency branch alike."""
    from app.m2_analysis import frequency_detector

    primary.reset_cache()
    frequency_detector.frequency.reset_cache()
