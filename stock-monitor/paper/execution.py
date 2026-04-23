from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from storage import Storage

ExecutionMode = Literal["paper", "dry_live", "live"]


@dataclass(slots=True)
class ExecutionReadiness:
    closed_trades: int
    win_rate_pct: float
    avg_rr: float
    min_closed_trades: int
    min_win_rate_pct: float
    min_avg_rr: float

    def blockers(self) -> list[str]:
        blockers: list[str] = []
        if self.closed_trades < self.min_closed_trades:
            blockers.append(
                f"closed_trades {self.closed_trades} < required {self.min_closed_trades}"
            )
        if self.win_rate_pct < self.min_win_rate_pct:
            blockers.append(
                f"win_rate_pct {self.win_rate_pct:.2f} < required {self.min_win_rate_pct:.2f}"
            )
        if self.avg_rr < self.min_avg_rr:
            blockers.append(
                f"avg_rr {self.avg_rr:.2f} < required {self.min_avg_rr:.2f}"
            )
        return blockers


class ExecutionModeController:
    def __init__(
        self,
        *,
        storage: Storage,
        initial_mode: ExecutionMode = "paper",
        live_trading_enabled: bool = False,
        live_execution_available: bool = False,
        min_closed_trades: int = 20,
        min_win_rate_pct: float = 50.0,
        min_avg_rr: float = 1.0,
    ):
        self._storage = storage
        self._mode: ExecutionMode = initial_mode
        self._live_trading_enabled = bool(live_trading_enabled)
        self._live_execution_available = bool(live_execution_available)
        self._min_closed_trades = max(1, int(min_closed_trades))
        self._min_win_rate_pct = float(min_win_rate_pct)
        self._min_avg_rr = float(min_avg_rr)

    @property
    def mode(self) -> ExecutionMode:
        return self._mode

    def readiness(self) -> ExecutionReadiness:
        trades = sorted(
            self._storage.list_paper_trades(limit=20_000),
            key=lambda item: (item["ts"], item["id"]),
        )
        closed = 0
        wins = 0
        rr_sum = 0.0
        rr_n = 0
        for row in trades:
            reason = str(row["reason"])
            if reason.startswith("smc_"):
                continue
            closed += 1
            pnl = float(row["pnl"] or 0.0)
            if pnl > 0:
                wins += 1
            if row["rr"] is not None:
                rr_sum += float(row["rr"])
                rr_n += 1
        win_rate_pct = (wins / closed * 100.0) if closed else 0.0
        avg_rr = (rr_sum / rr_n) if rr_n else 0.0
        return ExecutionReadiness(
            closed_trades=closed,
            win_rate_pct=round(win_rate_pct, 2),
            avg_rr=round(avg_rr, 4),
            min_closed_trades=self._min_closed_trades,
            min_win_rate_pct=self._min_win_rate_pct,
            min_avg_rr=self._min_avg_rr,
        )

    def snapshot(self) -> dict:
        readiness = self.readiness()
        blockers = readiness.blockers()
        if not self._live_trading_enabled:
            blockers = ["live trading disabled in config", *blockers]
        if not self._live_execution_available:
            blockers = ["live execution path not implemented", *blockers]
        return {
            "mode": self._mode,
            "available_modes": ["paper", "dry_live", "live"],
            "live_trading_enabled": self._live_trading_enabled,
            "live_execution_available": self._live_execution_available,
            "readiness": {
                "closed_trades": readiness.closed_trades,
                "win_rate_pct": readiness.win_rate_pct,
                "avg_rr": readiness.avg_rr,
                "min_closed_trades": readiness.min_closed_trades,
                "min_win_rate_pct": readiness.min_win_rate_pct,
                "min_avg_rr": readiness.min_avg_rr,
                "blockers": blockers,
                "live_ready": not blockers,
            },
        }

    def set_mode(self, mode: ExecutionMode) -> tuple[bool, dict]:
        if mode not in {"paper", "dry_live", "live"}:
            return False, {
                **self.snapshot(),
                "error": f"unsupported mode: {mode}",
            }
        if mode == "live":
            snap = self.snapshot()
            blockers = snap["readiness"]["blockers"]
            if blockers:
                return False, {
                    **snap,
                    "error": "live mode is locked",
                }
        self._mode = mode
        snap = self.snapshot()
        snap["changed"] = True
        return True, snap
