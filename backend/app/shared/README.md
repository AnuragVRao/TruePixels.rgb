# Shared Backend Layer

Cross-cutting backend code used by M1, M2, and M3. This is the home for request dependencies, configuration, database session wiring, common errors, and the binding integration contracts.

Do not place module-specific business rules here. Changes to contracts must be reviewed against PRD4 and the contract tests.