# Runtime storage

Files the backend writes at run time. **Everything here is gitignored.**

- `uploads/`: validated originals, EXIF-stripped, stored under their content
  hash.
- `explainability/`: the explanation panels (PNG) for each prediction.
- `models/`: `spai.safetensors`, uploaded model heads, and the quality gate's
  reference cache.
- `tensors/`: no longer written (M1's old CLIP tensor). It can be empty.

Never commit user images or model files. Tests use a scratch directory
(`STORAGE_DIR`), never this one.
