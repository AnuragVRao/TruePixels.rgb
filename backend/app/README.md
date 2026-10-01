# Application Source

FastAPI application package. Keep business logic inside the owning module and use `shared` only for deliberately cross-cutting concerns.

## Folders

- `m1_access/`: M1 image and access management.
- `m2_analysis/`: M2 image analysis and prediction.
- `m3_results/`: M3 results and reporting management.
- `stubs/`: M3's test-only stand-ins for M1 and M2; imported only by `backend/tests/m3`.
- `shared/`: shared configuration, persistence wiring, dependencies, and contracts.