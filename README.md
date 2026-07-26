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

Retrieve a technical summary calculated from six months of daily OHLCV data:

```powershell
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/analyze/AAPL
```

Example response:

```json
{
  "symbol": "AAPL",
  "price": 333.02,
  "analysis": {
    "trend": "Bullish",
    "rsi": 62.3,
    "macd": "Bullish",
    "volume": "Above Average",
    "strength": "Strong",
    "support": 324.4,
    "resistance": 337.8
  }
}
```

The technical engine calculates SMA (20/50/200), EMA (9/21/50), RSI-14, MACD, Bollinger Bands, ATR-14, VWAP, and 20-period volume average. This is informational analysis only; it does not place trades.

Run the analysis workflow:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/analyze -ContentType 'application/json' -Body '{"symbol":"AAPL"}'
```

The response contains planner, scanner, signal, trade-planning, risk, decision, and monitoring stages, plus a SQLite audit ID. The scanner uses the market-data service; the resulting decision is always non-executable.

Google ADK and Gemini are included behind an optional, non-executing research-agent boundary (`agents/gemini_research.py`). Add `GEMINI_API_KEY` to `.env` only when integrating a controlled research-summarization flow; the local mock workflow does not call external AI services.

## Structure

`app/services/market_data.py` provides the resilient Yahoo Finance adapter and its Pydantic data models.

`app/services/technical_analysis.py` provides the pandas/NumPy/`ta` technical-analysis engine.

## Multi-agent architecture

HDX-08 also exposes a dependency-injected multi-agent lifecycle. Each agent receives an `AgentContext`, returns an `AgentResult`, and may safely enrich the context without coupling to a global service.

```mermaid
flowchart LR
    P[Planner Agent] --> S[Scanner Agent]
    S --> T[Technical Agent]
    T --> D[Decision Agent]
    D --> M[Memory Agent]
    M --> R[Final Context]
    S --> MD[Market Data Service]
    T --> TA[Technical Analysis Service]
    D --> G[Gemini Service]
    M --> DB[(SQLite Memory)]
```

Run it with:

```powershell
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/run/AAPL
```

The endpoint returns the request ID, completed agents, execution duration, market data, technical analysis, and AI explanation. The memory agent stores only request ID, symbol, timestamp, AI summary, confidence, and trend in local SQLite.

### Adding an agent

Create a class in `app/agents/` with a unique `name`, `enabled_by_default = True`, and `run(context) -> AgentResult`. Inject its dependencies through the constructor and add its instance to `build_orchestrator`. The Planner reads the registered enabled agent list, so compatible future agents (for example News, Risk, Macro, or Social Sentiment) participate without changes to the orchestrator itself.

## Gemini market explanation

Add your Google Gemini API key to `.env`:

```text
GOOGLE_API_KEY=your_key_here
```

The service uses `google-genai` to explain only the supplied market and technical JSON. It enforces structured JSON output, validates it with Pydantic, retries transient failures, and returns a safe error object if credentials or Gemini are unavailable. It never creates orders or trade instructions.

```powershell
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/ai-analysis/AAPL
```

The response contains `market_data`, `technical_analysis`, and `ai_analysis`. AI analysis is informational only and must use `Insufficient Data` where the supplied data cannot support a conclusion.

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
