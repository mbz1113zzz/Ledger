# 美股事件监控系统 — MVP 设计文档

**日期：** 2026-04-18
**阶段：** Phase 1 MVP
**状态：** 设计已确认，待写实现计划

---

## 1. 目标与范围

### 目标
为美股交易者提供一个本地运行的 Web Dashboard，实时监控关注股票的重大事件（新闻、SEC 备案、财报日历），避免错过关键信息。

### 范围（仅 Phase 1 MVP）
- 定时从 Finnhub、SEC EDGAR、yfinance 三个免费源拉取数据
- 按用户 watchlist 过滤事件
- 按重要性分级（高/中/低）
- 浏览器通知 + Dashboard 事件流展示
- 本地 SQLite 存储历史事件

### 不在范围
- 价格异动告警（Phase 2）
- 技术指标告警（Phase 3）
- 云端部署、多用户
- 移动端 App
- AI 事件摘要

---

## 2. 技术栈

| 层 | 技术 | 理由 |
|----|------|------|
| 后端 | Python 3.10+ / FastAPI | 异步、轻量，适合定时任务 + REST |
| 定时调度 | APScheduler | Python 原生，无需额外服务 |
| 存储 | SQLite | 零配置本地文件 |
| 前端 | 原生 HTML + JS（无框架） | 避免过度工程，单页应用够用 |
| 通知 | Web Notifications API | 浏览器原生，无需邮件服务 |
| HTTP 客户端 | httpx | FastAPI 生态兼容异步 |

**启动方式：** `python app.py` → 浏览器访问 `http://localhost:8000`

---

## 3. 架构与数据流

```
 ┌─────────────────┐
 │  watchlist.json │  用户编辑 → 关注的股票列表
 └────────┬────────┘
          │
    ┌─────▼──────────────────────┐
    │  Scheduler (APScheduler)   │
    │  ├─ 每 5 分钟: Finnhub 新闻 │
    │  ├─ 每 5 分钟: SEC EDGAR   │
    │  └─ 每天 1 次: yfinance 财报│
    └─────┬──────────────────────┘
          │
    ┌─────▼────────────┐       ┌──────────────┐
    │  去重 + 打分     │──────▶│  SQLite      │
    └─────┬────────────┘       └──────┬───────┘
          │                           │
    ┌─────▼───────────┐       ┌───────▼────────┐
    │  推送浏览器通知 │       │  FastAPI 路由  │
    │  (SSE 长连接)   │       │  Dashboard UI  │
    └─────────────────┘       └────────────────┘
```

### 数据流说明

1. 调度器按频率调用各数据源模块
2. 每个源返回统一的 `Event` 对象列表
3. 去重器根据 `(source, external_id)` 检查 SQLite 是否已存在
4. 新事件经打分器标记重要性
5. 写入 SQLite，同时通过 SSE (Server-Sent Events) 推送到已打开的 Dashboard
6. Dashboard 收到新事件：触发浏览器通知 + 事件流顶部插入卡片

---

## 4. 模块设计

### 4.1 目录结构

```
stock-monitor/
├── app.py                    # FastAPI 入口，启动时拉起 scheduler
├── config.py                 # 配置（API keys, 轮询频率）
├── watchlist.json            # 用户关注股票列表
├── watchlist_manager.py      # 读取/校验 watchlist
├── sources/
│   ├── __init__.py
│   ├── base.py               # 统一的 Event 数据结构 + Source 基类
│   ├── finnhub.py
│   ├── sec_edgar.py
│   └── yfinance_source.py
├── event_scorer.py           # 重要性打分
├── deduplicator.py           # 去重逻辑
├── storage.py                # SQLite 读写
├── scheduler.py              # APScheduler 封装
├── notifier.py               # SSE 推送
├── web/
│   ├── static/
│   │   ├── index.html
│   │   ├── app.js
│   │   └── style.css
│   └── routes.py             # FastAPI 路由
├── tests/
│   ├── test_sources.py
│   ├── test_scorer.py
│   ├── test_storage.py
│   └── test_deduplicator.py
├── requirements.txt
└── data/
    └── events.db             # SQLite 数据文件（gitignore）
```

### 4.2 核心数据结构

**`Event` (sources/base.py)**

```python
@dataclass
class Event:
    source: str              # "finnhub" | "sec_edgar" | "yfinance"
    external_id: str         # 源系统 ID，用于去重
    ticker: str              # 股票代码
    event_type: str          # "news" | "filing_8k" | "earnings"
    title: str
    summary: str | None
    url: str | None
    published_at: datetime   # UTC
    importance: str = "low"  # "high" | "medium" | "low"（由 scorer 填充）
    raw: dict                # 原始数据，调试用
```

**`Source` 基类**

```python
class Source(ABC):
    @abstractmethod
    async def fetch(self, tickers: list[str]) -> list[Event]: ...
```

### 4.3 数据源实现

**Finnhub (`sources/finnhub.py`)**
- 端点：`/company-news?symbol={ticker}&from=...&to=...`
- 频率：每 5 分钟
- 返回字段映射：`id → external_id`, `headline → title`, `summary`, `url`, `datetime → published_at`
- `event_type = "news"`

**SEC EDGAR (`sources/sec_edgar.py`)**
- 端点：`https://data.sec.gov/submissions/CIK{cik}.json`
- 需先维护 ticker → CIK 的映射（SEC 提供 `company_tickers.json`，启动时加载进内存）
- 只抓 Form Type = `8-K` 的条目
- 频率：每 5 分钟
- `event_type = "filing_8k"`，`external_id = accession_number`

**yfinance (`sources/yfinance_source.py`)**
- 调用 `Ticker(symbol).calendar` 获取下次财报日
- 频率：每天 1 次（凌晨 00:05）
- `event_type = "earnings"`，`external_id = f"{ticker}-earnings-{date}"`

### 4.4 打分规则 (`event_scorer.py`)

```python
HIGH_KEYWORDS = [
    "acquisition", "merger", "fda approval", "guidance",
    "ceo", "resign", "bankruptcy", "dividend", "buyback",
    "downgrade", "upgrade", "investigation"
]

def score(event: Event) -> str:
    if event.event_type == "filing_8k":
        return "high"
    if event.event_type == "earnings":
        return "high"
    if event.event_type == "news":
        text = (event.title + " " + (event.summary or "")).lower()
        if any(kw in text for kw in HIGH_KEYWORDS):
            return "high"
        return "medium"
    return "low"
```

打分规则集中在一处，后续容易调整。

### 4.5 去重 (`deduplicator.py`)

- 唯一键：`(source, external_id)`
- 入库前查询 SQLite：`SELECT 1 FROM events WHERE source=? AND external_id=?`
- 存在则跳过

### 4.6 存储 (`storage.py`)

SQLite schema:

```sql
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    url TEXT,
    published_at TIMESTAMP NOT NULL,
    importance TEXT NOT NULL,
    raw_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, external_id)
);

CREATE INDEX idx_ticker_time ON events(ticker, published_at DESC);
CREATE INDEX idx_importance_time ON events(importance, published_at DESC);
```

**清理策略：** 启动时运行一次 `DELETE FROM events WHERE created_at < datetime('now', '-30 days')`，之后每天凌晨清理。

### 4.7 推送 (`notifier.py`)

使用 Server-Sent Events (SSE)：
- 端点：`GET /stream`
- 新事件写入 DB 后，向所有连接的客户端推送 JSON
- 客户端 JS 通过 `EventSource` 接收，触发 `Notification.requestPermission()` 后显示

### 4.8 API 路由

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/` | 返回 Dashboard HTML |
| GET | `/api/events?importance=&ticker=&limit=` | 历史事件查询 |
| GET | `/api/watchlist` | 读当前 watchlist |
| GET | `/stream` | SSE 新事件推送 |
| GET | `/healthz` | 健康检查 |

---

## 5. Dashboard UI

### 布局

```
┌─────────────────────────────────────────────────┐
│  [Header] 今日: 3个高重要性事件  🔔 [通知开关]  │
├──────────────┬──────────────────────────────────┤
│ [左侧栏]     │ [主区: 事件流 按时间倒序]         │
│              │                                  │
│ Watchlist    │ ┌─────────────────────────────┐ │
│  - EOSE      │ │ 🔴 EOSE 发布 8-K           │ │
│  - MDB       │ │    2分钟前 · 查看原文 ↗     │ │
│  - NVDA      │ ├─────────────────────────────┤ │
│              │ │ 🟡 MDB 财报将于 2026-04-25 │ │
│ 筛选:        │ │    7天后                    │ │
│ ☑ 高         │ ├─────────────────────────────┤ │
│ ☑ 中         │ │ 🟢 NVDA 发布新闻: ...      │ │
│ ☐ 低         │ │    1小时前                  │ │
│              │ └─────────────────────────────┘ │
└──────────────┴──────────────────────────────────┘
```

### 交互行为

- 新事件到达：顶部插入，背景短暂高亮 2 秒
- 卡片点击：展开显示 summary，再点击外部链接打开原文
- 重要性筛选：勾选框即时过滤，不发请求（前端过滤已加载事件）
- 浏览器通知：仅对 `importance == "high"` 触发
- 通知开关：localStorage 持久化

### 颜色编码
- 🔴 高：红色左边框 `#f85149`
- 🟡 中：黄色左边框 `#d29922`
- 🟢 低：绿色左边框 `#3fb950`

---

## 6. 配置

**`.env` 文件（不入库）：**
```
FINNHUB_API_KEY=xxx
```

**`config.py`：**
```python
FINNHUB_INTERVAL_MINUTES = 5
SEC_INTERVAL_MINUTES = 5
EARNINGS_CALENDAR_HOUR = 0  # 每天凌晨
DB_PATH = "data/events.db"
RETAIN_DAYS = 30
PORT = 8000
```

**`watchlist.json`（用户编辑）：**
```json
{
  "tickers": ["EOSE", "MDB", "NVDA"]
}
```

---

## 7. 错误处理

| 场景 | 策略 |
|------|------|
| 数据源 API 报错/超时 | 单次失败跳过，记日志，下次轮询重试；不影响其他源 |
| 429 速率限制 | 指数退避（10s → 60s → 300s），最多 3 次 |
| SQLite 写冲突 | 使用 `INSERT OR IGNORE`，依赖 UNIQUE 约束 |
| SSE 客户端断开 | 服务端自动清理连接，客户端自动重连 |
| 启动时 Finnhub key 缺失 | 日志警告，跳过该源，其他源正常运行 |
| watchlist.json 格式错误 | 启动失败并打印清晰错误信息 |

---

## 8. 测试策略

### 单元测试 (pytest)
- `test_sources.py`：mock HTTP 响应，验证字段映射正确
- `test_scorer.py`：覆盖所有重要性分支
- `test_storage.py`：去重、清理、查询
- `test_deduplicator.py`：重复事件不二次入库

### 集成测试
- 启动完整 app（使用内存 SQLite + mock 数据源），验证事件从拉取到 SSE 推送的完整链路

### 手动验收
- 真实 API key 跑一轮，验证 watchlist 中的股票能正确拉到真实数据
- 浏览器通知能正常触发

---

## 9. 开发里程碑

| 阶段 | 内容 | 验收 |
|------|------|------|
| M1 | 项目骨架 + Event 数据结构 + SQLite | 能手动插入/查询事件 |
| M2 | 三个数据源实现 + 单测 | 单测全绿 |
| M3 | 调度 + 去重 + 打分 | 端到端跑 10 分钟无重复 |
| M4 | FastAPI 路由 + 历史查询 | `GET /api/events` 返回数据 |
| M5 | Dashboard UI + SSE | 浏览器能看到事件流实时更新 |
| M6 | 浏览器通知 + 筛选 + 样式打磨 | 手动验收通过 |

---

## 10. 默认决策（确认清单）

以下在设计沟通中已默认，若有异议请在实施前提出：

- [x] watchlist 通过编辑 `watchlist.json` 管理，UI 添加按钮留 Phase 2
- [x] 轮询频率：新闻 5 分钟，财报日历每天 1 次
- [x] 通知声音默认关闭，UI 可开
- [x] 事件历史保留 30 天
- [x] 浏览器通知仅对"高"重要性触发
- [x] 只支持本地运行，不做多用户/云端
