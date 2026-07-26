# HDX-08

HDX-08 is Version 1 of a modular AI trading-system architecture. It is deliberately an **analysis and research platform**, not a trading bot: it contains no broker integration, live market execution, or automatic order placement.

## Quick start

```powershell
pip install -r requirements.txt
Copy-Item .env.example .env
python main.py
```

Send a mocked analysis request:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/analyze -ContentType 'application/json' -Body '{"symbol":"AAPL"}'
```

The response contains planner, scanner, signal, trade-planning, risk, decision, and monitoring stages, plus a SQLite audit ID. The resulting decision is always non-executable.

Google ADK and Gemini are included behind an optional, non-executing research-agent boundary (`agents/gemini_research.py`). Add `GEMINI_API_KEY` to `.env` only when integrating a controlled research-summarization flow; the local mock workflow does not call external AI services.

## Structure

- `agents/` — seven single-responsibility workflow agents.
- `tools/` — protocol interfaces and safe local mock adapters.
- `api/` — FastAPI delivery layer and Pydantic contracts.
- `database/` — SQLite audit persistence.
- `memory/` — workflow-scoped state.
- `docs/` — architecture, installation, roadmap, and developer guide.

## Design

The application uses constructor injection to keep business workflow logic independent of external adapters. See [architecture documentation](docs/architecture.md), [installation guide](docs/installation.md), [developer guide](docs/developer-guide.md), and [roadmap](docs/roadmap.md).

## Safety boundary

HDX-08 does not place, route, simulate, or automatically execute orders. Any future capability expansion should undergo dedicated technical, security, compliance, and human-review design.
