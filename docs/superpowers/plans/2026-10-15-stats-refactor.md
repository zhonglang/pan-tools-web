# 数据概览页重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按设计文档重构数据概览：账号+可选时间筛选、历史/区间指标、后端分页表格、日表驱动折线，并去掉新建分享面板。

**Architecture:** 新增 `account_stat_days`（账号×日水位）。同步写完分享快照后 upsert 当日行；历史汇总与表格只查 `share_links`；区间卡片用日表「结束日−开始日」；区间表格用链接边界快照算增量并在 SQL 侧分页；折线只读日表。前端按有无日期切换 UI。

**Tech Stack:** FastAPI、SQLAlchemy、Alembic、PostgreSQL、React、现有 pytest / TestClient。

**Spec:** `docs/superpowers/specs/2026-10-15-stats-refactor-design.md`

---

## File map

| 文件 | 职责 |
|---|---|
| `backend/alembic/versions/012_account_stat_days.py` | 建表 + 从 `share_stat_snapshots` 回填 |
| `backend/app/models/share.py` | 新增 `AccountStatDay` 模型 |
| `backend/app/models/__init__.py` | 导出模型 |
| `backend/app/services/stats.py` | 写入日表、回填辅助、重写 `query_stats`；删除 `query_created_shares` |
| `backend/app/schemas/stats.py` | `SeriesLineOut.kind`；弱化/兼容 `rank`；可删 `CreatedSharesOut` |
| `backend/app/api/routes/stats.py` | `GET /api/stats` 以有无日期区分模式；删除 `/api/stats/created` |
| `backend/app/schemas/__init__.py` | 导出调整 |
| `backend/tests/test_stats.py` | 按新语义重写/增补 |
| `frontend/src/api.ts` | `statsQuery` 去掉 `rank`；删 `createdShares` |
| `frontend/src/components/TransferChart.tsx` | 双线（增量+总量）图例与文案 |
| `frontend/src/components/DateRangePicker.tsx` | 支持清空（可选：Stats 页外包一层「清除」） |
| `frontend/src/pages/StatsPage.tsx` | 新筛选与展示 |

---

### Task 1: 模型与迁移（含回填）

**Files:**
- Create: `backend/alembic/versions/012_account_stat_days.py`
- Modify: `backend/app/models/share.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: 在 `share.py` 增加模型**

```python
class AccountStatDay(Base):
    __tablename__ = "account_stat_days"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("pan_accounts.id"), index=True)
    stat_date: Mapped[datetime] = mapped_column(Date)  # 用 sa.Date
    transfer_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    view_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    download_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    link_total: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

使用 `sqlalchemy.Date`；并加 `UniqueConstraint("account_id", "stat_date")`。

- [ ] **Step 2: 导出模型**

在 `models/__init__.py` 导入并加入 `__all__`。

- [ ] **Step 3: 写 Alembic 012**

- `down_revision = "011_library_items"`
- `upgrade`: `create_table` + `UniqueConstraint` + index `(account_id, stat_date)`
- 同文件末尾执行回填 SQL（或 `op.execute` 多步）：

思路（PostgreSQL）：

```sql
INSERT INTO account_stat_days (account_id, stat_date, transfer_total, view_total, download_total, link_total, updated_at)
SELECT
  account_id,
  ((taken_at AT TIME ZONE 'Asia/Shanghai')::date) AS stat_date,
  SUM(transfer_count) FILTER (WHERE transfer_count IS NOT NULL),
  SUM(view_count) FILTER (WHERE view_count IS NOT NULL),
  SUM(download_count) FILTER (WHERE download_count IS NOT NULL),
  COUNT(DISTINCT share_link_id),
  NOW()
FROM (
  SELECT DISTINCT ON (account_id, share_link_id, ((taken_at AT TIME ZONE 'Asia/Shanghai')::date))
    account_id, share_link_id, transfer_count, view_count, download_count, taken_at
  FROM share_stat_snapshots
  ORDER BY account_id, share_link_id, ((taken_at AT TIME ZONE 'Asia/Shanghai')::date), taken_at DESC, id DESC
) AS last_per_share_day
GROUP BY account_id, ((taken_at AT TIME ZONE 'Asia/Shanghai')::date)
ON CONFLICT (account_id, stat_date) DO UPDATE SET
  transfer_total = EXCLUDED.transfer_total,
  view_total = EXCLUDED.view_total,
  download_total = EXCLUDED.download_total,
  link_total = EXCLUDED.link_total,
  updated_at = EXCLUDED.updated_at;
```

（表需有对应 UNIQUE 名；若用 `UniqueConstraint` 无名，用列列表 `ON CONFLICT (account_id, stat_date)`。）

- [ ] **Step 4: 本地/远程执行迁移**

Run: `cd backend && uv run alembic upgrade head`  
Expected: 成功；`account_stat_days` 有回填行（远程大库应有大量行）。

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/012_account_stat_days.py backend/app/models/share.py backend/app/models/__init__.py
git commit -m "feat: add account_stat_days table and backfill"
```

---

### Task 2: 同步时 upsert 日表

**Files:**
- Modify: `backend/app/services/stats.py`
- Test: `backend/tests/test_stats.py`

- [ ] **Step 1: 写失败测试**

在 `test_stats.py` 增加（同步成功路径上断言日表）：

```python
def test_sync_upserts_account_stat_day(client):
    # register + mock baidu list one share tCnt=5
    # execute_sync ...
    # assert AccountStatDay for account, Shanghai date of NOW
    # transfer_total == 5, link_total == 1
    # run sync again with tCnt=8 same day
    # still one row, transfer_total == 8
```

复用现有 `test_sync_updates_records_and_marks_missing_removed` 的 mock 风格。

- [ ] **Step 2: Run 确认失败**

Run: `uv run pytest tests/test_stats.py::test_sync_upserts_account_stat_day -v`  
Expected: FAIL（无模型写入或无行）

- [ ] **Step 3: 实现 `_upsert_account_stat_day`**

在 `apply_share_records` 末尾、`_write_daily_snapshots` 之后调用：

```python
def _upsert_account_stat_day(session, account, active: list[ShareLink], now: datetime) -> None:
    moment = _aware(now)
    stat_date = moment.astimezone(SHANGHAI).date()
    def _sum(field: str) -> int | None:
        values = [getattr(row, field) for row in active if getattr(row, field) is not None]
        return sum(values) if values else None
    row = session.scalars(
        select(AccountStatDay).where(
            AccountStatDay.account_id == account.id,
            AccountStatDay.stat_date == stat_date,
        )
    ).first()
    if row is None:
        row = AccountStatDay(account_id=account.id, stat_date=stat_date)
        session.add(row)
    row.transfer_total = _sum("transfer_count")
    row.view_total = _sum("view_count")
    row.download_total = _sum("download_count")
    row.link_total = len(active)
    row.updated_at = moment
```

- [ ] **Step 4: 测试通过并 Commit**

```bash
uv run pytest tests/test_stats.py::test_sync_upserts_account_stat_day -v
git add backend/app/services/stats.py backend/tests/test_stats.py
git commit -m "feat: upsert account_stat_days on share sync"
```

---

### Task 3: 重写历史模式 `query_stats`（无日期）

**Files:**
- Modify: `backend/app/services/stats.py`
- Modify: `backend/app/api/routes/stats.py`
- Modify: `backend/app/schemas/stats.py`（`rank` 可改为可选默认 `"history"` / `"range"` 由有无日期决定）
- Test: `backend/tests/test_stats.py`

- [ ] **Step 1: 写失败测试**

```python
def test_history_stats_paginates_share_links(client):
    # 插入 3 条 active share，transfer_count 5,3,None
    # GET /api/stats?page=1&page_size=2  (无 start/end)
    # total==3, rank_total==3, len(rows)==2
    # rows[0].transfers == 5
    # dates == []
```

同时改 `user_stats`：无 `start/end` 视为历史，**不再要求** `rank=range` 必须带日期。

- [ ] **Step 2: 实现历史查询（SQL 聚合 + 分页）**

```python
# summary
total = count active
transfers = sum(transfer_count) ...
# rows
select ShareLink where account_id in (...) and status=='active'
order by transfer_count.desc().nulls_last(), created_at.desc()
offset/limit
# series empty
```

`query_stats` 签名建议改为：无 start/end → history；有 → range（可忽略旧 `rank` 参数或映射）。

- [ ] **Step 3: 调整路由**

```python
# GET /api/stats
if start and end:
    mode = "range"
elif not start and not end:
    mode = "history"
else:
    raise 422
# 删除对 rank==range 强制日期的旧逻辑；rank 查询参数可废弃但保持兼容（忽略）
```

- [ ] **Step 4: 测试通过并 Commit**

```bash
uv run pytest tests/test_stats.py -k history -v
git add backend/app/services/stats.py backend/app/api/routes/stats.py backend/tests/test_stats.py
git commit -m "feat: paginate history stats from share_links"
```

---

### Task 4: 区间卡片（日表水位差）+ 区间 series

**Files:**
- Modify: `backend/app/services/stats.py`
- Modify: `backend/app/schemas/stats.py` — `SeriesLineOut` 增加 `kind: str`（`"delta"` | `"total"`）
- Test: `backend/tests/test_stats.py`

- [ ] **Step 1: 写失败测试**

```python
def test_range_summary_uses_account_stat_days(client):
    # AccountStatDay: 9-01 transfer=10, 9-10 transfer=25
    # GET /api/stats?start=2026-09-01&end=2026-09-10
    # transfers.value == 15
    # dates 含区间每日；lines 两条 kind=total 与 kind=delta
```

缺开始或结束日行时 `transfers.value is None`。

- [ ] **Step 2: 实现**

```python
# load AccountStatDay for accounts where stat_date in [start_date, end_date]
# 以及 start_date 当天行（用于增量基线）
# card transfer = sum(end_day.transfer_total) - sum(start_day.transfer_total)  # 多账号先按日合计
# series dates = each day in range
# total_line[i] = sum transfer_total that day (None if no row)
# delta_line[i] = total[i] - prev_total (prev 可为 start-1 day row)
```

`new_shares` / `total`（区间）：`COUNT` active links with `created_at` in `[start, end]`。

- [ ] **Step 3: 测试通过并 Commit**

```bash
uv run pytest tests/test_stats.py::test_range_summary_uses_account_stat_days -v
git commit -m "feat: range summary and chart from account_stat_days"
```

---

### Task 5: 区间表格分页（链接增量）

**Files:**
- Modify: `backend/app/services/stats.py`
- Test: `backend/tests/test_stats.py`

- [ ] **Step 1: 写失败测试**

两条分享，各自在 start 前与 end 有快照；断言第一页按 transfer 增量排序，且只返回 page_size 条；`rank_total` 为 active 总数。

- [ ] **Step 2: 实现（避免全量进 Python）**

推荐原生 SQL / SQLAlchemy：

1. 子查询：每条 `share_link_id` 在 `taken_at <= start` 的最后 transfer/view/download  
2. 子查询：`taken_at <= end` 的最后值  
3. `JOIN share_links` active，`delta = end - start`（NULL 安全）  
4. `ORDER BY delta NULLS LAST, created_at DESC LIMIT/OFFSET`

若 SQL 过重，允许先对 **当前页候选** 优化：用窗口函数一次取出边界。禁止 `session.scalars(select(ShareStatSnapshot).where(account_id.in_(...))).all()` 全表拉取。

- [ ] **Step 3: 测试通过并 Commit**

```bash
git commit -m "feat: paginate range rank rows with snapshot deltas"
```

---

### Task 6: 删除新建分享 API

**Files:**
- Modify: `backend/app/api/routes/stats.py` — 删除 `created_share_stats`
- Modify: `backend/app/services/stats.py` — 删除 `query_created_shares`
- Modify: `backend/app/schemas/stats.py` / `__init__.py`
- Modify: `backend/tests/test_stats.py` — 删除/改写相关用例

- [ ] **Step 1: 删除路由与服务函数，更新测试**

`GET /api/stats/created` 应 404。

- [ ] **Step 2: Commit**

```bash
git commit -m "refactor: remove created-shares stats endpoint"
```

---

### Task 7: 前端 API 与图表

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/TransferChart.tsx`

- [ ] **Step 1: `statsQuery`**

```ts
statsQuery: (accountId, page, pageSize, start, end) => {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (accountId != null) params.set("account_id", String(accountId));
  if (start && end) { params.set("start", start); params.set("end", end); }
  return request<AccountStats>(`/api/stats?${params}`);
},
```

删除 `createdShares`。`TransferLine` 增加可选 `kind?: "delta" | "total"`。

- [ ] **Step 2: `TransferChart`**

- 去掉对 `mode===history` 的依赖；文案改为同时解释「实线总量 / 虚线或第二色增量」（按 `kind` 分色或分线型）。
- `caption`：区间内每天转存总量与相对前一天的增量。

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: update stats client types and dual-line chart"
```

---

### Task 8: 重构 `StatsPage`

**Files:**
- Modify: `frontend/src/pages/StatsPage.tsx`
- Modify: `frontend/src/components/DateRangePicker.tsx`（若需清空：增加 `allowClear` 或页面旁「清除日期」按钮把 `start/end` 置 `""`）

- [ ] **Step 1: 状态**

```ts
const [start, setStart] = useState(""); // 空 = 历史
const [end, setEnd] = useState("");
// 删除 rank、created*、panel
const ranged = Boolean(start && end);
```

- [ ] **Step 2: 筛选 UI**

仅 `AccountSelect` + 日期（带清除）。无 mode 切换。

- [ ] **Step 3: 卡片**

四个：总链接（`stats.total`）、总转存、总浏览、总下载。  
历史 note：「当前累计」；区间 note：「区间水位差」/「区间新建」。

- [ ] **Step 4: 图表**

`ranged && stats` 时渲染 `TransferChart`；否则不渲染。

- [ ] **Step 5: 表格**

只保留原排行表；列含义随 `ranged` 切换文案（累计 vs 增量）。删除新建分享表与 Tab。

- [ ] **Step 6: 请求**

```ts
api.statsQuery(accountId, page, pageSize, ranged ? start : null, ranged ? end : null)
```

- [ ] **Step 7: 手工点验 + Commit**

```bash
git commit -m "feat: rebuild stats page filters and layout"
```

---

### Task 9: 回归与清理

- [ ] **Step 1: 跑后端测试**

```bash
cd backend && uv run pytest tests/test_stats.py -q
```

Expected: 全绿。修复旧用例里对 `rank`、`/stats/created`、全量快照假设的断言。

- [ ] **Step 2: 跑迁移后远程抽查（可选）**

```sql
SELECT count(*) FROM account_stat_days;
SELECT * FROM account_stat_days WHERE account_id=2 ORDER BY stat_date DESC LIMIT 5;
```

- [ ] **Step 3: 浏览器**

- 未选日期：无图、表格分页、卡片为累计。  
- 选最近一周：有双折线、卡片为增量、翻页不卡顿。  
- 刷新数据后当日日表更新。

- [ ] **Step 4: Final commit（若有修复）**

```bash
git commit -m "test: align stats suite with refactor"
```

---

## 执行方式

计划写好后请用户选择：

1. 本会话按 task 分包执行（subagent-driven-development）  
2. 本会话按 plan 顺序执行（executing-plans）  
3. 只要计划，稍后再做  

**默认推荐：1。**
