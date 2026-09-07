# Application Source

FastAPI application package. Keep business logic inside the owning module and use `shared` only for deliberately cross-cutting concerns.

## Folders

- `m1_access/`: M1 image and access management.
- `m2_analysis/`: M2 image analysis and prediction.
- `m3_reporting/`: M3 results and reporting management.
- `shared/`: shared configuration, persistence wiring, dependencies, and contracts.