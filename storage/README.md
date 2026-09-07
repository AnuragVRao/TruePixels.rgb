# Runtime Storage

Local-development layout for file references used by the backend. Production deployments should map these paths to managed or shared persistent storage.

## Folders

- `uploads/`: validated original image files and temporary upload workspace.
- `tensors/`: deterministic `.npy` tensors produced by M1.
- `models/`: registered model artefacts used by M2.
- `explainability/`: visualisations produced by M3.

Do not commit user images, model binaries, tensors, or generated reports.