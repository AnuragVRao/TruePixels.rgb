# Contract Documentation

Implementation-facing documentation for Contracts C1 through C5. PRD4 remains
the authoritative source; changes here must not silently diverge from it —
which is exactly why the divergences below are written down.

## C2 — InferenceOutput (M2 → M3): field set restored to PRD2 §7.3

M2 no longer trains its own classifiers. It runs two independently pretrained
models — one semantic, one frequency-domain — and fuses them. After an
interim revision (2026-09-07) that added a `secondary_score` field for a
second semantic detector, the field set is **back to exactly PRD2 §7.3** as of
2026-09-12. What changed is what produces the numbers, not their names or
meanings.

| Field | Status | Meaning now |
|---|---|---|
| `semantic_score` | unchanged | P(AI Generated) from the semantic branch, a pretrained SigLIP 2 fine-tune |
| `frequency_score` | **populated again**, typed `float \| None` | P(AI Generated) from the frequency branch — SPAI, a pretrained spectral detector reading the native-resolution image. Null **only** if that branch is disabled by configuration, in which case fusion is a documented passthrough of `semantic_score`. Never a stand-in number |
| `fusion_score` | unchanged | `0.5 · semantic + 0.5 · frequency` (PRD2 FR-03 strategy A), P(AI Generated) |
| `confidence_score` | unchanged | Confidence in the **predicted class** — see the inversion rule below |

`secondary_score` (interim, 2026-09-07 → 2026-09-12) **no longer exists**.
Nothing should read it.

**Implementers of M3:** treat a null `frequency_score` as "branch disabled",
render the absence, and do not substitute a zero.

### The inversion rule is unchanged

`semantic_score`, `frequency_score` and `fusion_score` are all
P(AI Generated). `confidence_score` is confidence in whichever class was
predicted:

```
predicted_class  = "AI Generated" if fusion_score >= tau else "Real"
confidence_score = fusion_score if predicted_class == "AI Generated" else 1.0 - fusion_score
```

A `fusion_score` of 0.08 is **"Real" at 0.92 confidence**. M3 is expected to
assert this independently from its own side.

## C1 — PreprocessedImage (M1 → M2): unchanged, but one field is now dead

M2 **no longer reads `tensor_ref`**. Both branches preprocess the
native-resolution `source_reference` themselves: SigLIP 2 with its own
`AutoImageProcessor`, and SPAI by tiling the full image into 224×224 patches
that must never come from a resized copy. No single shared tensor can serve
both.

The contract is preserved as written and the field is still populated, but
**C1 v2 should drop `tensor_ref`, `shape`, `dtype` and `normalization` before
M1 is implemented** — otherwise M1's owner will build a CLIP-normalised tensor
that nothing consumes. Flagged here rather than changed unilaterally, since
C1 is jointly owned.

What M2 does still require from C1 is unchanged and load-bearing:
`source_reference` must point at the **losslessly decoded original**, not a
resampled copy.

## C4 — Model management: what "a model version" means now

D3 rows will record **which third-party checkpoint was active**, not an
artefact this project produced — a Hugging Face id for the semantic branch, a
weights file plus the pinned digest of its contents for the frequency branch.
FR-06's canary forward pass still applies with full force: a checkpoint that
fails to load, whose weights do not match their digest, whose labels cannot be
resolved to an AI class, or whose parameter set does not match the
architecture exactly, must be rejected in front of the administrator
registering it rather than in front of a user.
