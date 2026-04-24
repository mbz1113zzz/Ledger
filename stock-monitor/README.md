# Stock Monitor

FastAPI-based US equities monitoring and paper-trading system. Combines
two parallel lanes:

1. **Event monitoring** — polls Finnhub, SEC EDGAR, analyst feeds, etc.
   and classifies/pushes alerts.
2. **IBKR realtime SMC paper trading** — streams ticks/bars from IBKR,
   derives market structure, generates entry signals, and executes paper
   trades with risk guardrails.

Everything surfaces through a web UI, REST API, and SSE notifications.

See [`docs/LLM_PROJECT_OVERVIEW.md`](docs/LLM_PROJECT_OVERVIEW.md) for a
full architectural tour.

## Requirements

- Python 3.11+
- An IBKR TWS or Gateway instance (only if `IBKR_ENABLED=1`)
- API keys for any sources you enable (Finnhub, Anthropic/DeepSeek for
  enrichment, Telegram/Bark/Feishu for push)

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill in your keys
```

The SQLite database is created automatically at `data/events.db` on
first run.

## Run

```bash
python app.py
```

Server listens on `http://127.0.0.1:8000/` (port configured via
`PORT` in `config.py`).

Key endpoints:

- `GET /` — web UI
- `GET /api/health` — liveness
- `GET /api/diagnostics` — source health, IBKR telemetry, startup state
- `GET /events/stream` — SSE event feed

## Test

```bash
pytest
```

All tests are offline (no network, no IBKR). Run the full suite after
any change:

```bash
pytest -x -q
```

## Configuration

All runtime knobs live in [`config.py`](config.py) and are overridable
via environment variables. The important groups:

| Group | Keys |
|---|---|
| Sources | `FINNHUB_API_KEY`, `FINNHUB_ENABLE_*`, `SEC_USER_AGENT` |
| Enrichment | `ENRICH_PROVIDER`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY` |
| Push | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `BARK_URL`, `FEISHU_WEBHOOK` |
| IBKR | `IBKR_ENABLED`, `IBKR_HOST`, `IBKR_PORT`, `IBKR_CLIENT_ID` |
| SMC | `SMC_MAX_RISK_PCT`, `SMC_MIN_RR`, `SMC_TICK_SIZE` |
| Paper | `PAPER_INITIAL_CASH`, `PAPER_MAX_POSITIONS`, risk/exposure caps |
| Execution | `EXECUTION_MODE` (`paper`/`live`), `LIVE_TRADING_ENABLED` |

See [`.env.example`](.env.example) for the full list of supported
variables with safe defaults.

## Project Layout

```
app.py              FastAPI entrypoint + lifespan
pipeline.py         Event polling pipeline
scheduler.py        APScheduler jobs (polling, digest, backup, EOD)
storage.py          SQLite wrapper (events + paper + SMC tables)
config.py           Central configuration
sources/            External data sources (Finnhub, SEC, IBKR, ...)
smc/                Structure/order-block/liquidity engines
streaming/          IBKR tick/bar ingestion + signal routing
paper/              Ledger, broker, execution-mode guardrails, reviews
web/                FastAPI routes + static UI
tests/              Offline pytest suite
docs/               Architecture overview + phase specs
```

## Notes

- Paper trading is the default execution mode. Live execution is gated
  behind `LIVE_TRADING_ENABLED=1` **and** a minimum track-record gate
  (see `LIVE_READINESS_*` in `config.py`).
- The SQLite DB is backed up nightly (see `BACKUP_*` env vars). Old
  events are pruned after `RETAIN_DAYS` (default 30).
