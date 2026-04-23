# IBKR 实时行情 + SMC 短线模拟交易设计

**日期**：2026-04-19
**范围**：接入 IBKR paper 的实时行情，跑 **SMC（Smart Money Concepts）** 短线策略的模拟交易。同时保留 % 异动做实时报警，两套并行。每日收盘后生成复盘报告。

---

## 1. 目标

- 把行情延迟从 120s（Finnhub 轮询）降到 <2s（IBKR tick）。
- 基于 5m 市场结构 + 1m 入场时机，跑 SMC 规则的模拟多头交易。
- % 异动（0.5 / 1 / 3%）保留作为独立报警通道，不再驱动交易。
- 每交易日 16:15 ET 自动出复盘报告，人工 review 后决定是否改参数。

## 2. 关键决策（已确认）

| 项 | 选择 |
|----|------|
| 账户 | IBKR paper `127.0.0.1:7497`，`ib_insync` |
| 结构时间级别 | **5m 结构 + 1m 入场** |
| 入场触发 | **A: Liquidity Sweep + CHoCH + OB 回踩** / **B: Liquidity Sweep + BOS + OB 回踩** |
| 止损 | **结构性**：放在入场 OB 的另一端（bullish OB 下沿下方 1 tick） |
| 止盈 | 默认 1:2 RR（风险报酬比）；若至前方下一个 5m swing high 更远则按 swing high |
| 方向 | 仅做多（v1） |
| 最长持仓 | 60 分钟（避免 setup 失效后死扛） |
| 收盘强平 | 15:50 ET 全平，不留夜仓 |
| 单票上限 | 账户权益 20%（初始 $2,000） |
| 初始资金 | $10,000 |
| % 异动 | 保留独立报警通道，**不**驱动交易 |
| 复盘 | 每日 md 报告，不自动调参 |

## 3. 架构

```
┌───────────────────────────────────────────────────────────────┐
│                    FastAPI App (lifespan)                     │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐   │
│  │             StreamingRunner (新, asyncio)              │   │
│  │                                                        │   │
│  │  IbkrClient (ib_insync)                                │   │
│  │    ├─► tick stream                                     │   │
│  │    └─► 5-sec realTimeBars                              │   │
│  │         │                                              │   │
│  │  ┌──────▼──────┐   ┌──────────────────────┐            │   │
│  │  │ BarAggregator│──►│ Candles: 1m / 5m     │            │   │
│  │  └──────┬──────┘   └──────┬───────────────┘            │   │
│  │         │                 │                            │   │
│  │  ┌──────▼──────────┐  ┌───▼─────────────────────────┐  │   │
│  │  │ TickBuffer      │  │ SmcEngine                   │  │   │
│  │  │ + AnomalyDetect │  │ ├ StructureTracker (swings, │  │   │
│  │  │                 │  │ │    BOS / CHoCH)           │  │   │
│  │  │ (% 异动报警)    │  │ ├ OrderBlockIndex           │  │   │
│  │  │                 │  │ ├ LiquidityPoolIndex        │  │   │
│  │  │                 │  │ └ SmcSignal (入场决策)      │  │   │
│  │  └──────┬──────────┘  └───┬─────────────────────────┘  │   │
│  │         │                 │                            │   │
│  │         ▼                 ▼                            │   │
│  │  ┌───────────────────────────────────────────────┐     │   │
│  │  │ SignalRouter                                  │     │   │
│  │  │  - 异动 → events 表 + SSE + push_hub          │     │   │
│  │  │  - SMC  → events + broker.on_smc_signal       │     │   │
│  │  └───────────────────────┬───────────────────────┘     │   │
│  │                          │                             │   │
│  │                   ┌──────▼──────────┐                  │   │
│  │                   │ PaperBroker     │                  │   │
│  │                   │  ├ Ledger       │                  │   │
│  │                   │  └ on_tick 出场 │                  │   │
│  │                   └─────────────────┘                  │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                               │
│  DailyReviewJob (CronTrigger 16:15 ET) → md 报告              │
│  FallbackPricePipeline (Finnhub /quote 2min) 保留兜底          │
└───────────────────────────────────────────────────────────────┘
```

## 4. 模块与文件

### 4.1 新增

| 文件 | 职责 |
|------|------|
| `sources/ibkr_realtime.py` | `IbkrClient`：连 Gateway、订阅 tick + realTimeBars、自动重连、reqId→ticker 映射 |
| `streaming/bar_aggregator.py` | 5s bar → 1m / 5m candle，close-only OHLC，维护最近 N 根 |
| `streaming/tick_buffer.py` | 每 ticker 环形缓冲，提供 1min 前价、今日开盘价 |
| `streaming/anomaly.py` | `AnomalyDetector`：% 异动（0.5/1/3%）分档报警，独立于 SMC |
| `smc/structure.py` | `StructureTracker`：swing high/low 识别（fractal 3 或 swing strength），发 BOS / CHoCH 事件 |
| `smc/order_block.py` | `OrderBlockIndex`：impulsive move 识别 + 最后 opposing candle 标记为 OB，带有效期和消耗状态 |
| `smc/liquidity.py` | `LiquidityPoolIndex`：跟踪近期 swing high/low 作为流动性点，被击穿即标记 "swept" |
| `smc/engine.py` | `SmcEngine.on_candle(tf, candle)`：组合上述，按 A/B 条件发 `SmcSignal(ticker, ob, sl, tp, ts, reason)` |
| `smc/types.py` | dataclass：`Swing`, `OrderBlock`, `LiquidityPool`, `SmcSignal`, `StructureEvent` |
| `streaming/signal_router.py` | 异动 + SMC 信号去重、落库、推送、分流 |
| `streaming/runner.py` | `StreamingRunner` 装配，lifespan 钩子 |
| `paper/ledger.py` | `Ledger`：positions / cash / equity，持久化 SQLite |
| `paper/broker.py` | `PaperBroker`：on_smc_signal 开仓、on_tick 出场（SL/TP/timeout/eod）|
| `paper/strategy.py` | `SmcLongStrategy`：仓位大小、入场/出场规则，纯函数 |
| `paper/pricing.py` | 出场取价（TickBuffer 最新 → fallback /quote）|
| `paper/review.py` | `build_daily_review(date) -> str`：md 报告生成 |
| `config.py` (追加) | IBKR / ANOMALY / SMC / PAPER / REVIEW 参数 |
| `web/routes.py` (追加) | `/api/paper/{positions,trades,equity,review}`, `/api/smc/structure?ticker=` |
| `web/static/app.js` (追加) | Paper 面板：权益、持仓、今日成交、当日 BOS/CHoCH/OB 可视化 |
| 测试文件 | 每个新模块对应 |

### 4.2 SQLite（新增表）

```sql
CREATE TABLE paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TIMESTAMP NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,             -- 'buy' | 'sell'
    qty INTEGER NOT NULL,
    price REAL NOT NULL,
    reason TEXT NOT NULL,           -- 'smc_choch_ob' | 'smc_bos_ob' | 'tp' | 'sl' | 'timeout' | 'eod'
    pnl REAL,                       -- 仅平仓行
    signal_id INTEGER,              -- 关联 events.id
    rr REAL                         -- 仅平仓行：实际 RR
);

CREATE TABLE paper_equity (
    ts TIMESTAMP PRIMARY KEY,
    cash REAL NOT NULL,
    positions_value REAL NOT NULL,
    equity REAL NOT NULL
);

CREATE TABLE smc_structure (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TIMESTAMP NOT NULL,
    ticker TEXT NOT NULL,
    tf TEXT NOT NULL,               -- '5m'
    kind TEXT NOT NULL,             -- 'swing_high' | 'swing_low' | 'bos_up' | 'bos_down' | 'choch_up' | 'choch_down' | 'ob_bull' | 'ob_bear' | 'liq_sweep_high' | 'liq_sweep_low'
    price REAL NOT NULL,
    ref_id INTEGER,                 -- 自引用：OB 回溯 swing，sweep 回溯 liquidity
    meta_json TEXT
);

CREATE INDEX idx_smc_ticker_ts ON smc_structure(ticker, ts DESC);
```

## 5. SMC 策略细节

### 5.1 术语（快速对齐）

- **Swing High / Low**：局部极值，我们用 5-candle fractal（中间 K 比两侧 2 根都高/低）
- **BOS (Break of Structure)**：上行趋势中突破前一个 swing high → bos_up；反之 bos_down
- **CHoCH (Change of Character)**：下行趋势中突破前一个 swing high → choch_up（趋势反转信号）；反之亦然
- **Order Block (OB)**：impulsive move（单向 N 根连续同向 K 或单根大 K）前最后一根反向 K 线的 high-low 区间。Bullish OB = 牛冲前的最后一根阴线
- **Liquidity Pool**：明显的近期 swing high / low，周围通常堆积止损单；价格穿过即 "swept"
- **Liquidity Sweep**：K 线 wick 穿过 pool 但收盘回到 pool 内侧 → 定义为扫过流动性
- **OB Retest**：价格回到 OB 区间内（任意 wick 触及即可）

### 5.2 StructureTracker

**输入**：5m 收盘 K 线
**维护**：
- `swings: list[Swing]`（带 `kind`, `price`, `bar_idx`, `ts`）
- `trend: "up" | "down" | "none"`
- `last_bos_high`, `last_bos_low`

**逻辑**：
1. 每根新 K 入库后，判断上一根（bar_idx - 2 的中心）是否是 fractal swing：
   - `high[i-2] > max(high[i-4..i-3], high[i-1..i])` → swing_high
   - 同理 swing_low
2. 若新 K close > 最近未破的 swing_high：
   - trend == "up" → 发 `bos_up`
   - trend == "down" → 发 `choch_up` 并切 trend = "up"
3. swing_low 的方向对称
4. 事件写 `smc_structure` 表

### 5.3 OrderBlockIndex

**输入**：5m K 线 + StructureTracker 的 BOS/CHoCH 事件

**触发**：BOS/CHoCH 发生时，从触发 K 往回找：
- `choch_up` / `bos_up`：最近一根 **bearish candle**（close < open），且其之后是 impulsive up move（至少 2 根 bullish 或单根 bullish 覆盖 ≥ 1.5×ATR(14)）→ 该 bearish candle 的 [low, high] = bullish OB
- 对称处理 bearish OB（v1 仅多头用不上，记录备用）

**状态机**：
- `fresh`：已识别，价格还没回来
- `mitigated`：价格回进 OB 区间
- `invalidated`：价格穿透 OB 下沿（bullish OB），或持续超过 2 小时未回踩

**入场只用 fresh 或首次 mitigated 的 OB。**

### 5.4 LiquidityPoolIndex

- 每个新 swing_high 入 pool，status=`pending`
- 若后续 K wick 超过 pool.price 但 close < pool.price → status=`swept`，发 `liq_sweep_high` 事件
- pool 保留 1 交易日

### 5.5 入场条件（SmcEngine.on_candle）

**A: Liquidity Sweep + CHoCH + OB Retest（反转做多）**

1. 5m 出现 `liq_sweep_low`（扫低）
2. 随后出现 `choch_up`（结构反转向上）
3. 记录触发这次 CHoCH 的 bullish OB
4. 切到 1m：价格第一次回踩到该 OB 区间 → 发 `SmcSignal(reason="smc_choch_ob")`

**B: Liquidity Sweep + BOS + OB Retest（顺势做多）**

1. 当前已是上行趋势（`trend == "up"` 且最近有 bos_up）
2. 5m 回调中出现 `liq_sweep_low`（回调扫了前低）
3. 随后出现 `bos_up`（继续突破）
4. 记录该 BOS 对应的 bullish OB
5. 1m 回踩 OB → 发 `SmcSignal(reason="smc_bos_ob")`

**两者共用的入场参数**：
- `entry = 当前 1m tick 价`
- `sl = OB.low - 1 tick`（结构止损）
- `risk = entry - sl`
- `tp = max(entry + 2 * risk, 下一个 5m 未被扫的 swing_high - 1 tick)`（至少 1:2 RR，往上有明显流动性则取流动性）
- 若 `risk / entry > 1.5%` → 放弃该信号（避免大止损）

### 5.6 仓位计算

```
equity = ledger.equity_now()
max_position_value = equity * 0.20
max_risk_per_trade = equity * 0.01          # 每笔最多亏 1%
risk_per_share = entry - sl
qty_by_risk = floor(max_risk_per_trade / risk_per_share)
qty_by_cap  = floor(max_position_value / entry)
qty = max(1, min(qty_by_risk, qty_by_cap, ledger.cash // entry))
```

risk-first sizing 是 SMC 标配。

### 5.7 出场（PaperBroker.on_tick）

每个活跃仓位逐笔检查：

1. `price <= sl` → 平仓 `sl`
2. `price >= tp` → 平仓 `tp`
3. `now - entry_ts >= 60min` → 平仓 `timeout`
4. 15:50 ET cron → 全仓 `eod`

无移动止损 v1；v2 考虑 BE move（价格到 1R 时 SL 拉到入场价）。

## 6. 两套信号并行

| 通道 | 来源 | 去向 |
|------|------|------|
| 异动报警 | TickBuffer → AnomalyDetector | events 表（importance 按 tier）+ SSE + push_hub。**不触发交易** |
| SMC 交易 | candles → SmcEngine | events 表（event_type="smc_entry"）+ SSE + **broker 开仓** |

去重：
- 异动：`external_id = f"ibkr:anom:{ticker}:{tier}:{minute_bucket}"`
- SMC：`external_id = f"ibkr:smc:{ticker}:{reason}:{minute_bucket}"`

## 7. 每日复盘

**触发**：CronTrigger 16:15 ET（夏/冬令时用 `zoneinfo` 算 UTC）

**报告内容**：

```markdown
# Daily Review — 2026-04-19 (Fri)

## 账户
- 期初 / 期末权益：$10,247.50 → $10,318.20
- 当日 PnL：+$70.70 (+0.69%)
- 最大回撤：-$42.10

## 交易（3 笔）
| 时间 | 票 | 方向 | qty | 入场 | 出场 | 原因 | RR | PnL |
|---|---|---|---|---|---|---|---|---|
| 10:34 | NVDA | LONG | 22 | 91.23 | 93.08 | tp | 2.0 | +$40.70 |
| 11:12 | TSLA | LONG | 14 | 168.40 | 167.85 | sl | -1.0 | -$7.70 |
| ... |

## SMC 信号质量
| 触发类型 | 数量 | 入场 | 胜率 | 平均 RR |
|---|---|---|---|---|
| smc_choch_ob | 4 | 3 | 67% | +1.1 |
| smc_bos_ob | 6 | 4 | 50% | +0.4 |

## 结构事件
- NVDA: 2 × CHoCH↑, 1 × BOS↑, 3 × liq_sweep_low
- TSLA: 1 × CHoCH↓, 4 × BOS↓（下行结构，多头机会少符合预期）

## 异动报警（独立）
- low: 14 次，medium: 8 次，high: 3 次

## 观察与建议
- NVDA CHoCH+OB 胜率 100%（3/3），可保持
- TSLA BOS+OB 胜率 25%，趋势下行期不应做多 → 考虑加 "只在 trend==up 做 B" 的约束
- 平均持仓 18 min，timeout 触发 0 次 → 60min 上限可能过宽
- 2 笔 SL 距离 >1% 的信号被规则过滤掉 → 继续过滤

*本报告不自动改参数。*
```

## 8. 配置

```python
# IBKR
IBKR_ENABLED = os.getenv("IBKR_ENABLED", "1") == "1"
IBKR_HOST = os.getenv("IBKR_HOST", "127.0.0.1")
IBKR_PORT = int(os.getenv("IBKR_PORT", "7497"))
IBKR_CLIENT_ID = int(os.getenv("IBKR_CLIENT_ID", "42"))

# 异动（独立报警）
ANOMALY_TIERS = [("low", 0.005), ("medium", 0.01), ("high", 0.03)]
ANOMALY_COOLDOWN_SEC = 300

# SMC
SMC_STRUCTURE_TF = "5m"
SMC_ENTRY_TF = "1m"
SMC_FRACTAL_WINDOW = 5
SMC_OB_MAX_AGE_MIN = 120
SMC_MAX_RISK_PCT = 0.015          # 单笔风险占入场价 >1.5% 弃用信号
SMC_MIN_RR = 2.0

# Paper broker
PAPER_ENABLED = os.getenv("PAPER_ENABLED", "1") == "1"
PAPER_INITIAL_CASH = 10_000.0
PAPER_MAX_POSITION_PCT = 0.20
PAPER_MAX_RISK_PER_TRADE_PCT = 0.01
PAPER_MAX_HOLD_MIN = 60
PAPER_EOD_HOUR_ET = 15
PAPER_EOD_MINUTE_ET = 50

# Review
REVIEW_HOUR_ET = 16
REVIEW_MINUTE_ET = 15
```

## 9. 错误与降级

| 场景 | 处理 |
|------|------|
| Gateway 未启动 | 指数退避重连 1→60s；期间 StreamingRunner 标记 disabled，Finnhub 兜底轮询继续 |
| 订阅报错 market-data | 该 ticker 标记 disabled，/api/health 可见 |
| 开盘价缺失 | `reqHistoricalData` 取当日 30min bar |
| SMC 历史结构缺失（重启后无 swing） | 启动后用 `reqHistoricalData` 拉当日 5m bar 回放 StructureTracker 建立结构 |
| Ledger 状态不一致（资金 / 持仓负） | 拒绝交易 + error 日志，不强改 |
| EOD 无 tick | 用最近 TickBuffer 价；超过 5min 无 tick 则用 Finnhub /quote |
| Review 生成失败 | error 记录，不重试 |

## 10. 测试

- `BarAggregator`：tick → 1m/5m 正确闭合
- `StructureTracker`：各种 swing / BOS / CHoCH 序列、趋势切换
- `OrderBlockIndex`：bullish OB 识别、mitigation、invalidation、max_age
- `LiquidityPoolIndex`：swept 判定、wick vs close
- `SmcEngine`：A / B 两种入场序列端到端，假数据驱动；RR 过滤；多 ticker 隔离
- `Ledger`：开平仓、权益、边界
- `SmcLongStrategy`：仓位计算（risk-first）
- `PaperBroker`：SMC 信号 → 开仓；on_tick → 四种出场
- `AnomalyDetector`：档位、冷却、双基准同向
- `review.build_daily_review`：无交易日、多笔、无信号
- `IbkrClient`：mock `ib_insync.IB`，不连真 Gateway

**不做**：实连 Gateway 的集成测试（手动冒烟）；不做统计显著性测试（样本量不足期）。

## 11. 分期交付

**Phase 1（数据 + 结构识别）**
- IbkrClient + BarAggregator + TickBuffer + StructureTracker + OrderBlockIndex + LiquidityPoolIndex
- AnomalyDetector 保留现有行为接到新 runner
- 验收：前端能看到 5m 结构事件（BOS/CHoCH/OB/sweep），异动报警正常

**Phase 2（SMC 入场 + 模拟交易）**
- SmcEngine（A + B）+ Ledger + PaperBroker + SmcLongStrategy
- 验收：paper_trades 有 entry + tp/sl/timeout/eod 出场记录

**Phase 3（UI + 复盘）**
- Paper 面板（权益、持仓、今日成交）、Structure 可视化
- Daily review cron + md 报告推送

**Phase 4（优化）**
- Break-even 移动止损
- Short 支持
- 基于历史样本的胜率面板（按 ticker × setup 类型）

## 12. 权衡与已知限制

- **无滑点模型 v1**：按 tick 价成交，乐观估计。Phase 4 加 5bps。
- **Pre/post-market 不处理**：RTH only。
- **Structure 识别是后置的**：swing 需 fractal 后置确认（中心点向后看 2 根），所以结构事件滞后 2 根 5m = 10min。这是 SMC 本质，不可避免。
- **SMC 主观性**：不同教材 OB / sweep 定义有出入，本设计取保守定义（明确的 wick + close + fractal）。
- **单进程**：StreamingRunner 崩溃拖整个 FastAPI。用 /api/health 监控。
- **市场数据订阅费**：用户承担。
- **样本量小**：1 个人 watchlist 几天数据，统计建议仅作参考，不上 ML 优化。

---

## 执行计划

Design 已成型。接下来走 `writing-plans` 生成分步骤实施计划，按 Phase 1 → 4 逐段做 TDD 开发。

要不要我现在进 writing-plans？
