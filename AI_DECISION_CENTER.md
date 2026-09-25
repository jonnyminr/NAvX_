# NAV-X AI Decision Center

This build uses a **structured AI decision layer**, not a free-form conversational interface.

## What it does

1. Reads the already-calculated FASTEST / BALANCED / SAFEST route evidence.
2. Displays the backend recommendation only when the route engine has issued one.
3. Compares available risk score, ETA, distance, CPA, iceberg clearance, time-matched hazards, and sea-ice exposure.
4. Shows quantified evidence supporting the recommendation and the operational trade-offs.
5. Displays the physics-informed iceberg ML model card and validation gate.
6. Displays AIS Isolation Forest anomaly scoring when a model has been trained from genuine AIS observations.

## What it does not do

- It does not use a generative LLM.
- It does not invent missing scientific measurements.
- It does not issue autonomous navigation commands.
- It does not label an AIS anomaly as dangerous intent.
- It does not claim a supervised navigation-risk ML model where verified outcome labels do not exist.

## Main endpoints

- `GET /api/ai/status`
- `POST /api/ai/decision-support`
- `GET /api/ai/vessel-anomalies`

The decision-support endpoint accepts the current NAV-X route result as structured context and returns structured JSON containing readiness, recommendation, reasons, trade-offs, route matrix, model contribution, and evidence completeness.
