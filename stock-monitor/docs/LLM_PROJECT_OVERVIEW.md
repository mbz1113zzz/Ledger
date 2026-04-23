# Stock Monitor LLM Project Overview

## 1. What This Project Is

This repository is a FastAPI-based US stock monitoring and paper-trading system.

It combines two parallel lanes:

1. Event monitoring and alerting
2. IBKR-driven realtime SMC paper trading

At a high level, it does four jobs:

1. Poll external sources such as Finnhub and SEC Edgar for news, filings, earnings, analyst changes, sentiment, and price alerts
2. Stream realtime market data from IBKR, derive market structure, and generate SMC entry signals
3. Execute paper trades with risk controls, ledger persistence, review reports, and execution-mode guardrails
4. Expose everything through a web UI, REST APIs, and SSE notifications

## 2. Runtime Shape

Main entrypoint: [app.py](/Users/mabizheng/Desktop/美股/stock-monitor/app.py)

When the app starts, `create_app()` wires together:

- `Storage`
- `Notifier`
- `WatchlistManager`
- news/event polling pipeline
- price alert polling pipeline
- `PaperBroker`
- `ExecutionModeController`
- optional IBKR `StreamingRunner`

During FastAPI lifespan startup:

1. SQLite schema is initialized
2. retention cleanup runs
3. scheduler jobs are started
4. IBKR streaming runner is started if enabled
5. a background startup sync loads the SEC ticker map and runs both pipelines once

## 3. Core Data Flow

### 3.1 News / event polling lane

Main files:

- [scheduler.py](/Users/mabizheng/Desktop/美股/stock-monitor/scheduler.py)
- [pipeline.py](/Users/mabizheng/Desktop/美股/stock-monitor/pipeline.py)
- [sources/](/Users/mabizheng/Desktop/美股/stock-monitor/sources)

Flow:

1. `scheduler.py` builds source objects
2. `Pipeline.run_once()` calls `fetch(tickers)` on each source
3. events are deduplicated
4. event importance is scored
5. optional LLM enrichment adds Chinese summaries
6. new events are stored in SQLite
7. events are published through SSE and optionally push channels

Important source modules:

- `sources/finnhub.py`: news + earnings calendar
- `sources/sec_edgar.py`: SEC filings
- `sources/analyst.py`: analyst upgrades/downgrades
- `sources/sentiment.py`: Finnhub news sentiment spike detector
- `sources/price_alerts.py`: price anomaly alerts
- `sources/health.py`: request counters, error classification, auto-disable, diagnostics snapshots

### 3.2 Realtime trading lane

Main files:

- [streaming/runner.py](/Users/mabizheng/Desktop/美股/stock-monitor/streaming/runner.py)
- [sources/ibkr_realtime.py](/Users/mabizheng/Desktop/美股/stock-monitor/sources/ibkr_realtime.py)
- [streaming/signal_router.py](/Users/mabizheng/Desktop/美股/stock-monitor/streaming/signal_router.py)
- [paper/](/Users/mabizheng/Desktop/美股/stock-monitor/paper)
- [smc/](/Users/mabizheng/Desktop/美股/stock-monitor/smc)

Flow:

1. `IbkrClient` subscribes to ticks and realtime bars
2. `StreamingRunner` feeds:
   - anomaly detection
   - 1m / 5m bar aggregation
   - SMC structure tracking
3. SMC engine emits `SmcSignal`
4. `SignalRouter` persists structure / signal / execution-intent events
5. depending on execution mode:
   - `paper`: queue and fill paper trades
   - `dry_live`: observe only, emit execution intent
   - `live`: currently still guarded / not fully implemented
6. `PaperBroker` manages entries, stop/take-profit, break-even, timeout, EOD flattening
7. `Ledger` persists positions, trades, and equity snapshots

## 4. Important Subsystems

### 4.1 Web app and APIs

Main file: [web/routes.py](/Users/mabizheng/Desktop/美股/stock-monitor/web/routes.py)

The web layer serves both the SPA-like frontend and JSON APIs.

Important endpoints:

- `/`: main dashboard HTML
- `/stream`: SSE stream for realtime updates
- `/api/events`: event feed
- `/api/watchlist`: add/remove/watch tickers
- `/api/health`: coarse health
- `/api/diagnostics`: startup, source metrics, pipeline telemetry, IBKR telemetry, execution status
- `/api/execution-mode`: current execution guardrail state and mode switching
- `/api/paper/*`: positions, trades, equity, review, stats
- `/api/smc/structure`: structure events
- `/api/chart`: chart payload with candles, structure overlays, trades, liquidity, order blocks
- `/api/backtest`: event backtesting

Frontend files:

- [web/static/index.html](/Users/mabizheng/Desktop/美股/stock-monitor/web/static/index.html)
- [web/static/app.js](/Users/mabizheng/Desktop/美股/stock-monitor/web/static/app.js)
- [web/static/style.css](/Users/mabizheng/Desktop/美股/stock-monitor/web/static/style.css)

The UI is operator-oriented, not just trader-oriented. Recent additions include:

- diagnostics modal
- execution readiness panel
- chart overlays
- paper review / stats views

### 4.2 Paper trading

Main files:

- [paper/broker.py](/Users/mabizheng/Desktop/美股/stock-monitor/paper/broker.py)
- [paper/ledger.py](/Users/mabizheng/Desktop/美股/stock-monitor/paper/ledger.py)
- [paper/strategy.py](/Users/mabizheng/Desktop/美股/stock-monitor/paper/strategy.py)
- [paper/review.py](/Users/mabizheng/Desktop/美股/stock-monitor/paper/review.py)
- [paper/execution.py](/Users/mabizheng/Desktop/美股/stock-monitor/paper/execution.py)

Responsibilities:

- `PaperBroker`: trade lifecycle, pending entries, fill logic, slippage, fees, open-risk / gross-exposure gates, day drawdown halt
- `Ledger`: positions, realized/unrealized PnL, cash, equity snapshots
- `SmcLongStrategy`: sizing logic
- `build_daily_review()`: end-of-day review markdown
- `ExecutionModeController`: `paper`, `dry_live`, `live` mode state and readiness thresholds

### 4.3 SMC engine

Main files:

- [smc/structure.py](/Users/mabizheng/Desktop/美股/stock-monitor/smc/structure.py)
- [smc/order_block.py](/Users/mabizheng/Desktop/美股/stock-monitor/smc/order_block.py)
- [smc/liquidity.py](/Users/mabizheng/Desktop/美股/stock-monitor/smc/liquidity.py)
- [smc/engine.py](/Users/mabizheng/Desktop/美股/stock-monitor/smc/engine.py)
- [smc/types.py](/Users/mabizheng/Desktop/美股/stock-monitor/smc/types.py)

The design target is:

- 5m structure
- 1m entries
- liquidity sweep + BOS / CHoCH + order-block retest logic

Good background docs:

- [docs/superpowers/specs/2026-04-19-ibkr-realtime-paper-trading-design.md](/Users/mabizheng/Desktop/美股/stock-monitor/docs/superpowers/specs/2026-04-19-ibkr-realtime-paper-trading-design.md)
- [docs/2026-04-21-diagnostics-phase-requirements.md](/Users/mabizheng/Desktop/美股/stock-monitor/docs/2026-04-21-diagnostics-phase-requirements.md)
- [docs/2026-04-21-next-expansion-plan.md](/Users/mabizheng/Desktop/美股/stock-monitor/docs/2026-04-21-next-expansion-plan.md)

## 5. Persistence Model

Main file: [storage.py](/Users/mabizheng/Desktop/美股/stock-monitor/storage.py)

SQLite is the only persistent store.

Key tables:

- `events`: news, filings, price alerts, SMC signals, execution intents
- `smc_structure`: BOS / CHoCH / swing / OB / liquidity events
- `paper_trades`: entry and exit trades, including PnL, RR, fee
- `paper_equity`: equity snapshots
- `paper_positions`: current open paper positions

Operational notes:

- SQLite runs in WAL mode
- schema upgrades are handled lazily in `init_schema()`
- the repo currently contains a local DB at `data/events.db`

## 6. External Dependencies and Integrations

Configured in [config.py](/Users/mabizheng/Desktop/美股/stock-monitor/config.py).

Main integrations:

- Finnhub
- SEC Edgar
- IBKR / `ib_insync`
- Telegram / Bark / Feishu pushers
- optional LLM enrichment via Anthropic or DeepSeek

Important environment concepts:

- IBKR can be toggled with `IBKR_ENABLED`
- execution guardrails are controlled by `EXECUTION_MODE`, `LIVE_TRADING_ENABLED`, and `LIVE_EXECUTION_IMPLEMENTED`
- paper-trading risk parameters are all in config

## 7. Testing and Environment

This project should be worked on in the conda environment:

```bash
conda run -n stock-monitor python --version
```

Current verified environment in this workspace:

- conda env: `stock-monitor`
- Python: `3.11.15`

Useful commands:

```bash
conda run -n stock-monitor python -m pytest -q
conda run -n stock-monitor python -m pytest -q tests/test_execution_mode.py tests/test_diagnostics_route.py tests/test_routes_smc.py
conda run -n stock-monitor python -c "import app; print(app.app.title)"
```

Notes:

- running plain system `python3` may use Python 3.9, which is too old for this codebase
- use the conda env for all test and runtime work

## 8. Suggested Reading Order For Another Model

If a new model needs to ramp up quickly, read in this order:

1. [app.py](/Users/mabizheng/Desktop/美股/stock-monitor/app.py)
2. [config.py](/Users/mabizheng/Desktop/美股/stock-monitor/config.py)
3. [scheduler.py](/Users/mabizheng/Desktop/美股/stock-monitor/scheduler.py)
4. [pipeline.py](/Users/mabizheng/Desktop/美股/stock-monitor/pipeline.py)
5. [web/routes.py](/Users/mabizheng/Desktop/美股/stock-monitor/web/routes.py)
6. [streaming/runner.py](/Users/mabizheng/Desktop/美股/stock-monitor/streaming/runner.py)
7. [paper/broker.py](/Users/mabizheng/Desktop/美股/stock-monitor/paper/broker.py)
8. [paper/ledger.py](/Users/mabizheng/Desktop/美股/stock-monitor/paper/ledger.py)
9. [paper/execution.py](/Users/mabizheng/Desktop/美股/stock-monitor/paper/execution.py)
10. [storage.py](/Users/mabizheng/Desktop/美股/stock-monitor/storage.py)

Then read the design docs in `docs/`.

## 9. Practical Modification Guidelines

When changing this project, keep these coupling points in mind:

1. API payload changes often require matching updates in `web/static/app.js` and tests
2. Paper-trading changes usually touch `paper/broker.py`, `paper/ledger.py`, `storage.py`, and related tests together
3. Diagnostics changes usually span source modules, `SourceHealth`, routes, and frontend modal rendering
4. Streaming changes often affect both `streaming/runner.py` and the SMC modules
5. Config changes should be traced through app wiring, scheduler jobs, and tests

## 10. Current System Character

The project is best thought of as:

- a stock event monitor
- plus an IBKR-first intraday paper-trading sandbox
- plus an operator dashboard for diagnosing market-data and execution readiness

It is not yet a true live-trading engine. The codebase is currently in a guarded transition phase from paper trading toward dry-live / eventually live execution.
