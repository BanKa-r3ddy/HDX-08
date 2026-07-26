# Developer Guide

Each agent has exactly one analysis responsibility and implements `AnalysisAgent.run`. Integrations are defined in `tools/interfaces.py` using `Protocol`; provide concrete adapters through constructors rather than importing infrastructure inside agents. Keep outputs informational, auditable, and non-executable.

Run tests with `python -m pytest`. Run the offline smoke check with `python scripts/healthcheck.py`.
