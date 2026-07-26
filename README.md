# HDX-08

HDX-08 is Version 1 of a modular AI trading-system architecture. It is deliberately an **analysis and research platform**, not a trading bot: it contains no broker integration, live market execution, or automatic order placement.

## Installation

```powershell
pip install -r requirements.txt
Copy-Item .env.example .env
python main.py
```

## Usage

Start the local API with `python main.py`, then retrieve a live, read-only Yahoo Finance quote:

Alternatively, use Uvicorn directly:

```powershell
uvicorn app.main:app --reload
```

```powershell
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/market/AAPL
```

Example response:

```json
{
  "symbol": "AAPL",
  "price": 212.15,
  "open": 210.34,
  "high": 214.2,
  "low": 209.9,
  "previous_close": 211.0,
  "volume": 54832112,
  "currency": "USD",
  "exchange": "NMS",
  "timestamp": "2026-01-01T00:00:00Z"
}
```

Quote and historical calls use yfinance, retry transient failures, enforce an eight-second provider timeout, and cache successful responses for 60 seconds. Provider failures return a structured error response rather than crashing the API.

Run the analysis workflow:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/analyze -ContentType 'application/json' -Body '{"symbol":"AAPL"}'
```

The response contains planner, scanner, signal, trade-planning, risk, decision, and monitoring stages, plus a SQLite audit ID. The scanner uses the market-data service; the resulting decision is always non-executable.

Google ADK and Gemini are included behind an optional, non-executing research-agent boundary (`agents/gemini_research.py`). Add `GEMINI_API_KEY` to `.env` only when integrating a controlled research-summarization flow; the local mock workflow does not call external AI services.

## Structure

`app/services/market_data.py` provides the resilient Yahoo Finance adapter and its Pydantic data models.

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
