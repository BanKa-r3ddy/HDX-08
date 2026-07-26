"""ASGI application module for ``uvicorn app.main:app``."""
from __future__ import annotations

from api.app import create_app
from app.services.market_data import MarketDataService
from main import build_workflow


# A single injected service instance is shared by the HTTP endpoint and scanner,
# so 60-second quote caching applies consistently across both code paths.
market_data_service = MarketDataService()
app = create_app(build_workflow(market_data_service), market_data_service)
