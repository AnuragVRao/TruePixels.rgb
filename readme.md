# TruePixels.rgb

AI-generated image detection system based on the four product requirement documents in this repository.

## Project structure

```text
TruePixels.rgb/
├── backend/        FastAPI application and database migrations
├── frontend/       React user and administrator interface
├── ml/             Training, evaluation, and experiment assets
├── storage/        Local development storage layout for files and artefacts
├── infra/          Containers, database setup, and deployment scripts
├── docs/           Architecture, contracts, and technical decisions
├── tests/          Cross-module contract, integration, and end-to-end tests
└── PRD*.md         Product requirements and module specifications
```

## Module ownership

- `backend/app/m1_access`: M1, image access management, authentication, validation, and preprocessing.
- `backend/app/m2_analysis`: M2, model inference, fusion, prediction persistence, and model registry.
- `backend/app/m3_reporting`: M3, explainability, results, history, reports, administration, and logging.
- `backend/app/shared`: shared configuration, database wiring, dependencies, and cross-module contracts.
- `frontend`: React screens that consume the backend APIs.
- `ml`: Offline training and evaluation. Training data and model artefacts are not committed here.

## Planned technology baseline

- Backend: Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic.
- Database: PostgreSQL 15 with `citext`.
- Image and tensor processing: Pillow and NumPy.
- Inference: PyTorch 2.x and Hugging Face Transformers.
- Frontend: React 18.

## Getting started

This commit establishes the project layout only. Implementation, dependency manifests, environment configuration, and run commands will be added after the open decisions in the PRDs are resolved.

Read the README in each top-level folder before adding code there. Cross-module changes must follow `docs/contracts/` and the integration rules in `PRD4_Shared_Interface_Integration.md`.
