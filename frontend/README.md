# Frontend

React 18 interface for general users and administrators.

The frontend presents M3-owned result, history, reporting, dashboard, account-management, and model-management screens. It calls M1 and M2 administrative endpoints through M3-facing workflows and must not write directly to backend data stores.

## Folders

- `src/`: application source.
- `src/components/`: reusable interface components.
- `src/pages/`: route-level screens.
- `src/services/`: HTTP clients and API adapters.
- `src/types/`: frontend representations of API contracts.
- `src/hooks/`: reusable React hooks.
- `src/assets/`: images, icons, and other frontend assets.