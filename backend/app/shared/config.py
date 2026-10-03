"""Shared configuration for the TruePixels.rgb backend.

Every provisional constant in this file is a placeholder for a value that a
later milestone selects from data. Each one names the PRD decision that will
replace it. Nothing here is hard-coded anywhere else in the codebase - if you
find yourself typing 0.5 into a branch module, put it here instead.
"""

from __future__ import annotations

import os
from pathlib import Path

import torch

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

# backend/app/shared/config.py -> repository root
REPO_ROOT = Path(__file__).resolve().parents[3]

# User data: M1's uploads, M3's explainability panels. All three
# modules share this one tree. It is NOT web-served: files leave only through
# owner-checked endpoints (app/shared/files.py). It
# honours M1's STORAGE_DIR variable so the two can never disagree; M1's own
# default points here too.
STORAGE_ROOT = Path(os.getenv("STORAGE_DIR", str(REPO_ROOT / "storage"))).resolve()
UPLOADS_DIR = STORAGE_ROOT / "uploads"
EXPLAINABILITY_DIR = STORAGE_ROOT / "explainability"

# Model weights are NOT user data and deliberately do not follow STORAGE_DIR:
# pointing tests at a scratch storage tree must not hide the SPAI weights.
MODELS_DIR = REPO_ROOT / "storage" / "models"


def ensure_storage_dirs() -> None:
    """Create the local storage layout if it is missing.

    Contents are gitignored; the directories themselves are not guaranteed to
    exist on a fresh clone.
    """
    for directory in (UPLOADS_DIR, EXPLAINABILITY_DIR, MODELS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# CORS
# --------------------------------------------------------------------------
#
# Browsers let any page call this API from any origin only if we say so. The
# combination that used to be here - allow_origins=["*"] with
# allow_credentials=True - is the dangerous one: Starlette then echoes the
# caller's Origin back instead of sending "*", so ANY website a signed-in user
# visits could make credentialed requests with their session. That is a hole
# worth closing before this is exposed through a tunnel.
#
# The two UIs that actually need it are M1's React dev server and anything
# served from the API's own host (M3's dashboard is same-origin and needs no
# CORS at all). Add deployment origins through the environment, comma
# separated, rather than widening the default:
#     TRUEPIXELS_CORS_ORIGINS=https://truepixels.example.com
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "TRUEPIXELS_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if origin.strip()
]


# --------------------------------------------------------------------------
# Device
# --------------------------------------------------------------------------

# PRD2 section 4: inference must remain viable on CPU (SRS 3.2.2 minimum spec);
# a CUDA GPU is used automatically where available.
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# Load both detectors at startup (app/m2_analysis/warmup.py) so that no user
# request pays the one-time load. Off for the test suite, which loads lazily.
WARMUP_ON_STARTUP = os.getenv("WARMUP_ON_STARTUP", "True").strip().lower() in {"1", "true", "yes"}


# --------------------------------------------------------------------------
# Determinism (PRD2 section 8.4, NF.5, AC-04)
# --------------------------------------------------------------------------

# Inference determinism no longer depends on this: there are no randomly
# initialised weights left in the system. It is kept for test fixtures and for
# any future code path that samples.
SEED = 20260907


# --------------------------------------------------------------------------
# Pretrained detectors
# --------------------------------------------------------------------------
#
# TruePixels.rgb NEVER trains, fine-tunes or retrains a model. Both branches
# below are third-party checkpoints already trained for AI-vs-real image
# detection, used exactly as published. Change these identifiers to swap
# detectors; nothing else in the codebase names a checkpoint.
#
# The two branches read DIFFERENT KINDS of evidence, which is the whole
# argument for fusing them (PRD2 section 1.3):
#   - the primary asks a semantic question - what is this a picture of, and
#     does it look like the AI images it was trained on;
#   - the frequency detector asks a physical question - does the pixel grid
#     carry the spectral signature of a synthesis pipeline.
#
# PRIMARY - prithivMLmods/AIorNot-SigLIP2
#   Fine-tuned from google/siglip2-base-patch16-224 (declared in the model's
#   own HF metadata as base_model:finetune, so the SigLIP 2 lineage is
#   verifiable rather than merely asserted in prose).
#   Task     : binary AI-vs-real image classification
#   Data     : competitions/aiornot
#   Labels   : {0: "Real", 1: "AI"}  -> AI index 1, resolved from id2label
#              (see detectors.resolve_ai_index - never hard-coded)
#   Size     : 92,885,762 params
#   Licence  : Apache-2.0
#   Upstream self-reported accuracy 0.9149 over 18,618 samples. That figure is
#   THEIRS, measured on their split. We have run no benchmark of our own.
DETECTOR_PRIMARY = "prithivMLmods/AIorNot-SigLIP2"
# Pinned hub revision (commit). Without it from_pretrained() follows the
# floating "main" branch, so new weights pushed upstream would change what
# runs without anything here - or in D3 - changing (Phase 0 finding, fixed in
# Phase 4). Loaded from the local cache first (no network at startup); the
# hub is contacted only if this revision is not cached yet.
DETECTOR_PRIMARY_REVISION = "f4e6a281725e8dfb11a1d8c959b69737bba1e91d"


# --------------------------------------------------------------------------
# Frequency-domain detector - SPAI (FR-02, realised with a pretrained model)
# --------------------------------------------------------------------------
#
# SPAI: "Any-Resolution AI-Generated Image Detection by Spectral Learning",
# Karageorgiou, Papadopoulos, Kompatsiaris, Gavves - CVPR 2025.
#   Repo     : https://github.com/mever-team/spai
#   Paper    : https://arxiv.org/abs/2411.19417
#   Method   : the image is split by FFT into low-pass and high-pass
#              components (circular mask, radius 16); a ViT-B/16 pretrained by
#              Masked Frequency Modeling encodes original, low and high; the
#              cosine similarities between those encodings ("spectral
#              reconstruction similarity") plus projected features are
#              aggregated across 224x224 patches by a learned cross-attention
#              ("spectral context attention") and classified with one logit.
#   Data     : real COCO / LSUN vs Latent Diffusion generations
#   Output   : sigmoid(logit) = P(AI Generated); see the sign convention below
#   Size     : 139,945,243 params
#   Licence  : Apache-2.0 - code AND weights
#   Upstream self-reported validation accuracy 0.9853 (embedded in the
#   checkpoint). THEIRS, on THEIR split. Not ours.
#
# The model code is vendored under app/m2_analysis/vendor/spai (see NOTICE).
# The weights are published on Google Drive, which cannot be fetched
# reproducibly by URL, so the loader NEVER downloads. Setup is a one-time,
# two-step affair:
#   1. download spai.pth from DETECTOR_FREQUENCY_SOURCE_URL into storage/models/
#   2. cd backend && python scripts/convert_spai_checkpoint.py
# Step 2 verifies the upstream SHA-256, extracts the model tensors from the
# pickled training checkpoint under a restricted unpickler, and writes a
# safetensors file that contains no code. The runtime loads only that file.
DETECTOR_FREQUENCY_NAME = "SPAI"
DETECTOR_FREQUENCY_SOURCE_URL = (
    "https://drive.google.com/file/d/1vvXmZqs6TVJdj8iF1oJ4L_fcgdQrp_YI/view"
)
DETECTOR_FREQUENCY_UPSTREAM_COMMIT = "8ff7b3b6779b4fcb43cf313471d9cb1c62d129a4"
# SHA-256 of the upstream spai.pth as downloaded on 2026-09-12 (934,865,338 bytes).
DETECTOR_FREQUENCY_UPSTREAM_SHA256 = (
    "24159f27d7c8c2cd0cb6c4019189eb89ad0874a0d9d15f8dc9afd39ca9648a55"
)
# The converted, tensors-only file the runtime actually loads (560,019,476
# bytes), and the SHA-256 of ITS WEIGHTS - name, dtype, shape and bytes of
# every tensor in sorted order (frequency_detector.weights_digest). The file's
# own hash is not pinned because safetensors writes header metadata in
# arbitrary order, so re-converting the same weights yields a different file.
DETECTOR_FREQUENCY_FILENAME = "spai.safetensors"
DETECTOR_FREQUENCY_WEIGHTS_DIGEST = (
    "0151f7570b540c305fcbdae0221bccad9399998a6c3938c9c384c323e5dfb42e"
)

# Set False to run on the primary detector alone. Fusion then degrades to a
# documented passthrough - never a fabricated second opinion.
DETECTOR_FREQUENCY_ENABLED = True

# SPAI has no id2label to resolve an AI index from: it is a single-logit BCE
# classifier. Its training CSVs label real images 0 and generated images 1,
# and the authors' inference script writes sigmoid(logit) straight out as the
# AI probability - so sigmoid(logit) = P(AI Generated). That convention is NOT
# inferable from the weights, which is why it is (a) stated here, (b) a flag
# rather than an assumption, and (c) checked by the smoke-image canary
# recorded in CLAUDE.md: generated images must score higher than photographs.
# If a future checkpoint inverts it, flip this - do not touch the code.
DETECTOR_FREQUENCY_AI_IS_POSITIVE = True

# Input geometry. SPAI is any-resolution by design: it tiles the native image
# into 224x224 patches (stride 224) and attends across them. We therefore
# NEVER resize by default - Contract C1 section 4.3 is explicit that a
# downsample is a low-pass filter which erases exactly the evidence this
# branch looks for. The authors' inference script offers --resize-to as a cap
# on the longest side for very large images; it is exposed here for the same
# reason and for latency (each patch costs three ViT-B/16 passes). None means
# never resize. Set it only on the basis of a latency measurement, and record
# that measurement in CLAUDE.md.
DETECTOR_FREQUENCY_RESIZE_TO: int | None = None

# Patches per backbone forward. Memory and speed only - never changes the
# result. Upstream's default of 400 assumes an 8 GB GPU with mixed precision.
# MEASURED 2026-09-12 on an RTX 4050 Laptop (6 GB, fp32), worst-case smoke
# image 6144x6144 = 729 patches, SigLIP 2 resident in the same process:
#   batch 16 -> 29.5 s, peak 3.4 GB allocated / 3.8 GB reserved
#   batch 24 -> 27.9 s, peak 4.0 GB allocated / 4.5 GB reserved
#   batch 32+ -> exceeded VRAM; on Windows (WDDM) CUDA then silently spills
#                into shared system memory and throughput collapses to ~0
#                instead of raising an out-of-memory error.
# 16 keeps ~2 GB of headroom for ~5% throughput; the GPU is saturated there.
# Raise it only after measuring peak VRAM on the target GPU.
DETECTOR_FREQUENCY_FEATURE_BATCH = 16


# --------------------------------------------------------------------------
# Contract C1 tensor
# --------------------------------------------------------------------------

# M1 builds the C1 tensor itself (app/m1_access/preprocess.py, hand-written
# CLIP normalisation). No detector reads it - each applies its own
# AutoImageProcessor to the native-resolution original. See CLAUDE.md: C1 v2
# should drop the tensor.
CLIP_BACKBONE_ID = "clip_vit_b32"  # ActivationBundle.backbone literal


# --------------------------------------------------------------------------
# Frequency features (FR-02, explainability only - no classifier)
# --------------------------------------------------------------------------
#
# The spectral pipeline is real signal processing and is retained to populate
# ActivationBundle.spectrum for M3's explainability. It produces NO score:
# there is no pretrained classifier compatible with this bespoke feature
# vector, and training one is out of scope permanently.

# [DECISION REQUIRED] PRD2 open issue OI-5: full native image vs fixed centre
# crop, and at what size. A fixed size is required for spectra to be
# comparable across images. Resolve by checkpoint I2.
FREQ_CROP_SIZE = 512

# Number of bins in the 1-D azimuthally averaged radial power spectrum.
FREQ_RADIAL_BINS = 128

# [DECISION REQUIRED] PRD2 item M2-C: whether the branch should operate per
# colour channel rather than on luminance. Resolve by ablation during
# milestone M2.2, not by argument.
FREQ_USE_LUMINANCE = True

# Optional high-pass residual (light Gaussian blur subtraction) to suppress
# scene content before the transform. Step 3 ablates whether it helps.
FREQ_HIGHPASS = True
FREQ_HIGHPASS_SIGMA = 1.0

FREQ_SCALAR_FEATURES = 4  # hf energy ratio, peak count, peak prominence, DCT block energy


# --------------------------------------------------------------------------
# Fusion and thresholding (FR-03 / FR-04)
# --------------------------------------------------------------------------

# Strategy A, weighted average. PRD2 open issue OI-1 also offered strategy B
# (a logistic meta-classifier), but fitting three coefficients on a validation
# split is model training, which is permanently out of scope. OI-1 is
# therefore closed in favour of A.
FUSION_STRATEGY = "weighted_average"

# PRD2 FR-03 strategy A, verbatim: fusion = w * semantic + (1 - w) * frequency.
#
# SELECTED ON A VALIDATION SPLIT, 2026-10-01 - not on the test set, and not by
# training anything. w and tau are both configuration constants, and FR-03
# describes strategy A as "one weight, tuned on validation"; CLAUDE.md section
# 0 forbids updating model WEIGHTS, which this is not. Step 4 had closed this
# as "fitting is training", a ruling made when no labelled data existed; see
# the session log.
#
# It was 0.5 (an unweighted average, chosen to prefer neither kind of
# evidence). Measurement showed that choice is what made MM2.6 expensive: at
# the false-positive rate MM2.6 demands, the equal-weight average yields
# recall 0.596, because SPAI is certain about 157 of the 198 validation fakes
# while their mean SigLIP score is only 0.577 - so averaging drags confident
# detections down to ~0.79 and a qualifying tau cuts 52 of them.
#
#   w       tau     FPR     recall   (validation, 198 real / 198 generated)
#   0.00    0.945   0.096   0.843    frequency branch alone
#   0.25    0.756   0.096   0.798    <- selected
#   0.50    0.667   0.096   0.596    the old value
#   1.00    0.950   0.096   0.192    semantic branch alone
#
# 0.25 rather than 0 because the semantic branch still earns its place: under
# degradation the fused score beats SPAI alone (RESULTS.md), so keeping some
# of it buys robustness that w = 0 would discard.
FUSION_WEIGHT = 0.25

# Decision threshold.
#
# SELECTED ON A VALIDATION SPLIT, 2026-10-01, by the rule PRD2 FR-03 states:
# the smallest tau whose false-positive rate on real photographs is at or
# below MM2.6's 0.10 - smallest because tau trades recall for FPR
# monotonically, so the smallest qualifying value keeps the most recall.
# Chosen by ml/evaluation/select_threshold.py on scenes 99-296 of the
# Synthbuster/RAISE set, which share no image with the test set reported in
# RESULTS.md.
#
# It was 0.5, the argmax boundary both detectors were trained on, which gave a
# false-positive rate of 0.162 against a 0.10 target. tau belongs with
# FUSION_WEIGHT above: changing either without the other invalidates both.
#
# What it is NOT: an operating point chosen to satisfy MM2.6. PRD2 FR-03 wants
# tau selected on a validation split to hold the false-positive rate on real
# photographs at or below 0.10. MEASURED 2026-09-30 (ml/evaluation/RESULTS.md):
# at this tau the FPR is 0.162 [0.10, 0.25] on pristine camera TIFFs, so
# **MM2.6 is missed**. Raising tau trades recall for it - tau = 0.99 gave
# FPR 0.051 at recall 0.798 on the test set - but choosing tau from the set you
# then report is fitting on the test set. Use ml/evaluation/select_threshold.py
# on a disjoint validation split instead.
FUSION_TAU = 0.7558

# Temperature scaling (PRD2 FR-04). A no-op at 1.0: nothing is fitted here.
# MEASURED 2026-09-30: expected calibration error is 0.097 (SPAI) and 0.089
# (fused) against MM2.5's <= 0.05, so **the fused score is not calibrated and
# MM2.5 is missed**. A temperature fitted on a disjoint validation split would
# close it, but T and tau are coupled - combine() scales the fused score and
# only then compares it to tau - so adopting a T means re-selecting tau
# underneath it, and changes every confidence figure shown to a user.
CALIBRATION_TEMPERATURE = 1.0
