# Architecture

HDX-08 follows Clean Architecture: the API is a delivery adapter, agents hold application orchestration, tool protocols define infrastructure boundaries, and SQLite is an outbound persistence adapter. Dependencies point inward through Python protocols and constructor injection.

```mermaid
flowchart LR
    Client --> API[FastAPI /analyze]
    API --> W[Analysis Workflow]
    W --> P[Planner]
    W --> S[Scanner]
    W --> G[Signal]
    W --> T[Trade Planner]
    W --> R[Risk Manager]
    W --> D[Decision]
    W --> M[Monitoring]
    S --> Tools[Market data / News / Indicators]
    W --> DB[(SQLite audit store)]
```

No component has broker credentials, order-routing code, or live-execution capability.
