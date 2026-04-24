# CLAUDE.md

Guidance for Claude Code when working in this repo. See
[README.md](README.md) for user-facing docs and
[docs/LLM_PROJECT_OVERVIEW.md](docs/LLM_PROJECT_OVERVIEW.md) for the
full architectural tour.

## Always

- **Run `pytest -x -q` after any code change.** All 197 tests are
  offline (no network, no IBKR) and run in <2 s. There is no excuse for
  skipping this.
- **Prefer `Edit` over `Write`.** Full rewrites drop context.
- **Keep trading logic unchanged** unless the task explicitly says to
  modify it. When in doubt, ask.
- **Preserve existing inline comments explaining non-obvious code** —
  most of them encode tribal knowledge about ib_insync quirks, Finnhub
  payload shapes, or IBKR reconnect edge cases.

## Python Style

- Python 3.11+. Use `X | Y` unions, `list[T]`, `dict[K, V]` — no
  `typing.List` / `Optional`.
- `from __future__ import annotations` is used in newer modules
  (`paper/`, `streaming/`, `smc/`). Match the surrounding file.
- Dataclasses everywhere for value objects. Use `slots=True` when the
  object is created in hot paths.
- No emoji in source or commit messages.

## Time & Timezones

This is a trading system — timezone bugs are real bugs.

- **UTC for storage, ET (`America/New_York`) for business logic.**
  Every `datetime.now()` call must be `datetime.now(timezone.utc)` or
  explicitly localized. Never use naive datetimes.
- Use `zoneinfo.ZoneInfo("America/New_York")` (aliased as `ET` or
  `_ET` in modules that need it) — not `pytz`.
- "Daily" boundaries are ET midnight, not UTC midnight. See
  `paper/ledger.py::day_pnl_pct` for the canonical pattern.

## Sources & Health

Every `Source` subclass should:

- Own a `SourceHealth(self.name)` instance.
- Wrap each fetch in `try` with `record_success` / `record_timeout` /
  `record_http_error` / `record_error`.
- Short-circuit (`return []`) when `self._health.disabled` is true.
- Never raise out of `fetch()` — log and continue.

429 is rate-limiting (temporary), not a permanent auth failure. It
must not accumulate into the disable streak — see
`tests/test_source_health.py::test_http_429_is_classified_as_quota_exhausted`.

## Event Serialization

Both `Pipeline` and `SignalRouter` publish to `Notifier` via the
shared `serialize_event` helper in `sources/base.py`. Do not re-roll
this logic — fields that are safe to broadcast (and those that aren't,
like `raw`) are deliberate.

## Paper Trading

- `paper/broker.py` is the only place allowed to open/close positions.
- Risk gates live in `paper/execution.py` — adding a new gate means
  adding a test that proves it fires.
- `Ledger.day_pnl_pct` anchors the day at ET midnight using the
  **last snapshot before** that boundary. Never change that anchor
  without understanding why.

## Testing

- Tests live in `tests/` and follow `test_<module>.py` naming.
- Async tests run under `asyncio_mode = auto` (see `pytest.ini`) — no
  need for `@pytest.mark.asyncio`.
- Use in-memory SQLite (`Storage(":memory:")`) or tmp paths — never
  hit the real `data/events.db` from a test.
- When adding a behavior, add a test first or alongside. Behaviors
  without tests get silently regressed.

## Do Not

- **Do not commit secrets.** `.env` is gitignored; keep it that way.
- **Do not introduce a new external network call** without:
  (a) wrapping it in the `SourceHealth` pattern,
  (b) giving it a kill-switch env var in `config.py`,
  (c) adding a test that exercises the error path.
- **Do not amend commits.** Always make new commits.
- **Do not push without running tests.**

## Commits

Follow the existing convention — lowercase conventional prefix:

- `feat:` / `feat(area):` — new behavior
- `fix:` — bugfix
- `refactor:` — no behavior change
- `docs:` — docs only
- `chore:` — tooling, deps, gitignore, etc.

Keep the subject under ~70 chars. Use the body for the "why."
