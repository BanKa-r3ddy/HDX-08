"""Historical replay agent that reuses the existing HDX-08 agent components."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any
from uuid import uuid4

import pandas as pd

from app.models.backtest import BacktestConfig, BacktestResult, EquityPoint
from app.services.backtest_service import calculate_metrics
from app.services.market_data import HistoricalBar, MarketDataError, MarketHistory, MarketQuote
from app.services.paper_trading_service import PaperTradingService
from .decision_agent import DecisionAgent
from .memory_agent import MemoryAgent
from .models import AgentContext
from .news_agent import NewsAgent
from .paper_trading_agent import PaperTradingAgent
from .planner_agent import PlannerAgent
from .scanner_agent import ScannerAgent
from .technical_agent import TechnicalAgent


class HistoricalReplayMarketData:
    """Market-data adapter that exposes a moving historical window to ScannerAgent."""

    def __init__(self, symbol: str, history: pd.DataFrame, window: int = 250) -> None:
        self._symbol, self._history, self._window, self._position = symbol.upper(), self._normalize(history), window, 0

    def advance(self, position: int) -> None:
        """Advance the visible daily candle without retaining duplicated history frames."""
        self._position = position

    def get_quote(self, symbol: str) -> MarketQuote | MarketDataError:
        """Return the current replay candle as a normalized quote."""
        if symbol.upper() != self._symbol or self._position >= len(self._history):
            return MarketDataError(symbol=symbol, code="provider_error", error="Replay candle is unavailable")
        current = self._history.iloc[self._position]
        previous = self._history.iloc[max(0, self._position - 1)]
        return MarketQuote(symbol=self._symbol, price=float(current["Close"]), open=float(current["Open"]), high=float(current["High"]),
                           low=float(current["Low"]), previous_close=float(previous["Close"]), volume=int(current["Volume"]),
                           currency=None, exchange="BACKTEST", timestamp=self._timestamp(self._history.index[self._position]))

    def get_history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> MarketHistory | MarketDataError:
        """Return an ending-at-current-candle historical window for technical analysis."""
        if symbol.upper() != self._symbol:
            return MarketDataError(symbol=symbol, code="invalid_symbol", error="Replay symbol does not match")
        start = max(0, self._position - self._window + 1)
        window = self._history.iloc[start:self._position + 1]
        bars = [HistoricalBar(timestamp=self._timestamp(index), open=float(row["Open"]), high=float(row["High"]),
                              low=float(row["Low"]), close=float(row["Close"]), volume=int(row["Volume"]))
                for index, row in window.iterrows()]
        return MarketHistory(symbol=self._symbol, period=period, interval=interval, bars=bars)

    @staticmethod
    def _normalize(history: pd.DataFrame) -> pd.DataFrame:
        required = ["Open", "High", "Low", "Close", "Volume"]
        missing = set(required).difference(history.columns)
        if history.empty or missing:
            raise ValueError(f"Historical replay data is missing columns: {', '.join(sorted(missing))}")
        return history[required].dropna().sort_index()

    @staticmethod
    def _timestamp(value: object) -> datetime:
        timestamp = pd.Timestamp(value).to_pydatetime()
        return timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp


class BacktestAgent:
    """Replays daily candles through existing agents and a virtual-paper portfolio."""

    def __init__(self, planner: PlannerAgent, technical: TechnicalAgent, decision: DecisionAgent,
                 paper_trading: PaperTradingAgent, memory: MemoryAgent, paper_service: PaperTradingService,
                 news: NewsAgent | None = None) -> None:
        self._planner, self._technical, self._decision = planner, technical, decision
        self._paper_trading, self._memory, self._paper_service, self._news = paper_trading, memory, paper_service, news
        self._logger = logging.getLogger("hdx08.backtest.agent")

    def run(self, configuration: BacktestConfig, history: pd.DataFrame) -> BacktestResult:
        """Replay daily OHLCV candles via existing agents and persist only portfolio state."""
        if configuration.strategy_name != "ema_trend_v1":
            raise ValueError("Only the ema_trend_v1 paper strategy is currently supported")
        replay = HistoricalReplayMarketData(configuration.symbol, history)
        scanner = ScannerAgent(replay)
        self._paper_service.trade_manager.reset(configuration.initial_capital)
        equity_curve: list[EquityPoint] = []
        previous_value = configuration.initial_capital
        first_position = min(49, len(history) - 1)
        for position in range(first_position, len(history)):
            replay.advance(position)
            context = AgentContext.for_symbol(configuration.symbol)
            context.metadata["available_agents"] = ["Planner", "Scanner", "Technical", "Decision", "PaperTrading", "Memory"]
            context = self._planner.run(context).updated_context
            context = scanner.run(context).updated_context
            context = self._technical.run(context).updated_context
            if configuration.include_news and self._news is not None:
                context = self._news.run(context).updated_context
            context = self._decision.run(context).updated_context
            context.metadata["paper_action"] = self._strategy_action(context)
            context = self._paper_trading.run(context).updated_context
            context = self._memory.run(context).updated_context
            snapshot = self._paper_service.trade_manager.get_portfolio()
            value = snapshot.portfolio_value
            equity_curve.append(EquityPoint(date=pd.Timestamp(history.index[position]).date(), portfolio_value=value,
                                            cash=snapshot.cash_balance, open_positions=len(snapshot.open_positions),
                                            daily_return=round(((value - previous_value) / previous_value) * 100, 6) if previous_value else 0.0))
            previous_value = value
        self._close_remaining_position(configuration.symbol, float(history.iloc[-1]["Close"]))
        final_snapshot = self._paper_service.trade_manager.get_portfolio()
        if equity_curve:
            equity_curve[-1] = equity_curve[-1].model_copy(update={"portfolio_value": final_snapshot.portfolio_value,
                                                                      "cash": final_snapshot.cash_balance, "open_positions": 0,
                                                                      "daily_return": round(((final_snapshot.portfolio_value - previous_value) / previous_value) * 100, 6) if previous_value else 0.0})
        trades = self._paper_service.trade_manager.get_trade_history()
        metrics = calculate_metrics(configuration.initial_capital, trades, equity_curve)
        result = BacktestResult(backtest_id=str(uuid4()), created_at=datetime.now(timezone.utc), configuration=configuration,
                                summary=f"{configuration.strategy_name} replayed {len(equity_curve)} daily candles for {configuration.symbol.upper()}.",
                                trade_history=trades, equity_curve=equity_curve, performance_metrics=metrics)
        self._logger.info("backtest_replay_completed", extra={"backtest_id": result.backtest_id, "symbol": configuration.symbol, "candles": len(equity_curve), "trades": len(trades)})
        return result

    def _strategy_action(self, context: AgentContext) -> dict[str, Any]:
        """Create explicit virtual actions from existing technical output only, never live orders."""
        summary = (context.technical_analysis or {}).get("summary", {})
        trend, rsi = summary.get("trend"), summary.get("rsi")
        open_positions = self._paper_service.trade_manager.get_open_positions()
        is_open = any(position.symbol == context.symbol for position in open_positions)
        if is_open and (trend == "Bearish" or (isinstance(rsi, (float, int)) and rsi >= 75)):
            return {"action": "SELL", "trade_id": next(position.trade_id for position in open_positions if position.symbol == context.symbol)}
        if not is_open and trend == "Bullish" and isinstance(rsi, (float, int)) and rsi < 70:
            price = float((context.market_data or {}).get("price", 0))
            return {"action": "BUY", "confidence": 75, "reasoning": ["Backtest ema_trend_v1: bullish EMA alignment with RSI below 70"],
                    "stop_loss": round(price * 0.97, 4), "take_profit": round(price * 1.06, 4)}
        return {"action": "NONE"}

    def _close_remaining_position(self, symbol: str, final_price: float) -> None:
        """Close any ending virtual position to produce final realized backtest metrics."""
        for trade in self._paper_service.trade_manager.get_open_positions():
            if trade.symbol == symbol.upper():
                self._paper_service.trade_manager.close_trade(trade.trade_id, final_price, "CLOSED")
