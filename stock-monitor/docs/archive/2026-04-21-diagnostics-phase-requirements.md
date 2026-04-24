# Ledger Diagnostics Phase Requirements

Date: 2026-04-21

## Objective

Improve operator visibility into the running system without changing trading logic:

1. show source-level health and request metrics
2. expose startup and runtime diagnostics through APIs
3. surface IBKR connectivity telemetry clearly enough to debug reconnects
4. make the Web UI useful for operators, not just traders

## Problems Observed

- `/api/health` currently tells us only coarse status
- source failures are visible in logs but not easy to inspect from the UI
- IBKR reconnect attempts are hard to reason about without tailing logs
- startup sync is backgrounded, but there is little detail about whether it succeeded or how long it took

## Requirements

### R1. Source Metrics

Each source should expose:

- `request_count`
- `success_count`
- `error_count`
- `consecutive_4xx`
- `last_status`
- `reason`
- `last_duration_ms`
- `last_success_at`
- `last_error_at`

### R2. IBKR Telemetry

Expose:

- connection state
- current subscribed tickers
- connect attempt count
- reconnect success count
- last successful connect timestamp
- last connection error

### R3. Startup Diagnostics

Expose:

- startup sync running / done
- startup sync started / finished timestamps
- startup sync duration
- startup sync error if present

### R4. Diagnostics API

Add a dedicated diagnostics endpoint returning:

- source snapshots
- pipeline run metadata
- startup sync status
- IBKR telemetry when runner is present

### R5. UI Diagnostics View

Provide a diagnostics modal or panel that shows:

- startup status
- source metrics table
- IBKR telemetry summary
- last run counts and timing

## Implementation Plan

### Step 1

Extend `SourceHealth` with counters, timestamps, latency, and snapshot export.

### Step 2

Instrument:

- `FinnhubSource`
- `SecEdgarSource`
- `PriceAlertSource`
- `AnalystSource`
- `SentimentSource`

### Step 3

Add telemetry export to `IbkrClient`.

### Step 4

Track startup sync lifecycle in `app.state`.

### Step 5

Add `/api/diagnostics`.

### Step 6

Add a UI diagnostics entry and modal rendering.

## Verification

- source health unit tests
- IBKR client snapshot unit test
- route test for diagnostics payload
- full test suite
- runtime smoke against local server
