# PROJECT_CONTEXT

## Purpose
The **Nutrition Calculator** dataset models a multi-module web product where a React UI and FastAPI service provide:
- Daily calorie and macro calculations from user profile inputs.
- User authentication and session restore flows.
- Calculation history retention and retrieval.
- Export of historical results for downstream use.
- Observable, traceable request workflows across UI/API/CORE/DATA/OBS/SHARED modules.

## Module Architecture
The design spec uses these module roles:

- **UI (frontend)**
  - Renders calculator, login, history, and export interfaces.
  - Triggers API requests from explicit user actions.
  - Handles loading/success/error state transitions.

- **API (api)**
  - Exposes HTTP endpoints for calculation, auth, history, and export.
  - Validates requests, enforces auth scope, orchestrates downstream modules.
  - Shapes deterministic response envelopes and error payloads.

- **CORE (domain)**
  - Provides deterministic nutrition/domain logic:
    BMR/TDEE, goal adjustment, macro allocation, rounding reconciliation.
  - Provides auth/export domain policies (password verification, export payload build).

- **DATA (infra)**
  - Integrates external/provider and persistence concerns:
    credential lookup, history storage, export artifact storage.
  - Handles provider handshake, retry, timeout, and data retrieval workflows.

- **SHARED (shared)**
  - Owns canonical DTO contracts used across UI/API/CORE.
  - Keeps request/response schemas aligned for auth, calculation, and export paths.

- **OBS (infra)**
  - Captures structured logs and metrics for request lifecycles.
  - Records timing/status telemetry for calculation, auth, history, and export flows.

## Workflow Overview

1) **Authentication and session bootstrap**
- UI presents login workflow and sends auth request to API.
- API parses request, queries DATA credential store, invokes CORE verification.
- API issues tokens and returns login/session payload.
- UI stores session state and restores authenticated context on app startup.

2) **Nutrition calculation**
- UI captures profile input and triggers calculation request.
- API validates and normalizes input, then invokes CORE calculation workflows.
- CORE computes deterministic outputs.
- API returns a structured response envelope; UI renders results and user-facing errors.

3) **History retention and retrieval**
- After successful calculation, DATA persists history records under user scope.
- UI History page sends filtered queries.
- API authorizes query scope and coordinates DATA reads.
- UI displays paginated history and supports restore-to-form interactions.

4) **Result export**
- UI opens export modal and submits export parameters.
- API validates request and invokes CORE export payload build.
- DATA stores generated artifacts and returns metadata.
- API returns download link metadata; UI presents download action.

5) **Observability and traceability**
- OBS records workflow metrics and logs with request identifiers.
- API middleware ensures request_id propagation across module interactions.

## Design-Spec Drafting Assumptions for this Dataset
- Requirements are written in EARS-style and remain deterministic/testable.
- Cross-module interactions are split into paired specs (sender and receiver).
- Subunits are generalized and shared by workflow part (for example `user_management`, `history_management`, `export_management`).

## Note
- Focus on explicit workflow behavior and acceptance criteria in each design spec row.
- Avoid relying on appendix references not present in this dataset.
