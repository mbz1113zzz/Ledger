# Ledger Next Expansion Plan

Date: 2026-04-21

## Goal

Build the next layer on top of the current IBKR-first monitoring and paper-trading stack:

1. Strengthen visual trading workflows
2. Improve production robustness and operator visibility
3. Prepare the system for controlled live-trading readiness

## Current Baseline

- IBKR-first trading and market-data core is in place
- Finnhub is limited to event/news sources by default
- Paper trading supports long, short, break-even, review, and win-rate stats
- Web UI supports:
  - event feed
  - paper dashboard
  - review and stats modals
  - chart visualization with structure and trade overlays

## Expansion Track A: Trading Visualization

### A1. Richer chart overlays

- Show persistent labels for active order blocks and liquidity pools
- Highlight BOS/CHoCH regimes with segmented background bands
- Add toggle chips for:
  - structure events
  - trades
  - liquidity
  - order blocks

### A2. Multi-panel chart workspace

- Split chart view into:
  - price panel
  - equity panel
  - volume panel
- Add ticker comparison mode for two-symbol side-by-side monitoring

### A3. Replay and diagnostics

- Add a replay cursor for structure/trade progression
- Allow stepping through SMC setups candle-by-candle
- Surface which rule opened each trade and which rule exited it

## Expansion Track B: Production Readiness

### B1. Source and connector resilience

- Add timeout / retry metrics per source
- Distinguish:
  - permission denied
  - quota exhausted
  - transient upstream failure
- Add startup source summary log and UI diagnostics banner

### B2. IBKR robustness

- Add account / contract subscription diagnostics
- Track reconnect counts and last successful heartbeat
- Add warm-start hydration for intraday structure state from historical bars

### B3. Data retention and cleanup

- Cap paper equity/trade snapshot growth
- Add archive / retention policy for chart-heavy history
- Add maintenance endpoint for compaction status

## Expansion Track C: Strategy and Risk

### C1. Parameter controls

- Move strategy parameters into editable config UI:
  - risk %
  - break-even threshold
  - max hold time
  - enabled setups

### C2. Risk dashboards

- Add:
  - max drawdown card
  - per-ticker exposure card
  - setup-level PnL contribution chart

### C3. Live-trading readiness checklist

- Introduce a gated execution mode:
  - paper
  - dry-live
  - live
- Require explicit validation steps before live mode unlock

## Proposed Delivery Order

### Phase N1

- Overlay toggles
- active OB / liquidity visuals
- volume panel

### Phase N2

- source diagnostics banner
- IBKR reconnect / heartbeat telemetry
- startup/source summary block

### Phase N3

- parameter controls
- risk dashboard
- replay cursor

### Phase N4

- live-trading readiness guardrails
- dry-live execution path
- operational checklist and sign-off flow

## Verification Strategy

- Add route tests for new telemetry and chart payloads
- Add UI smoke verification for overlay toggles and multi-panel chart rendering
- Add runtime validation for:
  - startup readiness
  - source degradation visibility
  - replay correctness
  - parameter persistence

## Recommended Next Step

Start with Phase N1.

Reason:

- highest user-visible value
- low operational risk
- builds directly on the new chart foundation
- improves review and debugging without touching live execution behavior
