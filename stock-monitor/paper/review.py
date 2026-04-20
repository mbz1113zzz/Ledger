from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pushers import PushHub
from storage import Storage

ET = ZoneInfo("America/New_York")


@dataclass(slots=True)
class ReviewPayload:
    title: str
    body: str
    date: str
    trade_count: int
    pnl: float


def _utc_bounds_for_et_day(day: datetime) -> tuple[datetime, datetime]:
    start_et = datetime(day.year, day.month, day.day, tzinfo=ET)
    end_et = start_et + timedelta(days=1)
    return start_et.astimezone(timezone.utc), end_et.astimezone(timezone.utc)


def _resolve_day(day_str: str | None, *, storage: Storage, now: datetime | None) -> datetime:
    if day_str:
        return datetime.fromisoformat(day_str).replace(tzinfo=ET)
    latest_ts: datetime | None = None
    for row in storage.list_paper_trades(limit=2000)[:1]:
        latest_ts = datetime.fromisoformat(row["ts"])
        break
    if latest_ts is None:
        eq = storage.last_paper_equity()
        if eq is not None:
            latest_ts = datetime.fromisoformat(eq["ts"])
    if latest_ts is None:
        latest_ts = now or datetime.now(timezone.utc)
    return latest_ts.astimezone(ET)


def build_daily_review(
    storage: Storage,
    *,
    day_str: str | None = None,
    now: datetime | None = None,
) -> ReviewPayload:
    day = _resolve_day(day_str, storage=storage, now=now)
    since, until = _utc_bounds_for_et_day(day)
    trades = [
        row for row in storage.list_paper_trades(limit=5000)
        if since <= datetime.fromisoformat(row["ts"]) < until
    ]
    equities = sorted(
        (
            row for row in storage.list_paper_equity(limit=5000)
            if since <= datetime.fromisoformat(row["ts"]) < until
        ),
        key=lambda row: row["ts"],
    )
    smc_rows = [
        row for row in storage.query_smc_structure(limit=5000)
        if since <= datetime.fromisoformat(row["ts"]) < until
    ]
    events = [
        ev for ev in storage.query_since(since, min_importance="low")
        if ev.published_at < until
    ]

    start_equity = equities[0]["equity"] if equities else 0.0
    end_equity = equities[-1]["equity"] if equities else start_equity
    pnl = end_equity - start_equity
    max_drawdown = 0.0
    if equities:
        peak = equities[0]["equity"]
        for row in equities:
            peak = max(peak, row["equity"])
            max_drawdown = min(max_drawdown, row["equity"] - peak)

    entries_by_signal: dict[int | None, dict] = {}
    closed_rows: list[dict] = []
    for row in sorted(trades, key=lambda item: (item["ts"], item["id"])):
        is_entry = str(row["reason"]).startswith("smc_")
        if is_entry:
            entries_by_signal[row["signal_id"]] = row
            continue
        if not is_entry:
            entry = entries_by_signal.get(row["signal_id"])
            closed_rows.append({"entry": entry, "exit": row})

    signal_stats: dict[str, dict[str, float]] = defaultdict(
        lambda: {"signals": 0, "entries": 0, "wins": 0, "rr_sum": 0.0, "rr_n": 0, "pnl_sum": 0.0}
    )
    for row in trades:
        if row["reason"].startswith("smc_"):
            signal_stats[row["reason"]]["entries"] += 1
    for ev in events:
        if ev.event_type == "smc_entry":
            reason = str(ev.raw.get("reason") or "unknown")
            signal_stats[reason]["signals"] += 1
    for closed in closed_rows:
        entry = closed["entry"]
        exit_row = closed["exit"]
        if not entry:
            continue
        setup = entry["reason"]
        if setup.startswith("smc_"):
            if (exit_row["pnl"] or 0) > 0:
                signal_stats[setup]["wins"] += 1
            signal_stats[setup]["pnl_sum"] += float(exit_row["pnl"] or 0.0)
            if exit_row["rr"] is not None:
                signal_stats[setup]["rr_sum"] += float(exit_row["rr"])
                signal_stats[setup]["rr_n"] += 1

    structure_counts = Counter((row["ticker"], row["kind"]) for row in smc_rows)
    anomaly_counts = Counter(ev.importance for ev in events if ev.event_type == "price_alert")

    lines = [
        f"# Daily Review — {day.strftime('%Y-%m-%d (%a)')}",
        "",
        "## 账户",
        f"- 期初 / 期末权益：${start_equity:,.2f} → ${end_equity:,.2f}",
        f"- 当日 PnL：{pnl:+,.2f}",
        f"- 最大回撤：{max_drawdown:+,.2f}",
        "",
        f"## 交易（{len(closed_rows)} 笔）",
    ]
    if not closed_rows:
        lines.append("- 当日无已平仓交易。")
    else:
        lines.extend([
            "| 时间 | 票 | qty | 入场 | 出场 | Setup | 出场原因 | RR | PnL |",
            "|---|---|---:|---:|---:|---|---|---:|---:|",
        ])
        for item in closed_rows:
            entry = item["entry"] or {}
            exit_row = item["exit"]
            ts = datetime.fromisoformat(exit_row["ts"]).astimezone(ET).strftime("%H:%M")
            rr = "" if exit_row["rr"] is None else f"{float(exit_row['rr']):.2f}"
            pnl_str = "" if exit_row["pnl"] is None else f"{float(exit_row['pnl']):+.2f}"
            lines.append(
                f"| {ts} | {exit_row['ticker']} | {exit_row['qty']} | "
                f"{float(entry.get('price', 0.0)):.2f} | {float(exit_row['price']):.2f} | "
                f"{entry.get('reason', '-')} | {exit_row['reason']} | {rr} | {pnl_str} |"
            )

    lines.extend(["", "## SMC 信号质量"])
    if not signal_stats:
        lines.append("- 当日无 SMC 信号。")
    else:
        lines.extend([
            "| 触发类型 | 信号数 | 入场数 | 胜率 | 平均 RR |",
            "|---|---:|---:|---:|---:|",
        ])
        for reason, stats in sorted(signal_stats.items()):
            win_rate = (stats["wins"] / stats["entries"] * 100) if stats["entries"] else 0.0
            avg_rr = (stats["rr_sum"] / stats["rr_n"]) if stats["rr_n"] else 0.0
            lines.append(
                f"| {reason} | {int(stats['signals'])} | {int(stats['entries'])} | "
                f"{win_rate:.0f}% | {avg_rr:+.2f} |"
            )

    lines.extend(["", "## 结构事件"])
    if not structure_counts:
        lines.append("- 当日无结构事件。")
    else:
        by_ticker: dict[str, list[str]] = defaultdict(list)
        for (ticker, kind), count in sorted(structure_counts.items()):
            by_ticker[ticker].append(f"{count} × {kind}")
        for ticker, parts in by_ticker.items():
            lines.append(f"- {ticker}: {', '.join(parts)}")

    lines.extend([
        "",
        "## 异动报警（独立）",
        f"- high: {anomaly_counts.get('high', 0)} 次，medium: {anomaly_counts.get('medium', 0)} 次，low: {anomaly_counts.get('low', 0)} 次",
        "",
        "## 观察",
    ])
    if closed_rows:
        timeouts = sum(1 for row in closed_rows if row["exit"]["reason"] == "timeout")
        best_setup = None
        best_win_rate = -1.0
        for reason, stats in signal_stats.items():
            if stats["entries"] == 0:
                continue
            rate = stats["wins"] / stats["entries"]
            if rate > best_win_rate:
                best_setup = reason
                best_win_rate = rate
        if best_setup is not None:
            lines.append(
                f"- {best_setup} 当前胜率最高，为 {best_win_rate * 100:.0f}%（样本 {int(signal_stats[best_setup]['entries'])}）。"
            )
        lines.append(f"- timeout 出场 {timeouts} 次。")
    else:
        lines.append("- 当前还没有形成可复盘的已平仓样本。")

    title = f"Paper Review {day.strftime('%Y-%m-%d')} · {len(closed_rows)} 笔 · {pnl:+.2f}"
    return ReviewPayload(
        title=title,
        body="\n".join(lines).strip(),
        date=day.strftime("%Y-%m-%d"),
        trade_count=len(closed_rows),
        pnl=round(pnl, 4),
    )


def build_win_rate_stats(storage: Storage) -> list[dict]:
    trades = sorted(storage.list_paper_trades(limit=10_000), key=lambda item: (item["ts"], item["id"]))
    entries_by_signal: dict[int | None, dict] = {}
    rows: dict[tuple[str, str], dict] = {}
    for row in trades:
        if str(row["reason"]).startswith("smc_"):
            entries_by_signal[row["signal_id"]] = row
            key = (row["ticker"], row["reason"])
            bucket = rows.setdefault(key, {
                "ticker": row["ticker"],
                "setup": row["reason"],
                "entries": 0,
                "closed": 0,
                "wins": 0,
                "rr_sum": 0.0,
                "rr_n": 0,
                "pnl_sum": 0.0,
            })
            bucket["entries"] += 1
            continue
        entry = entries_by_signal.get(row["signal_id"])
        if entry is None:
            continue
        key = (entry["ticker"], entry["reason"])
        bucket = rows.setdefault(key, {
            "ticker": entry["ticker"],
            "setup": entry["reason"],
            "entries": 0,
            "closed": 0,
            "wins": 0,
            "rr_sum": 0.0,
            "rr_n": 0,
            "pnl_sum": 0.0,
        })
        bucket["closed"] += 1
        pnl = float(row["pnl"] or 0.0)
        bucket["pnl_sum"] += pnl
        if pnl > 0:
            bucket["wins"] += 1
        if row["rr"] is not None:
            bucket["rr_sum"] += float(row["rr"])
            bucket["rr_n"] += 1
    out = []
    for bucket in rows.values():
        closed = bucket["closed"]
        bucket["win_rate_pct"] = round((bucket["wins"] / closed * 100.0) if closed else 0.0, 2)
        bucket["avg_rr"] = round((bucket["rr_sum"] / bucket["rr_n"]) if bucket["rr_n"] else 0.0, 4)
        bucket["avg_pnl"] = round((bucket["pnl_sum"] / closed) if closed else 0.0, 4)
        bucket.pop("rr_sum", None)
        bucket.pop("rr_n", None)
        bucket.pop("pnl_sum", None)
        out.append(bucket)
    out.sort(key=lambda item: (-item["win_rate_pct"], -item["closed"], item["ticker"], item["setup"]))
    return out


async def send_daily_review(storage: Storage, push_hub: PushHub, *, now: datetime | None = None) -> ReviewPayload:
    payload = build_daily_review(storage, now=now)
    if push_hub.enabled:
        await push_hub.broadcast_text(payload.title, payload.body)
    return payload
