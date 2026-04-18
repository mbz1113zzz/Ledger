# 项目恢复指南

如果当前会话中断（额度耗尽 / 上下文丢失 / 其他原因），把这个文件和下面提到的其他文件贴给新会话，即可无缝接手。

---

## 项目背景一句话

本地运行的美股事件监控系统（MVP Phase 1）：定时从 Finnhub / SEC EDGAR / yfinance 拉取用户关注股票的新闻、8-K 备案、财报日历，Web Dashboard 展示 + 浏览器通知。

---

## 关键路径

- **工作目录：** `/Users/mabizheng/Desktop/美股/`
- **项目代码：** `stock-monitor/`
- **Spec（设计）：** [docs/superpowers/specs/2026-04-18-us-stock-event-monitor-design.md](superpowers/specs/2026-04-18-us-stock-event-monitor-design.md)
- **Plan（实现计划，16 tasks）：** [docs/superpowers/plans/2026-04-18-us-stock-event-monitor.md](superpowers/plans/2026-04-18-us-stock-event-monitor.md)
- **API Key：** 已存于 `/Users/mabizheng/Desktop/美股/.env`（`FINNHUB_API_KEY=...`），已 gitignored
- **Python 环境：** conda env `stock-monitor`（Python 3.11）
  - 可执行: `~/miniconda3/envs/stock-monitor/bin/python`
  - 运行测试: `cd stock-monitor && PYTHONPATH=. ~/miniconda3/envs/stock-monitor/bin/python -m pytest -v`
- **Git：** 已在父目录 `/Users/mabizheng/Desktop/美股/` 初始化，branch `main`

---

## 执行策略

原 plan 有 16 个细粒度 task。为节省 token，实际按 **4 个批次 + 1 个验证 + 1 个最终 review** 执行：

- **Batch A** = Tasks 2–6（基础模块）
- **Batch B** = Tasks 7–9（三个数据源）
- **Batch C** = Tasks 10–12（Notifier / Pipeline / Scheduler）
- **Batch D** = Tasks 13–15（FastAPI 路由 / Dashboard UI / 主入口）
- **Task 16** = 端到端验证（主线 agent 自己做）
- **Final** = 最终 code review

每个 batch 派一个 `general-purpose` subagent 执行，plan 里的代码完整可 paste，subagent 主要负责落地 + 跑测试 + git commit。

---

## 进度表

| 阶段 | 状态 | Commit SHA（最新） | 测试数 |
|------|------|-------------------|--------|
| Task 1 Scaffolding | ✅ 完成 | `8dde576` | — |
| Batch A (Tasks 2–6) | ✅ 完成 | `867219d` | 23/23 |
| Batch B (Tasks 7–9) | ✅ 完成 | `ce30dfe` | 33/33 |
| Batch C (Tasks 10–12) | ✅ 完成 | `89d93b1` | 38/38 |
| Batch D (Tasks 13–15) | ⬜ 未开始 | — | — |
| Task 16 E2E | ⬜ 未开始 | — | — |
| Final review | ⬜ 未开始 | — | — |

**随时核对进度：**
```bash
cd /Users/mabizheng/Desktop/美股 && git log --oneline
```

---

## 恢复操作（新会话开场白模板）

贴给新会话：

> 继续之前的项目：美股事件监控系统 MVP。
> 工作目录 `/Users/mabizheng/Desktop/美股/`。
> 请读 [docs/superpowers/RECOVERY.md](docs/superpowers/RECOVERY.md) 了解进度，
> 然后从「未开始」的第一个批次继续。
> 使用 `superpowers:subagent-driven-development` 技能，每个 batch 派 subagent。
> Plan 文件里有每个 task 的完整代码，可直接粘给 subagent。

---

## 每个批次 subagent 提示词模板要点

Subagent 的 prompt 必须包含：

1. **环境**：工作目录 / conda python 路径 / 测试命令
2. **前置状态**：已存在哪些模块、pytest.ini 已建立 / asyncio_mode = auto
3. **每个 task 的完整代码**（从 plan 文件复制，不要让 subagent 自己去读）
4. **提交规范**：`git add <files> && git commit -m "feat: ..."`，每个 task 一个 commit
5. **报告格式**：DONE/DONE_WITH_CONCERNS/BLOCKED/NEEDS_CONTEXT + 测试数 + commit SHA

---

## 已知坑（避免重复踩）

- **Mac 默认 `python3` 是 3.9**，代码用了 `str | None` 语法需要 3.10+ → 必须用 conda env `stock-monitor`
- **pytest-asyncio 需要配置**：`stock-monitor/pytest.ini` 已设 `asyncio_mode = auto`
- **`.env` 禁止 commit**：已在 `.gitignore`
- **`data/` 禁止 commit**：已在 `.gitignore`（`.gitkeep` 需要 `git add -f`）
- **SEC EDGAR 必须带 User-Agent**：已在 `config.SEC_USER_AGENT` 配好
- **git commit 请在父目录执行**（`/Users/mabizheng/Desktop/美股/`），路径加 `stock-monitor/` 前缀

---

## Batch D 下一步 TL;DR

参照 plan 的 Tasks 13、14、15：
- `web/routes.py`（FastAPI 路由：`/`, `/api/events`, `/api/watchlist`, `/healthz`, `/stream` SSE）
- `web/static/index.html` + `style.css` + `app.js`（Dashboard UI，SSE 客户端 + 浏览器通知）
- `app.py`（FastAPI 主入口，`lifespan` 启动时 init storage、加载 SEC ticker map、首次运行 pipeline、启动调度器）
- 无新增单元测试；靠 Task 16 端到端验证

## 完成后 Task 16 TL;DR

端到端手工验证：
1. `cd stock-monitor && PYTHONPATH=. ~/miniconda3/envs/stock-monitor/bin/python app.py`
2. 浏览器访问 `http://localhost:8000`
3. 验证 `/healthz`, `/api/events`, `/api/watchlist`, `/stream` 四个端点
4. 勾选🔔通知，授权浏览器权限
5. 重启看去重是否生效

---

*本文件在每个 batch 完成后由主线 agent 更新「进度表」和「下一步 TL;DR」章节。*
