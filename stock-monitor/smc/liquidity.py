from __future__ import annotations

from smc.types import Candle, LiquidityPool, StructureEvent, Swing


class LiquidityPoolIndex:
    def __init__(self, ticker: str):
        self._ticker = ticker
        self._pools: list[LiquidityPool] = []

    def on_swing(self, swing: Swing) -> None:
        side = "high" if swing.kind == "swing_high" else "low"
        self._pools.append(LiquidityPool(
            ts=swing.ts, ticker=self._ticker, side=side, price=swing.price,
        ))

    def on_candle(self, candle: Candle) -> list[StructureEvent]:
        out: list[StructureEvent] = []
        for pool in self._pools:
            if pool.status != "pending":
                continue
            if pool.side == "high":
                if candle.h > pool.price and candle.c < pool.price:
                    pool.sweep(candle.ts)
                    out.append(StructureEvent(
                        ts=candle.ts, ticker=self._ticker,
                        kind="liq_sweep_high", price=pool.price, ref=pool,
                    ))
            else:
                if candle.l < pool.price and candle.c > pool.price:
                    pool.sweep(candle.ts)
                    out.append(StructureEvent(
                        ts=candle.ts, ticker=self._ticker,
                        kind="liq_sweep_low", price=pool.price, ref=pool,
                    ))
        return out

    def pending(self) -> list[LiquidityPool]:
        return [p for p in self._pools if p.status == "pending"]

    @property
    def all_pools(self) -> list[LiquidityPool]:
        return list(self._pools)
