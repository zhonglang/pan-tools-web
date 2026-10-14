# 数据概览页重构设计

日期：2026-10-15

重构数据分析（数据概览）页：去掉「新建分享」统计；筛选只保留账号与时间；未选时间为历史累计；选了时间为区间增量；表格后端分页；区间折线图改读账号日统计表；同步时写入日表并用现有快照回填。

目标：远程库场景下首屏与翻页明显变快；指标规则按本文定义，与旧版「按链接逐条 delta 再汇总」在语义上对齐为「账号日水位差 / 链接边界差」。

## 1. 交互

### 筛选

- 仅：**账号选择** + **时间范围**（可清空，默认不选）。
- 去掉：「时间范围增量 / 历史累计」切换。
- 去掉：「新建分享」面板及入口。

### 未选时间（历史）

- 顶部卡片：总链接、总转存、总浏览、总下载（均为当前库中最新累计）。
- **无折线图**。
- 一张表格：当前账号下全部 `active` 分享，**后端分页**。

### 选了时间（区间）

- 顶部卡片：总链接（区间内新建数）、总转存 / 总浏览 / 总下载（区间水位差）。
- **两套折线数据**：每天转存增量、每天转存总量（可同图双线或并排，实现时选一种，默认同图双线）。
- 表格：仍为当前账号全部 `active` 分享，指标为区间增量，后端分页。

### 刷新数据

保留「刷新数据」：走现有百度分享同步；同步成功后更新当日 `account_stat_days` 行。

## 2. 指标定义

### 历史（无 start/end）

| 卡片 | 定义 |
|---|---|
| 总链接 | `COUNT` active `share_links` |
| 总转存 / 浏览 / 下载 | `SUM` 对应 `share_links.*_count`（忽略 NULL，全 NULL 则「暂无」） |

表格行：直接使用 `share_links` 当前累计字段。默认排序：`transfer_count DESC NULLS LAST`，再 `created_at DESC`。

### 区间（有 start/end，按北京时间日期闭区间）

| 卡片 | 定义 |
|---|---|
| 总链接 | `created_at` 落在 `[start, end]` 内的 active 分享数 |
| 总转存 | 优先：`account_stat_days` 上结束日 `transfer_total` − 开始日 `transfer_total`；任一日缺失则「暂无」 |
| 总浏览 / 总下载 | 同上，用 `view_total` / `download_total` |

说明：开始日水位表示「该日统计行所代表的当日同步累计」；与产品举例「9/10 总量 − 9/1 总量」一致。日表由同步写入，一天一行。

表格行（每条 active 分享的区间增量）：

- 取该链接在 `share_stat_snapshots` 中：`taken_at ≤ end` 的最后一条有值快照，减去 `taken_at ≤ start` 的最后一条有值快照（按字段分别判断）。
- 任一侧缺失则该字段为 NULL（展示「暂无」）。
- 排序：区间 `transfer` 增量 `DESC NULLS LAST`，再 `created_at DESC`。
- **仅查询当前页所需行**：先在 SQL/子查询中算出可排序键再 `LIMIT/OFFSET`，避免全量进内存。

### 折线（仅区间）

数据源：`account_stat_days`，`stat_date` 落在 `[start, end]`。

- **每天转存总量**：当日 `transfer_total`。
- **每天转存增量**：当日 `transfer_total` − 前一日 `transfer_total`（前一日无行则为 NULL / 不连点）。

账号范围与现页一致：传入 `account_id` 则只查该账号；未传则查当前用户下参与统计的账号（百度/夸克）。  
折线：多账号时每条账号一条「总量」线与一条「增量」线（`kind` 区分），或先按日把多账号 `transfer_total` 相加再画合计增量/总量——**实现采用后者（合计一条增量 + 一条总量）**，表格仍按所选账号集合过滤。

## 3. 新表 `account_stat_days`

```text
id              PK
account_id      FK pan_accounts.id  NOT NULL
stat_date       DATE NOT NULL          -- 北京时间日历日
transfer_total  INT NULL
view_total      INT NULL
download_total  INT NULL
link_total      INT NOT NULL DEFAULT 0
updated_at      TIMESTAMPTZ NOT NULL
UNIQUE (account_id, stat_date)
INDEX (account_id, stat_date)
```

### 写入

在 `apply_share_records` 写完当日 per-link 快照之后：

1. 对当前账号全部 active 链接，分别 `SUM` transfer/view/download（NULL 不计入 sum；若该指标全 NULL 则存 NULL）。
2. `link_total = COUNT(active)`。
3. `stat_date = 当前时刻转上海时区后的 date`。
4. Upsert：已存在则更新总量字段与 `updated_at`；不存在则插入。

当日多次同步 / 多次全量查询：只更新当天这一行。

### 回填

一次性迁移或管理命令 / alembic data migration：

1. 从 `share_stat_snapshots` 按 `(account_id, share_link_id, 上海日期)` 取每日最后一条快照。
2. 按 `(account_id, 上海日期)` 对 transfer/view/download 求和，`link_total` 为该日有快照的 distinct share 数（或当日出现过的链接数）。
3. 写入 `account_stat_days`；已存在则跳过或覆盖（回填默认覆盖）。

## 4. 接口

### `GET /api/stats`

Query：

- `account_id` 可选
- `start` / `end` 可选，成对出现；格式与现网一致（日期）
- `page` / `page_size`

响应（字段名可与现 `StatsOut` 兼容裁剪）：

```json
{
  "total": 100,
  "new_shares": 100,
  "transfers": {"value": 10, "from_time": null},
  "views": {"value": 20, "from_time": null},
  "downloads": {"value": 5, "from_time": null},
  "page": 1,
  "page_size": 20,
  "rank_total": 100,
  "rows": [],
  "dates": ["2026-09-01", "..."],
  "lines": [
    {"account_id": 2, "account_name": "...", "values": [1, 2], "kind": "delta"},
    {"account_id": 2, "account_name": "...", "values": [100, 102], "kind": "total"}
  ]
}
```

- 无日期：`dates`/`lines` 为空数组；`total` 与 `new_shares` 均为 active 总数（或 `new_shares` 复用为总链接，前端只展示一个「总链接」卡片时用 `total`）。
- 有日期：`total` = 区间新建链接数；四个增量卡片用 transfers/views/downloads；`new_shares` 可与 `total` 同值或弃用（前端以「总链接」为准）。
- 去掉对 `first_snapshot_at` 的强依赖展示（可保留字段兼容）。

### 废弃

- 前端不再调用 `GET /api/stats/created`。
- 后端该路由可在同次改动中删除或返回 410；推荐删除并删相关测试。

## 5. 前端

- `StatsPage`：筛选仅账号 + `DateRangePicker`（支持清空为未选）。
- 未选时间：隐藏图表；表格列用累计指标。
- 选了时间：显示双折线；表格列用增量指标。
- 去掉新建分享 Tab/面板。
- 卡片文案改为：总链接、总转存、总浏览、总下载。

## 6. 非目标

- 不在本次删除 `share_stat_snapshots`（链接级快照仍用于表格区间增量与回填来源）。
- 不改为实时直连网盘算统计（仍以库内同步结果为准）。
- 不做跨用户全局统计。

## 7. 验收

- 大账号（约 8k 链接 / 8 万快照）：历史首屏与翻页、区间首屏均明显快于现状（目标 &lt; 2s，同远程库条件）。
- 未选时间无图表请求日表序列；选了时间图表只读 `account_stat_days`。
- 同步两次同一天只保留一行日统计，且 `transfer_total` 为最新。
- 回填后历史日期折线有数据（有快照的日期）。
- 无「新建分享」UI；相关 API 不再被前端调用。
- 回归：stats 相关单测按新语义重写。

## 8. 实施顺序

1. Migration：建 `account_stat_days` + 回填脚本/迁移。
2. 同步路径写入日表。
3. 重写 `query_stats`（历史/区间 summary + 库内分页表 + 日表 series）。
4. 删 created 接口与前端面板。
5. 前端筛选与展示改造。
6. 测试与手工验收。
