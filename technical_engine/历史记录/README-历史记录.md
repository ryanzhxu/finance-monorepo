# 每日盘后 Decision History

这个目录保存**离线验证用途**的每日盘后 Recommendation Snapshot。它不进入 Dashboard 前端、不参与当前 Recommendation，也不会把历史数据库加载进 Render 的常驻内存。

## 运行方式

Render Web Service 内的后端调度器每天在 `America/New_York` 的 **4:30 PM ET** 运行。它先执行与生产刷新相同的全量 live refresh，再调用现有 JavaScript `technical-features.js` 和 `decision-engine/` 生成 Short / Mid / Long 的正式快照，最后用短 SQLite transaction 写入数据库。

周末会跳过。周一至周五也会检查最新 Daily market bar 是否属于当天交易日；交易所假日或没有任何有效当天数据时会记录 `eod_runs.status = skipped`，绝不会把前一天 cache 伪装成当天 EOD。当天个别 ticker 的 Daily bar 仍是前一天时，会写入明确的 `unavailable` 行，而不会保存过期 Recommendation。

本地手动模拟（不必等到 4:30）：

```bash
python3 历史记录/历史记录.py --run-now
```

这个命令仍会执行 full live refresh，并只在今天确实有有效交易 session 时写入。

## 数据库位置

优先级如下：

1. `DECISION_HISTORY_DB_PATH` 环境变量（生产建议显式设置）。
2. Render Persistent Disk 已挂载且可写时：`/var/data/历史记录.sqlite`。
3. 本地开发：`历史记录/历史记录.sqlite`。

Render 当前 `render.yaml` 的 Persistent Disk mount 是 `/var/data`。建议在 Render Environment 增加：

```text
DECISION_HISTORY_DB_PATH=/var/data/历史记录.sqlite
```

`render.yaml` 已把 `EOD_DECISION_NODE_PATH=node` 写入 Blueprint；Render native deployment 提供 Node 工具。仅在将来改用不含 Node 的运行环境时，才需要把它改成实际 Node binary 的绝对路径：

```text
EOD_DECISION_NODE_PATH=/path/to/node
```

`EOD_HISTORY_NODE_MAX_OLD_SPACE_MB=192` 也已在 Blueprint 设置。这个一次性 Node 快照进程在提交后退出，不会长期占用 Dashboard RAM；如未来 watchlist 明显扩大，可在不超过 Render 内存预算的前提下审慎调整。

记录器必须使用 Node，因为正式 Decision Engine 是现有 JavaScript 实现；它不会创建 Python 近似推荐逻辑。

## 保存内容

`decision_history` 的唯一键是：`market_date + ticker + horizon`。重复运行同一天任务会 UPSERT 覆盖同一条正式记录，不会重复累积。

每一条包含：

- Identity：交易日、ET 记录时间、ticker、stock/ETF、horizon、data status。
- Final Decision：Action、Confidence、Price State、Current Price。
- Price Landscape：Opportunity / Reduce 范围、Invalidation、Landscape quality。
- 当前真正用于决策的 Direction、Confirmation、Risk、Exhaustion。
- 紧凑 Market context、supporting / limiting reasons、material-change 状态。
- 紧凑 canonical technical feature snapshot：MA、RSI、MACD、ADX/DI、ATR、Bollinger、KDJ、OBV/RVOL、Relative Strength、Fibonacci provenance / selected structure、52W context。
- Stock 的 Primary Classification、Company Traits、Lifecycle、应用 modifiers；或 ETF 的 leveraged、direction、underlying、ETF modifiers。

**不会**保存原始 OHLCV 数组、每根 1H/4H/Daily/Weekly bar、完整指标 series、目标价、旧 Action Score 或任何 Recommendation history cache。

`eod_runs` 只保存每个交易日一次轻量运行状态、记录行数、unavailable 数、错误摘要与数据库大小，便于检查是否漏跑。

## 查看最近运行

可以在 Render 服务日志搜索简洁日志：

```text
[EOD HISTORY] started 2026-08-18 16:30 ET
[EOD HISTORY] full refresh complete
[EOD HISTORY] 34 tickers / 102 horizon rows
[EOD HISTORY] 2 unavailable
[EOD HISTORY] database commit success
[EOD HISTORY] db size 3.4 MB
[EOD HISTORY] completed
```

失败或无有效当天交易数据也会留下 `eod_runs` 状态与简洁日志。

## 导出供离线分析

默认导出 CSV 到 `历史记录/导出/`：

```bash
python3 历史记录/导出历史记录.py
```

指定时间范围、格式和输出文件：

```bash
python3 历史记录/导出历史记录.py \
  --from 2026-08-01 --to 2026-08-31 --format jsonl \
  --output 历史记录/导出/2026-08.jsonl
```

支持 `csv`、`json`、`jsonl`。导出脚本是离线工具；Dashboard 本身永远不会读取整个历史库。

## 如果以后不再需要此功能

1. 删除项目目录 `历史记录/`（数据库与导出文件不在 Git）。
2. 从 `server.py` 删除 EOD scheduler 启动、`run_eod_history_once` 及其 import。
3. 从 Render Environment 删除 `DECISION_HISTORY_DB_PATH` 和可选的 `EOD_DECISION_NODE_PATH`。
4. 从 Render Persistent Disk 删除 `/var/data/历史记录.sqlite` 及其 `-wal` / `-shm` 文件。
5. 删除 `AGENTS.md` 中的 EOD Decision History Contract。

删除这项功能不会改变当前 Dashboard、Technical / Market 页面或 V1 Decision Engine 的计算结果。
