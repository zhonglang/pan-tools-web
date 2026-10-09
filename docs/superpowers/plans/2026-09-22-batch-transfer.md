# 批量转存 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户选择一个有效的百度账号和自己网盘里的一层目录，粘贴多行分享链接，由 Worker 按顺序转存；免费用户每天最多 100 条，超额整批拒绝。

**Architecture:** API 只做只读的「列目录」和任务入队。转存请求只由 Worker 调用百度适配器。适配器不访问数据库。额度按上海自然日写在 `daily_usage`，任务一创建就把本次条数计入，不论后来成功还是失败。管理员不计入额度，也不受 100 条限制。付费用户计入额度，但不因条数拒绝。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、Alembic、httpx、pytest。前端是现有的 Vite + React + TypeScript + Tailwind，不装回 Ant Design。

**本计划范围：** 规格《网盘拉新工具设计》的第 3 步。不实现批量分享、CSV、同步、快照、数据查询，也不实现解绑。

**工作区警告：** 分支上可能还有未提交的扫码登录改动。每个任务只 `git add` 本任务列出的文件。

**已锁定的规则：**

- 「每日」是 `Asia/Shanghai` 的自然日。
- 免费用户：本次条数 + 今日已入队条数 > 100 时，整批 422，不创建任务，已用条数不变。响应正文是 `今日还可转存 {n} 条`。
- 付费用户（`plan=paid` 且到期时间严格晚于现在）写入用量，不因条数拒绝。
- 管理员不写 `daily_usage`，也不因条数拒绝。到期后的付费用户按免费处理。
- 空行忽略。去掉空行后没有任何链接，422 `请粘贴分享链接`。
- 链接无法解析仍然创建任务和条目，该条直接失败，原因 `链接无法解析`，并且计入本次条数。
- 目标目录必须已存在。不存在则 422 `目标目录不存在`，不创建任务，不改用量。根目录 `/` 视为存在，不请求百度。
- 目录不是以 `/` 开头，或包含 `..`，422 `目标目录无效`。
- 账号不存在或属于别人：404 `账号不存在`。不是百度：422 `暂未开放`。状态不是 `valid`：422 `请重新登录百度`。
- 单条失败原因只使用这四句：`链接无法解析`、`链接无效`、`提取码错误`、`目标目录已有同名文件`。其它百度错误记为 `转存失败`。
- Cookie 失效时账号改为 `expired`。当前条和本任务里尚未执行的条都记为 `登录已失效，请重新登录`，不再请求百度。规格原文写的是「请重新粘贴 Cookie」；绑定已经改成扫码，这里用「请重新登录」。
- 限流 errno 为 `31034` 或 `9019`。同一条目最多尝试 3 次。第 1 次限流后等 2 秒，第 2 次限流后等 8 秒，第 3 次仍失败则停止，不再等待 20 秒。常量仍写成 `(2, 8, 20)`，其中 20 秒是规格里的第三次间隔，因为没有第 4 次尝试所以不会睡。
- Worker 一次只执行一个 `transfer` 任务。`running` 且超过 15 分钟没更新的条目：尝试次数小于 3 则回到 `pending`，否则记为失败 `已达到重试上限`。
- 全部成功 `succeeded`，有成功也有失败 `partial`，全部失败 `failed`。
- 不自动改名。转存参数 `ondup=fail`。
- 测试不访问真实百度，只用 `httpx.MockTransport`。
- 接口响应和日志都不含 Cookie 原文。

---

## 文件职责

| 文件 | 职责 |
|---|---|
| `backend/app/models.py` | `jobs`、`job_items`、`daily_usage` |
| `backend/alembic/versions/003_jobs.py` | PostgreSQL 建表 |
| `backend/app/links.py` | 解析三种百度分享链接 |
| `backend/app/quota.py` | 上海自然日和转存额度 |
| `backend/app/pans/errors.py` | 转存失败分类 |
| `backend/app/pans/baidu.py` | 列目录、转存分享 |
| `backend/app/transfers.py` | 创建任务、执行一条、收尾状态 |
| `backend/app/worker.py` | 领取任务的进程入口 |
| `backend/app/routers/transfers.py` | 列目录、创建转存、查询任务 |
| `frontend/src/pages/TransferPage.tsx` | 选账号、选目录、粘贴链接 |
| `frontend/src/pages/JobPage.tsx` | 任务进度 |
| `docker-compose.yml` | 增加 Worker 服务 |

---

### Task 1: 任务和用量表

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/alembic/env.py`
- Create: `backend/alembic/versions/003_jobs.py`
- Test: `backend/tests/test_jobs_model.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_jobs_model.py
from datetime import date, datetime, timezone

from sqlalchemy import select

from app.models import DailyUsage, Job, JobItem, User


def test_job_item_defaults_and_usage_day(client):
    with client.app.state.session_factory() as session:
        user = User(email="quota@example.com", password_hash="x")
        session.add(user)
        session.flush()
        job = Job(user_id=user.id, account_id=1, type="transfer", directory="/来自转存", status="pending")
        session.add(job)
        session.flush()
        session.add(JobItem(job_id=job.id, input_text="https://pan.baidu.com/s/1abc", status="pending"))
        session.add(DailyUsage(user_id=user.id, usage_date=date(2026, 9, 22), transfer_count=3, share_count=0))
        session.commit()
        stored = session.scalars(select(JobItem)).one()
        usage = session.scalars(select(DailyUsage)).one()
        assert stored.attempts == 0
        assert stored.error is None
        assert stored.result is None
        assert usage.transfer_count == 3
        assert job.created_at.tzinfo is not None or isinstance(job.created_at, datetime)
```

`client` 夹具会建表。这个测试在模型不存在时导入失败。

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_jobs_model.py -v`

Expected: FAIL，`ImportError` 或 `cannot import name 'Job'`。

- [ ] **Step 3: 写模型**

在 `backend/app/models.py` 增加导入 `Date`、`Integer`、`UniqueConstraint`，并追加：

```python
class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("pan_accounts.id"), index=True)
    type: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    directory: Mapped[str] = mapped_column(String(1024))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class JobItem(Base):
    __tablename__ = "job_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    input_text: Mapped[str] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class DailyUsage(Base):
    __tablename__ = "daily_usage"
    __table_args__ = (UniqueConstraint("user_id", "usage_date", name="uq_daily_usage_user_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    usage_date: Mapped[date] = mapped_column(Date)
    transfer_count: Mapped[int] = mapped_column(Integer, default=0)
    share_count: Mapped[int] = mapped_column(Integer, default=0)
```

文件顶部的 `datetime` 导入旁增加 `date`。`sqlalchemy` 导入改为：

```python
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
```

`backend/alembic/env.py` 的模型导入改为：

```python
from app.models import DailyUsage, Job, JobItem, PanAccount, User  # noqa: F401
```

`backend/alembic/versions/003_jobs.py`：

```python
"""create jobs and daily usage

Revision ID: 003_jobs
Revises: 002_pan_accounts
Create Date: 2026-09-22
"""

from alembic import op
import sqlalchemy as sa

revision = "003_jobs"
down_revision = "002_pan_accounts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("pan_accounts.id"), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("directory", sa.String(length=1024), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_jobs_user_id", "jobs", ["user_id"])
    op.create_index("ix_jobs_account_id", "jobs", ["account_id"])
    op.create_table(
        "job_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_items_job_id", "job_items", ["job_id"])
    op.create_table(
        "daily_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("transfer_count", sa.Integer(), nullable=False),
        sa.Column("share_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("user_id", "usage_date", name="uq_daily_usage_user_day"),
    )
    op.create_index("ix_daily_usage_user_id", "daily_usage", ["user_id"])


def downgrade():
    op.drop_index("ix_daily_usage_user_id", table_name="daily_usage")
    op.drop_table("daily_usage")
    op.drop_index("ix_job_items_job_id", table_name="job_items")
    op.drop_table("job_items")
    op.drop_index("ix_jobs_account_id", table_name="jobs")
    op.drop_index("ix_jobs_user_id", table_name="jobs")
    op.drop_table("jobs")
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_jobs_model.py -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/models.py backend/alembic/env.py backend/alembic/versions/003_jobs.py backend/tests/test_jobs_model.py
git commit -m "$(cat <<'EOF'
feat: store transfer jobs and daily usage

EOF
)"
```

---

### Task 2: 解析分享链接

**Files:**
- Create: `backend/app/links.py`
- Test: `backend/tests/test_links.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_links.py
from app.links import parse_share_link, split_link_lines


def test_three_link_forms():
    query = parse_share_link("https://pan.baidu.com/s/1AbCdEf?pwd=ab12")
    labeled = parse_share_link("https://pan.baidu.com/s/1AbCdEf 提取码: cd34")
    spaced = parse_share_link("https://pan.baidu.com/s/1AbCdEf gh56")
    plain = parse_share_link("https://pan.baidu.com/s/1AbCdEf")
    assert (query.surl, query.password) == ("AbCdEf", "ab12")
    assert (labeled.surl, labeled.password) == ("AbCdEf", "cd34")
    assert (spaced.surl, spaced.password) == ("AbCdEf", "gh56")
    assert (plain.surl, plain.password) == ("AbCdEf", None)


def test_unparseable_link_is_none():
    assert parse_share_link("不是链接") is None
    assert parse_share_link("https://pan.baidu.com/disk/home") is None


def test_blank_lines_are_dropped():
    assert split_link_lines("  \nhttps://pan.baidu.com/s/1abc\n\n  第二行  ") == [
        "https://pan.baidu.com/s/1abc",
        "第二行",
    ]
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_links.py -v`

Expected: FAIL，`ModuleNotFoundError: app.links`

- [ ] **Step 3: 写解析器**

```python
# backend/app/links.py
import re
from dataclasses import dataclass

_SHARE = re.compile(r"https?://pan\.baidu\.com/s/1([0-9A-Za-z_-]+)")
_PWD_QUERY = re.compile(r"[?&]pwd=([0-9A-Za-z]{4})")
_PWD_LABEL = re.compile(r"提取码\s*[:：]\s*([0-9A-Za-z]{4})")
_PWD_TAIL = re.compile(r"\s+([0-9A-Za-z]{4})\s*$")


@dataclass(frozen=True)
class ParsedLink:
    surl: str
    password: str | None


def parse_share_link(text: str) -> ParsedLink | None:
    matched = _SHARE.search(text.strip())
    if matched is None:
        return None
    password = None
    for pattern in (_PWD_QUERY, _PWD_LABEL, _PWD_TAIL):
        found = pattern.search(text)
        if found is not None:
            password = found.group(1)
            break
    return ParsedLink(surl=matched.group(1), password=password)


def split_link_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]
```

`surl` 不含官方短链开头的 `1`。`https://pan.baidu.com/s/1AbCdEf` 的 `surl` 是 `AbCdEf`。

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_links.py -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/links.py backend/tests/test_links.py
git commit -m "$(cat <<'EOF'
feat: parse Baidu share links and extraction codes

EOF
)"
```

---

### Task 3: 转存额度

**Files:**
- Create: `backend/app/quota.py`
- Test: `backend/tests/test_quota.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_quota.py
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import DailyUsage, User
from app.quota import QuotaRejected, reserve_transfers, shanghai_today

SHANGHAI_NOON = datetime(2026, 9, 22, 4, 0, tzinfo=timezone.utc)  # 上海 12:00


def add_user(session, email, plan="free", expires=None, role="user"):
    user = User(email=email, password_hash="x", plan=plan, plan_expires_at=expires, role=role)
    session.add(user)
    session.flush()
    return user


def test_shanghai_day_crosses_utc_midnight():
    assert shanghai_today(datetime(2026, 9, 21, 16, 30, tzinfo=timezone.utc)) == shanghai_today(SHANGHAI_NOON)


def test_free_user_over_limit_keeps_usage(client):
    with client.app.state.session_factory() as session:
        user = add_user(session, "free@example.com")
        session.add(DailyUsage(user_id=user.id, usage_date=shanghai_today(SHANGHAI_NOON), transfer_count=100, share_count=0))
        session.commit()
        user_id = user.id
    with client.app.state.session_factory() as session:
        user = session.get(User, user_id)
        with pytest.raises(QuotaRejected) as caught:
            reserve_transfers(session, user, SHANGHAI_NOON, 1)
        assert caught.value.remaining == 0
        session.commit()
        usage = session.scalars(select(DailyUsage)).one()
        assert usage.transfer_count == 100


def test_paid_user_can_exceed_and_admin_is_not_counted(client):
    later = SHANGHAI_NOON + timedelta(days=2)
    with client.app.state.session_factory() as session:
        paid = add_user(session, "paid@example.com", plan="paid", expires=later)
        admin = add_user(session, "admin-quota@example.com", role="admin")
        reserve_transfers(session, paid, SHANGHAI_NOON, 101)
        reserve_transfers(session, admin, SHANGHAI_NOON, 50)
        session.commit()
        rows = session.scalars(select(DailyUsage)).all()
        assert len(rows) == 1
        assert rows[0].user_id == paid.id
        assert rows[0].transfer_count == 101


def test_expired_paid_user_is_free(client):
    expired = SHANGHAI_NOON - timedelta(minutes=1)
    with client.app.state.session_factory() as session:
        user = add_user(session, "expired@example.com", plan="paid", expires=expired)
        session.add(DailyUsage(user_id=user.id, usage_date=shanghai_today(SHANGHAI_NOON), transfer_count=100, share_count=0))
        session.commit()
        user_id = user.id
    with client.app.state.session_factory() as session:
        user = session.get(User, user_id)
        with pytest.raises(QuotaRejected) as caught:
            reserve_transfers(session, user, SHANGHAI_NOON, 1)
        assert caught.value.remaining == 0
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_quota.py -v`

Expected: FAIL，`ModuleNotFoundError: app.quota`

- [ ] **Step 3: 写额度**

```python
# backend/app/quota.py
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.membership import as_utc, effective_plan
from app.models import DailyUsage, User

TRANSFER_LIMIT = 100
SHANGHAI = ZoneInfo("Asia/Shanghai")


class QuotaRejected(Exception):
    def __init__(self, remaining: int) -> None:
        self.remaining = remaining
        super().__init__(f"今日还可转存 {remaining} 条")


def shanghai_today(now: datetime) -> date:
    current = as_utc(now)
    if current is None:
        raise ValueError("now is required")
    return current.astimezone(SHANGHAI).date()


def reserve_transfers(session: Session, user: User, now: datetime, count: int) -> None:
    if count < 1:
        raise ValueError("count must be positive")
    if user.role == "admin":
        return
    day = shanghai_today(now)
    usage = session.scalar(
        select(DailyUsage).where(DailyUsage.user_id == user.id, DailyUsage.usage_date == day)
    )
    used = 0 if usage is None else usage.transfer_count
    if effective_plan(user, now) == "free":
        remaining = max(TRANSFER_LIMIT - used, 0)
        if used + count > TRANSFER_LIMIT:
            raise QuotaRejected(remaining)
    if usage is None:
        usage = DailyUsage(user_id=user.id, usage_date=day, transfer_count=0, share_count=0)
        session.add(usage)
    usage.transfer_count += count
```

管理员在函数开头返回，不写用量。`effective_plan` 已经把到期用户算成 `free`。付费用户只累加，不因条数拒绝。

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_quota.py -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/quota.py backend/tests/test_quota.py
git commit -m "$(cat <<'EOF'
feat: cap free transfer batches by the Shanghai day

EOF
)"
```

---

### Task 4: 百度列目录和转存

**Files:**
- Modify: `backend/app/pans/errors.py`
- Modify: `backend/app/pans/baidu.py`
- Test: `backend/tests/test_baidu_transfer.py`

适配器新增两个动作。`list_dir` 给 API 用。`transfer_share` 只给 Worker 用。不要在适配器里重试，限流直接抛出。

百度约定，测试用夹具锁定，不访问外网：

- 列目录：`GET https://pan.baidu.com/rest/2.0/xpan/file`，参数 `method=list`、`dir`、`order=name`、`desc=0`、`start=0`、`limit=1000`、`folder=0`、`web=1`。`errno == 0` 时读 `list`。`errno` 为 `-9` 或 `-7` 抛 `PathNotFound`。`errno == -6` 抛 `LoginRejected`。
- 取 bdstoken：`GET https://pan.baidu.com/api/gettemplatevariable`，参数 `clienttype=0`、`app_id=250528`、`web=1`、`fields=["bdstoken"]`。成功时 `result.bdstoken` 是字符串。
- 校验提取码：`POST https://pan.baidu.com/share/verify`，查询参数 `surl`（不含开头的 `1`）、`channel=chunlei`、`web=1`、`app_id=250528`、`clienttype=0`、`bdstoken`。表单 `pwd`，没有提取码就传空字符串。`errno == 0` 且 `randsk` 非空才算通过。`errno` 为 `-9` 或 `-12` 抛 `WrongPassword`。`errno` 为 `2`、`105`、`110`、`111`、`115`、`116` 抛 `InvalidLink`。
- 分享根目录：`GET https://pan.baidu.com/share/list`，参数 `shorturl` 与上面的 `surl` 相同、`root=1`、`page` 从 1 开始、`num=100`、`web=1`、`channel=chunlei`、`app_id=250528`、`clienttype=0`。请求头 Cookie 在原 Cookie 后追加 `; BDCLND={randsk}`。收集每页的 `fs_id`。短页结束。最多 20 页，第 20 页仍满 100 条则抛 `TransferFailed`。同时记下第一条响应里的 `share_id` 和 `uk`。列表为空抛 `InvalidLink`。
- 转存：`POST https://pan.baidu.com/share/transfer`，查询参数 `shareid`、`from`（uk）、`sekey`（randsk 原文，交给 httpx 编码一次）、`ondup=fail`、`async=0`、`channel=chunlei`、`web=1`、`app_id=250528`、`clienttype=0`、`bdstoken`。表单 `fsidlist` 是 JSON 数组，例如 `[11,12]`，`path` 是目标目录。`errno == 0` 成功。`errno` 为 `-33` 或 `12` 抛 `DuplicateName`。
- `errno` 为 `31034` 或 `9019` 一律抛 `RateLimited`。`errno == -6` 一律抛 `LoginRejected`。其余非 0 抛 `TransferFailed`。
- 非 200、非 JSON、网络错误：列目录抛 `PathNotFound` 以外的 `TransferFailed`；登录类接口在无法解析时抛 `TransferFailed`。不要把 Cookie 写进异常或日志。
- 调用 `client.get` / `client.post` 时，如果 URL 自己不带查询串，用 `params=` 传递。不要对已经带查询串的 URL 再传 `params={}`，空字典会清掉原查询串。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_baidu_transfer.py
import json

import httpx
import pytest

from app.pans.baidu import BaiduAdapter
from app.pans.errors import DuplicateName, InvalidLink, LoginRejected, PathNotFound, RateLimited, WrongPassword

COOKIE = "BDUSS=super-secret-cookie-value"


def scripted(replies: list[tuple[str, dict]]):
    calls = {"n": 0, "urls": []}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["urls"].append(str(request.url))
        assert COOKIE not in str(request.url)
        kind, payload = replies[calls["n"]]
        calls["n"] += 1
        assert kind in str(request.url)
        if kind == "share/verify":
            assert request.url.params["surl"] == "AbCdEf"
            assert COOKIE in request.headers["cookie"]
        if kind == "share/list":
            assert "BDCLND=rand-sk" in request.headers["cookie"]
        if kind == "share/transfer":
            assert request.url.params["ondup"] == "fail"
            assert json.loads(request.content.decode().split("fsidlist=")[1].split("&")[0]) == [11, 12]
        return httpx.Response(200, json=payload)

    return calls, httpx.Client(transport=httpx.MockTransport(handler))


def test_list_dir_returns_current_level():
    calls, client = scripted([
        ("xpan/file", {"errno": 0, "list": [
            {"server_filename": "片子", "path": "/片子", "isdir": 1},
            {"server_filename": "说明.txt", "path": "/说明.txt", "isdir": 0},
        ]}),
    ])
    entries = BaiduAdapter(client).list_dir(COOKIE, "/")
    assert [(item.name, item.path, item.is_dir) for item in entries] == [
        ("片子", "/片子", True),
        ("说明.txt", "/说明.txt", False),
    ]
    assert calls["n"] == 1


def test_missing_directory_and_bad_login():
    _, missing = scripted([("xpan/file", {"errno": -9})])
    with pytest.raises(PathNotFound):
        BaiduAdapter(missing).list_dir(COOKIE, "/没有")
    _, signed_out = scripted([("xpan/file", {"errno": -6})])
    with pytest.raises(LoginRejected):
        BaiduAdapter(signed_out).list_dir(COOKIE, "/没有")


def test_transfer_saves_every_root_entry():
    calls, client = scripted([
        ("gettemplatevariable", {"errno": 0, "result": {"bdstoken": "bd-token"}}),
        ("share/verify", {"errno": 0, "randsk": "rand-sk"}),
        ("share/list", {"errno": 0, "share_id": 9, "uk": 8, "list": [
            {"fs_id": 11}, {"fs_id": 12},
        ]}),
        ("share/transfer", {"errno": 0}),
    ])
    BaiduAdapter(client).transfer_share(COOKIE, "AbCdEf", "ab12", "/来自转存")
    assert calls["n"] == 4
    assert all(COOKIE not in url for url in calls["urls"])


def test_transfer_error_mapping():
    def once(kind, payload, exc):
        _, client = scripted([
            ("gettemplatevariable", {"errno": 0, "result": {"bdstoken": "bd-token"}}),
            (kind, payload),
        ])
        with pytest.raises(exc):
            BaiduAdapter(client).transfer_share(COOKIE, "AbCdEf", "ab12", "/来自转存")

    once("share/verify", {"errno": -12}, WrongPassword)
    once("share/verify", {"errno": 116}, InvalidLink)
    once("share/verify", {"errno": 31034}, RateLimited)
    _, client = scripted([
        ("gettemplatevariable", {"errno": 0, "result": {"bdstoken": "bd-token"}}),
        ("share/verify", {"errno": 0, "randsk": "rand-sk"}),
        ("share/list", {"errno": 0, "share_id": 9, "uk": 8, "list": [{"fs_id": 11}, {"fs_id": 12}]}),
        ("share/transfer", {"errno": -33}),
    ])
    with pytest.raises(DuplicateName):
        BaiduAdapter(client).transfer_share(COOKIE, "AbCdEf", None, "/来自转存")
```

`fsidlist` 断言如果因为表单编码失败，就改成读取 `request.content` 里解码后的正文，并断言它包含 `[11,12]` 或 `[11, 12]`。不要为了迁就断言去改百度要求的 JSON 数组格式。

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_baidu_transfer.py -v`

Expected: FAIL，`list_dir` 不存在，或异常类不存在。

- [ ] **Step 3: 写异常和适配器**

`backend/app/pans/errors.py` 追加：

```python
class PathNotFound(Exception):
    pass


class WrongPassword(Exception):
    pass


class InvalidLink(Exception):
    pass


class DuplicateName(Exception):
    pass


class RateLimited(Exception):
    pass


class TransferFailed(Exception):
    pass
```

`backend/app/pans/baidu.py` 在现有 `verify_login` 之后追加。保留原来的 `verify_login` 和 `USER_AGENT` 不动。

```python
import json
from dataclasses import dataclass

from app.pans.errors import (
    DuplicateName,
    InvalidLink,
    LoginRejected,
    PathNotFound,
    RateLimited,
    TransferFailed,
)

LIST_URL = "https://pan.baidu.com/rest/2.0/xpan/file"
TOKEN_URL = "https://pan.baidu.com/api/gettemplatevariable"
VERIFY_URL = "https://pan.baidu.com/share/verify"
SHARE_LIST_URL = "https://pan.baidu.com/share/list"
TRANSFER_URL = "https://pan.baidu.com/share/transfer"
RATE_LIMIT = {31034, 9019}
BAD_PASSWORD = {-9, -12}
BAD_LINK = {2, 105, 110, 111, 115, 116}
MISSING_DIR = {-9, -7}
DUPLICATE = {-33, 12}


@dataclass(frozen=True)
class DirEntry:
    name: str
    path: str
    is_dir: bool


def _payload(response: httpx.Response) -> dict:
    if response.status_code != 200:
        raise TransferFailed()
    try:
        data = response.json()
    except Exception as exc:
        raise TransferFailed() from exc
    if not isinstance(data, dict):
        raise TransferFailed()
    return data


def _raise_common(errno: object) -> None:
    if errno in RATE_LIMIT:
        raise RateLimited()
    if errno == -6:
        raise LoginRejected()


class BaiduAdapter:
    # 保留已有 __init__ 和 verify_login
    def _headers(self, cookie: str) -> dict[str, str]:
        return {"Cookie": cookie, "User-Agent": USER_AGENT}

    def _get(self, url: str, params: dict, cookie: str) -> dict:
        try:
            response = self.client.get(url, params=params, headers=self._headers(cookie), timeout=15, follow_redirects=False)
        except TransferFailed:
            raise
        except Exception as exc:
            raise TransferFailed() from exc
        return _payload(response)

    def _post(self, url: str, params: dict, data: dict, cookie: str) -> dict:
        try:
            response = self.client.post(
                url,
                params=params,
                data=data,
                headers={**self._headers(cookie), "Content-Type": "application/x-www-form-urlencoded"},
                timeout=20,
                follow_redirects=False,
            )
        except TransferFailed:
            raise
        except Exception as exc:
            raise TransferFailed() from exc
        return _payload(response)

    def list_dir(self, cookie: str, directory: str) -> list[DirEntry]:
        try:
            payload = self._get(
                LIST_URL,
                {"method": "list", "dir": directory, "order": "name", "desc": 0, "start": 0, "limit": 1000, "folder": 0, "web": 1},
                cookie,
            )
        except TransferFailed as exc:
            raise PathNotFound() from exc
        errno = payload.get("errno")
        _raise_common(errno)
        if errno in MISSING_DIR:
            raise PathNotFound()
        if errno != 0:
            raise PathNotFound()
        entries: list[DirEntry] = []
        for item in payload.get("list") or []:
            if not isinstance(item, dict):
                continue
            name = item.get("server_filename")
            path = item.get("path")
            if not isinstance(name, str) or not isinstance(path, str):
                continue
            entries.append(DirEntry(name=name, path=path, is_dir=item.get("isdir") == 1))
        return entries

    def transfer_share(self, cookie: str, surl: str, password: str | None, directory: str) -> None:
        token_payload = self._get(
            TOKEN_URL,
            {"clienttype": 0, "app_id": 250528, "web": 1, "fields": '["bdstoken"]'},
            cookie,
        )
        _raise_common(token_payload.get("errno"))
        if token_payload.get("errno") != 0:
            raise TransferFailed()
        result = token_payload.get("result")
        bdstoken = result.get("bdstoken") if isinstance(result, dict) else None
        if not isinstance(bdstoken, str):
            raise TransferFailed()
        verified = self._post(
            VERIFY_URL,
            {"surl": surl, "channel": "chunlei", "web": 1, "app_id": 250528, "clienttype": 0, "bdstoken": bdstoken},
            {"pwd": password or ""},
            cookie,
        )
        errno = verified.get("errno")
        _raise_common(errno)
        if errno in BAD_PASSWORD:
            raise WrongPassword()
        if errno in BAD_LINK:
            raise InvalidLink()
        randsk = verified.get("randsk")
        if errno != 0 or not isinstance(randsk, str) or not randsk:
            raise InvalidLink()
        fsids: list[int] = []
        share_id = None
        uk = None
        for page in range(1, 21):
            listed = self._get(
                SHARE_LIST_URL,
                {
                    "shorturl": surl,
                    "root": 1,
                    "page": page,
                    "num": 100,
                    "web": 1,
                    "channel": "chunlei",
                    "app_id": 250528,
                    "clienttype": 0,
                },
                cookie + "; BDCLND=" + randsk,
            )
            _raise_common(listed.get("errno"))
            if listed.get("errno") in BAD_LINK or listed.get("errno") != 0:
                raise InvalidLink()
            if share_id is None:
                share_id = listed.get("share_id")
                uk = listed.get("uk")
            page_items = listed.get("list") or []
            if not isinstance(page_items, list):
                raise TransferFailed()
            for item in page_items:
                if isinstance(item, dict) and isinstance(item.get("fs_id"), int):
                    fsids.append(item["fs_id"])
            if len(page_items) < 100:
                break
        else:
            raise TransferFailed()
        if not fsids or not isinstance(share_id, int) or not isinstance(uk, int):
            raise InvalidLink()
        saved = self._post(
            TRANSFER_URL,
            {
                "shareid": share_id,
                "from": uk,
                "sekey": randsk,
                "ondup": "fail",
                "async": 0,
                "channel": "chunlei",
                "web": 1,
                "app_id": 250528,
                "clienttype": 0,
                "bdstoken": bdstoken,
            },
            {"fsidlist": json.dumps(fsids), "path": directory},
            cookie,
        )
        errno = saved.get("errno")
        _raise_common(errno)
        if errno in DUPLICATE:
            raise DuplicateName()
        if errno != 0:
            raise TransferFailed()
```

不要把这个类写第二遍。把方法合并进现有的 `BaiduAdapter`。`_raise_common` 在 errno 不是限流或登录失效时什么都不做。

`list_dir` 把网络错误收成 `PathNotFound`，这样提交阶段会返回「目标目录不存在」，而不是 500。登录失效仍然是 `LoginRejected`。

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_baidu_transfer.py tests/test_accounts.py -q`

Expected: PASS。原有核对登录测试仍然通过。

- [ ] **Step 5: 提交**

```bash
git add backend/app/pans/errors.py backend/app/pans/baidu.py backend/tests/test_baidu_transfer.py
git commit -m "$(cat <<'EOF'
feat: list a Baidu directory and transfer a share

EOF
)"
```

---

### Task 5: 入队和执行转存

**Files:**
- Create: `backend/app/transfers.py`
- Create: `backend/app/worker.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/main.py`
- Create: `backend/app/routers/transfers.py`
- Test: `backend/tests/test_transfers.py`

`create_transfer` 在同一个数据库会话里检查目录、占额度、写任务。目录检查失败或额度失败时调用方回滚，不能留下任务。

`execute_job` 由测试和 Worker 调用。它不 `sleep` 真实时间，延迟通过参数 `sleeper` 注入。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_transfers.py
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.crypto import encrypt_cookie
from app.models import DailyUsage, Job, JobItem, PanAccount, User
from app.quota import shanghai_today
from app.transfers import execute_job, reclaim_stale

KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
COOKIE = "BDUSS=super-secret-cookie-value"
NOW = datetime(2026, 9, 22, 4, 0, tzinfo=timezone.utc)


def register(client, email="user@example.com"):
    response = client.post("/api/auth/register", json={"email": email, "password": "password-123"})
    assert response.status_code == 201
    return response


def bind(client, cookie=COOKIE):
    with client.app.state.session_factory() as session:
        user = session.scalars(select(User).where(User.email == "user@example.com")).one()
        account = PanAccount(
            user_id=user.id,
            provider="baidu",
            nickname="网盘昵称",
            cookie_ciphertext=encrypt_cookie(cookie, KEY),
            status="valid",
        )
        session.add(account)
        session.commit()
        return account.id


def install(client, handler):
    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))


def list_ok(request: httpx.Request) -> httpx.Response:
    if "xpan/file" in str(request.url):
        return httpx.Response(200, json={"errno": 0, "list": []})
    raise AssertionError(request.url)


def test_free_limit_does_not_create_a_job(client):
    register(client)
    account_id = bind(client)
    install(client, list_ok)
    with client.app.state.session_factory() as session:
        user = session.scalars(select(User).where(User.email == "user@example.com")).one()
        session.add(DailyUsage(user_id=user.id, usage_date=shanghai_today(NOW), transfer_count=100, share_count=0))
        session.commit()
    response = client.post("/api/transfers", json={
        "account_id": account_id,
        "directory": "/来自转存",
        "links": "https://pan.baidu.com/s/1AbCdEf ab12",
        "now": "2026-09-22T04:00:00+00:00",
    })
    assert response.status_code == 422
    assert response.json()["detail"] == "今日还可转存 0 条"
    assert COOKIE not in response.text
    with client.app.state.session_factory() as session:
        assert session.scalars(select(Job)).first() is None
        assert session.scalars(select(DailyUsage)).one().transfer_count == 100


def test_missing_directory_does_not_spend_quota(client):
    register(client)
    account_id = bind(client)

    def handler(request: httpx.Request) -> httpx.Response:
        assert "share/transfer" not in str(request.url)
        return httpx.Response(200, json={"errno": -9})

    install(client, handler)
    response = client.post("/api/transfers", json={
        "account_id": account_id,
        "directory": "/没有",
        "links": "https://pan.baidu.com/s/1AbCdEf",
    })
    assert response.status_code == 422
    assert response.json()["detail"] == "目标目录不存在"
    with client.app.state.session_factory() as session:
        assert session.scalars(select(Job)).first() is None
        assert session.scalars(select(DailyUsage)).first() is None


def test_job_runs_partial_and_hides_cookie(client):
    register(client)
    account_id = bind(client)
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        assert COOKIE not in url
        if "xpan/file" in url:
            return httpx.Response(200, json={"errno": 0, "list": []})
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        if "share/verify" in url:
            state["n"] += 1
            errno = 0 if state["n"] == 1 else -12
            return httpx.Response(200, json={"errno": errno, "randsk": "rand-sk"})
        if "share/list" in url:
            return httpx.Response(200, json={"errno": 0, "share_id": 9, "uk": 8, "list": [{"fs_id": 11}]})
        if "share/transfer" in url:
            return httpx.Response(200, json={"errno": 0})
        raise AssertionError(url)

    install(client, handler)
    created = client.post("/api/transfers", json={
        "account_id": account_id,
        "directory": "/来自转存",
        "links": "https://pan.baidu.com/s/1AbCdEf ab12\n\n不是链接\nhttps://pan.baidu.com/s/1ZzYyXx cd34",
    })
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "pending"
    assert COOKIE not in created.text
    job_id = body["id"]
    with client.app.state.session_factory() as session:
        job = session.get(Job, job_id)
        execute_job(session, client.app.state.pan_http_client, job, sleeper=lambda _seconds: None, now=NOW)
        session.commit()
    shown = client.get(f"/api/jobs/{job_id}")
    assert shown.status_code == 200
    assert shown.json()["status"] == "partial"
    reasons = [item["error"] for item in shown.json()["items"]]
    assert reasons == [None, "链接无法解析", "提取码错误"]
    assert shown.json()["items"][0]["result"] == "已转存"
    assert COOKIE not in shown.text


def test_expired_cookie_stops_later_items(client):
    register(client)
    account_id = bind(client)
    calls = {"transfer": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "xpan/file" in url:
            return httpx.Response(200, json={"errno": 0, "list": []})
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": -6})
        calls["transfer"] += 1
        raise AssertionError(url)

    install(client, handler)
    created = client.post("/api/transfers", json={
        "account_id": account_id,
        "directory": "/",
        "links": "https://pan.baidu.com/s/1AbCdEf\nhttps://pan.baidu.com/s/1ZzYyXx",
    })
    job_id = created.json()["id"]
    with client.app.state.session_factory() as session:
        execute_job(session, client.app.state.pan_http_client, session.get(Job, job_id), sleeper=lambda _seconds: None, now=NOW)
        session.commit()
        account = session.get(PanAccount, account_id)
        items = session.scalars(select(JobItem).where(JobItem.job_id == job_id).order_by(JobItem.id)).all()
        assert account.status == "expired"
        assert [item.error for item in items] == ["登录已失效，请重新登录", "登录已失效，请重新登录"]
        assert calls["transfer"] == 0


def test_rate_limit_retries_then_succeeds(client):
    register(client)
    account_id = bind(client)
    waits = []
    verify_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "xpan/file" in url:
            return httpx.Response(200, json={"errno": 0, "list": []})
        if "gettemplatevariable" in url:
            return httpx.Response(200, json={"errno": 0, "result": {"bdstoken": "bd-token"}})
        if "share/verify" in url:
            verify_calls["n"] += 1
            errno = 31034 if verify_calls["n"] < 3 else 0
            return httpx.Response(200, json={"errno": errno, "randsk": "rand-sk"})
        if "share/list" in url:
            return httpx.Response(200, json={"errno": 0, "share_id": 9, "uk": 8, "list": [{"fs_id": 11}]})
        if "share/transfer" in url:
            return httpx.Response(200, json={"errno": 0})
        raise AssertionError(url)

    install(client, handler)
    created = client.post("/api/transfers", json={
        "account_id": account_id,
        "directory": "/",
        "links": "https://pan.baidu.com/s/1AbCdEf",
    })
    job_id = created.json()["id"]
    with client.app.state.session_factory() as session:
        execute_job(
            session,
            client.app.state.pan_http_client,
            session.get(Job, job_id),
            sleeper=waits.append,
            now=NOW,
        )
        session.commit()
        item = session.scalars(select(JobItem)).one()
        assert waits == [2, 8]
        assert item.attempts == 3
        assert item.status == "succeeded"


def test_stale_running_item_is_requeued_until_attempt_cap(client):
    register(client)
    account_id = bind(client)
    old = NOW - timedelta(minutes=16)
    with client.app.state.session_factory() as session:
        user = session.scalars(select(User).where(User.email == "user@example.com")).one()
        job = Job(user_id=user.id, account_id=account_id, type="transfer", directory="/", status="running", updated_at=old)
        session.add(job)
        session.flush()
        session.add(JobItem(job_id=job.id, input_text="https://pan.baidu.com/s/1AbCdEf", status="running", attempts=1, updated_at=old))
        session.add(JobItem(job_id=job.id, input_text="https://pan.baidu.com/s/1ZzYyXx", status="running", attempts=3, updated_at=old))
        session.commit()
        job_id = job.id
    with client.app.state.session_factory() as session:
        reclaim_stale(session, NOW)
        session.commit()
        items = session.scalars(select(JobItem).where(JobItem.job_id == job_id).order_by(JobItem.id)).all()
        assert items[0].status == "pending"
        assert items[1].status == "failed"
        assert items[1].error == "已达到重试上限"
        assert session.get(Job, job_id).status == "pending"
```

提交接口接受可选字段 `now`，只在测试里传入固定时间。生产请求不传，接口用 `now_utc()`。不要把 `now` 写进响应。

根目录 `/` 不调用列目录。`test_expired_cookie_stops_later_items` 和限流测试使用 `directory: "/"`，因此 handler 不必实现 `xpan/file`，除非实现仍然请求了它。实现必须对 `/` 跳过列目录。如果测试 handler 收到了 `xpan/file`，那是实现错误。

`test_job_runs_partial_and_hides_cookie` 的目录不是 `/`，所以会先列目录。

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_transfers.py -v`

Expected: FAIL，路由 404 或 `execute_job` 不存在。

- [ ] **Step 3: 写队列、路由和 Worker**

`backend/app/schemas.py` 追加：

```python
class TransferIn(BaseModel):
    account_id: int
    directory: str = Field(min_length=1, max_length=1024)
    links: str = Field(min_length=1, max_length=20000)
    now: datetime | None = None


class JobItemOut(BaseModel):
    id: int
    status: str
    input_text: str
    error: str | None
    result: str | None
    attempts: int


class JobOut(BaseModel):
    id: int
    status: str
    directory: str
    items: list[JobItemOut]
```

`backend/app/transfers.py`：

```python
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import decrypt_cookie
from app.links import parse_share_link
from app.models import Job, JobItem, PanAccount
from app.pans.baidu import BaiduAdapter
from app.pans.errors import (
    DuplicateName,
    InvalidLink,
    LoginRejected,
    RateLimited,
    TransferFailed,
    WrongPassword,
)

RETRY_DELAYS = (2, 8, 20)
EXPIRED = "登录已失效，请重新登录"


def normalize_directory(directory: str) -> str:
    cleaned = directory.strip()
    if not cleaned.startswith("/") or ".." in cleaned.split("/"):
        raise ValueError("目标目录无效")
    return cleaned


def finish_job(job: Job, items: list[JobItem], now: datetime) -> None:
    statuses = {item.status for item in items}
    if statuses == {"succeeded"}:
        job.status = "succeeded"
    elif "succeeded" in statuses:
        job.status = "partial"
    else:
        job.status = "failed"
    job.updated_at = now


def fail_remaining(items: list[JobItem], start: int, now: datetime) -> None:
    for item in items[start:]:
        if item.status == "pending":
            item.status = "failed"
            item.error = EXPIRED
            item.updated_at = now


def run_item(adapter: BaiduAdapter, item: JobItem, account: PanAccount, directory: str, cookie: str, sleeper: Callable[[float], None], now: datetime) -> str:
    parsed = parse_share_link(item.input_text)
    if parsed is None:
        item.status = "failed"
        item.error = "链接无法解析"
        item.updated_at = now
        return "failed"
    while item.attempts < 3:
        item.attempts += 1
        item.status = "running"
        item.updated_at = now
        try:
            adapter.transfer_share(cookie, parsed.surl, parsed.password, directory)
        except RateLimited:
            if item.attempts >= 3:
                item.status = "failed"
                item.error = "转存失败"
                item.updated_at = now
                return "failed"
            sleeper(RETRY_DELAYS[item.attempts - 1])
            continue
        except LoginRejected:
            account.status = "expired"
            account.updated_at = now
            item.status = "failed"
            item.error = EXPIRED
            item.updated_at = now
            return "expired"
        except WrongPassword:
            item.status = "failed"
            item.error = "提取码错误"
            item.updated_at = now
            return "failed"
        except InvalidLink:
            item.status = "failed"
            item.error = "链接无效"
            item.updated_at = now
            return "failed"
        except DuplicateName:
            item.status = "failed"
            item.error = "目标目录已有同名文件"
            item.updated_at = now
            return "failed"
        except TransferFailed:
            item.status = "failed"
            item.error = "转存失败"
            item.updated_at = now
            return "failed"
        item.status = "succeeded"
        item.result = "已转存"
        item.error = None
        item.updated_at = now
        return "succeeded"
    item.status = "failed"
    item.error = "转存失败"
    item.updated_at = now
    return "failed"


def execute_job(session: Session, client, job: Job, sleeper: Callable[[float], None], now: datetime) -> None:
    from app.config import get_settings

    job.status = "running"
    job.updated_at = now
    account = session.get(PanAccount, job.account_id)
    items = session.scalars(select(JobItem).where(JobItem.job_id == job.id).order_by(JobItem.id)).all()
    if account is None or account.status != "valid":
        fail_remaining(items, 0, now)
        finish_job(job, items, now)
        return
    cookie = decrypt_cookie(account.cookie_ciphertext, get_settings().cookie_fernet_key)
    adapter = BaiduAdapter(client)
    for index, item in enumerate(items):
        if item.status != "pending":
            continue
        outcome = run_item(adapter, item, account, job.directory, cookie, sleeper, now)
        if outcome == "expired":
            fail_remaining(items, index + 1, now)
            break
    finish_job(job, items, now)


def reclaim_stale(session: Session, now: datetime) -> None:
    cutoff = now - timedelta(minutes=15)
    jobs = session.scalars(select(Job).where(Job.type == "transfer", Job.status == "running")).all()
    for job in jobs:
        items = session.scalars(select(JobItem).where(JobItem.job_id == job.id)).all()
        for item in items:
            updated = item.updated_at
            if item.status != "running":
                continue
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=now.tzinfo)
            if updated >= cutoff:
                continue
            if item.attempts >= 3:
                item.status = "failed"
                item.error = "已达到重试上限"
            else:
                item.status = "pending"
            item.updated_at = now
        if any(item.status == "running" for item in items):
            continue
        if any(item.status == "pending" for item in items):
            job.status = "pending"
        else:
            finish_job(job, items, now)
        job.updated_at = now
```

条目在路由里创建。`transfers.py` 只负责校验目录、执行和回收。

`backend/app/routers/transfers.py`：

```python
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import decrypt_cookie
from app.deps import get_current_user, get_db, now_utc
from app.links import parse_share_link, split_link_lines
from app.models import Job, JobItem, PanAccount, User
from app.pans.baidu import BaiduAdapter
from app.pans.errors import LoginRejected, PathNotFound
from app.quota import QuotaRejected, reserve_transfers
from app.schemas import DirEntryOut, JobItemOut, JobOut, TransferIn
from app.transfers import normalize_directory

router = APIRouter(tags=["transfers"])


def pan_client(request: Request) -> httpx.Client:
    existing = getattr(request.app.state, "pan_http_client", None)
    if existing is not None:
        return existing
    client = httpx.Client()
    request.app.state.pan_http_client = client
    return client


def owned_baidu(session: Session, user: User, account_id: int) -> PanAccount:
    account = session.scalar(select(PanAccount).where(PanAccount.id == account_id, PanAccount.user_id == user.id))
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    if account.provider != "baidu":
        raise HTTPException(status_code=422, detail="暂未开放")
    if account.status != "valid":
        raise HTTPException(status_code=422, detail="请重新登录百度")
    return account


def to_job(job: Job, items: list[JobItem]) -> JobOut:
    return JobOut(
        id=job.id,
        status=job.status,
        directory=job.directory,
        items=[
            JobItemOut(
                id=item.id,
                status=item.status,
                input_text=item.input_text,
                error=item.error,
                result=item.result,
                attempts=item.attempts,
            )
            for item in items
        ],
    )


@router.get("/api/accounts/{account_id}/files", response_model=list[DirEntryOut])
def list_files(
    account_id: int,
    request: Request,
    dir: str = "/",
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    account = owned_baidu(session, user, account_id)
    try:
        directory = normalize_directory(dir)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="目标目录无效") from exc
    from app.config import get_settings

    cookie = decrypt_cookie(account.cookie_ciphertext, get_settings().cookie_fernet_key)
    try:
        entries = BaiduAdapter(pan_client(request)).list_dir(cookie, directory)
    except LoginRejected as exc:
        account.status = "expired"
        account.updated_at = now_utc()
        session.commit()
        raise HTTPException(status_code=422, detail="请重新登录百度") from exc
    except PathNotFound as exc:
        raise HTTPException(status_code=422, detail="目标目录不存在") from exc
    return [DirEntryOut(name=entry.name, path=entry.path, is_dir=entry.is_dir) for entry in entries]


@router.post("/api/transfers", response_model=JobOut, status_code=201)
def create_transfer(
    body: TransferIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    account = owned_baidu(session, user, body.account_id)
    try:
        directory = normalize_directory(body.directory)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    lines = split_link_lines(body.links)
    if not lines:
        raise HTTPException(status_code=422, detail="请粘贴分享链接")
    moment = body.now or now_utc()
    if directory != "/":
        from app.config import get_settings

        cookie = decrypt_cookie(account.cookie_ciphertext, get_settings().cookie_fernet_key)
        try:
            BaiduAdapter(pan_client(request)).list_dir(cookie, directory)
        except LoginRejected as exc:
            account.status = "expired"
            account.updated_at = moment
            session.commit()
            raise HTTPException(status_code=422, detail="请重新登录百度") from exc
        except PathNotFound as exc:
            raise HTTPException(status_code=422, detail="目标目录不存在") from exc
    try:
        reserve_transfers(session, user, moment, len(lines))
    except QuotaRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    job = Job(
        user_id=user.id,
        account_id=account.id,
        type="transfer",
        status="pending",
        directory=directory,
        created_at=moment,
        updated_at=moment,
    )
    session.add(job)
    session.flush()
    items: list[JobItem] = []
    for line in lines:
        parsed = parse_share_link(line)
        item = JobItem(
            job_id=job.id,
            input_text=line,
            status="failed" if parsed is None else "pending",
            error="链接无法解析" if parsed is None else None,
            attempts=0,
            created_at=moment,
            updated_at=moment,
        )
        session.add(item)
        items.append(item)
    session.commit()
    return to_job(job, items)


@router.get("/api/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    job = session.scalar(select(Job).where(Job.id == job_id, Job.user_id == user.id))
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    items = session.scalars(select(JobItem).where(JobItem.job_id == job.id).order_by(JobItem.id)).all()
    return to_job(job, items)
```

`schemas.py` 还要有：

```python
class DirEntryOut(BaseModel):
    name: str
    path: str
    is_dir: bool
```

`backend/app/main.py` 导入并 `app.include_router(transfers.router)`。

`backend/app/worker.py`：

```python
import time

from app.bootstrap import ensure_admin
from app.config import get_settings
from app.db import make_engine, make_session_factory
from app.deps import now_utc
from app.models import Job
from app.transfers import execute_job, reclaim_stale
from sqlalchemy import select
import httpx


def run_once(session_factory, client: httpx.Client) -> bool:
    now = now_utc()
    with session_factory() as session:
        reclaim_stale(session, now)
        running = session.scalar(select(Job).where(Job.type == "transfer", Job.status == "running"))
        if running is not None:
            session.commit()
            return False
        job = session.scalar(select(Job).where(Job.type == "transfer", Job.status == "pending").order_by(Job.id))
        if job is None:
            session.commit()
            return False
        execute_job(session, client, job, sleeper=time.sleep, now=now)
        session.commit()
        return True


def main() -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        ensure_admin(session, settings)
    client = httpx.Client()
    try:
        while True:
            worked = run_once(session_factory, client)
            if not worked:
                time.sleep(2)
    finally:
        client.close()


if __name__ == "__main__":
    main()
```

`python -m app.worker` 不会自动调用 `main`。文件末尾改成模块导入时不跑循环。在 `if __name__` 之外再加：

```python
def _entry() -> None:
    main()
```

并在 `backend/pyproject.toml` 的项目配置里增加脚本不是必须的。`python -m app.worker` 只在 `app/worker.py` 被当作 `__main__` 时执行 `main()`。这满足 Compose 命令 `python -m app.worker`。确认 `app/__init__.py` 存在；如果包没有 `__init__.py`，现有 `python -m` 测试已经能导入 `app`，保持原样即可。

`reclaim_stale` 在条目的 `updated_at` 来自 SQLite 时可能是 naive datetime。测试写入的 `old` 带时区。比较前把 naive 时间当作 UTC。

额度测试传入 `now`。`TransferIn.now` 是可选 datetime。生产页面不传这个字段。

 guest 访问 `POST /api/transfers` 应返回 401 `未登录`。本任务的测试没有覆盖它也可以，不要为了额外测试去改已通过的断言。

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_transfers.py tests/test_quota.py tests/test_baidu_transfer.py -q`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/transfers.py backend/app/worker.py backend/app/schemas.py backend/app/main.py backend/app/routers/transfers.py backend/tests/test_transfers.py
git commit -m "$(cat <<'EOF'
feat: queue Baidu transfers and run them in a worker

EOF
)"
```

---

### Task 6: 转存页面

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/pages/HomePage.tsx`
- Create: `frontend/src/pages/TransferPage.tsx`
- Create: `frontend/src/pages/JobPage.tsx`
- Modify: `docker-compose.yml`

- [ ] **Step 1: 写页面**

`frontend/src/api.ts` 增加类型和方法：

```typescript
export type DirEntry = { name: string; path: string; is_dir: boolean };
export type JobItem = {
  id: number;
  status: string;
  input_text: string;
  error: string | null;
  result: string | null;
  attempts: number;
};
export type Job = { id: number; status: string; directory: string; items: JobItem[] };
```

`api` 对象增加：

```typescript
  files: (accountId: number, dir: string) =>
    request<DirEntry[]>(`/api/accounts/${accountId}/files?dir=${encodeURIComponent(dir)}`),
  createTransfer: (accountId: number, directory: string, links: string) =>
    request<Job>("/api/transfers", {
      method: "POST",
      body: JSON.stringify({ account_id: accountId, directory, links }),
    }),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
```

`AppShell` 的导航在「网盘账号」后面增加：

```tsx
<NavLink to="/transfer" className={({ isActive }) => navClass(isActive)}>
  批量转存
</NavLink>
```

`App.tsx` 增加路由 `/transfer` 和 `/jobs/:id`。都要求 `user` 存在，否则 `<Navigate to="/login" />`，外层用 `AppShell`。

```tsx
<Route
  path="/transfer"
  element={
    user ? (
      <AppShell user={user} onLogout={onLogout}>
        <TransferPage />
      </AppShell>
    ) : (
      <Navigate to="/login" />
    )
  }
/>
<Route
  path="/jobs/:id"
  element={
    user ? (
      <AppShell user={user} onLogout={onLogout}>
        <JobPage />
      </AppShell>
    ) : (
      <Navigate to="/login" />
    )
  }
/>
```

`HomePage.tsx` 把三张占位卡片拆开。第一张是链接到 `/transfer` 的「批量转存」，说明写「把分享链接保存到自己的目录」。后两张仍是虚线卡片，文案仍是「即将开放」。

`frontend/src/pages/TransferPage.tsx`：

```tsx
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type DirEntry, type PanAccount } from "../api";

export default function TransferPage() {
  const navigate = useNavigate();
  const [accounts, setAccounts] = useState<PanAccount[]>([]);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [directory, setDirectory] = useState("/");
  const [entries, setEntries] = useState<DirEntry[]>([]);
  const [links, setLinks] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    api.accounts().then((rows) => {
      const baidu = rows.filter((row) => row.provider === "baidu" && row.status === "valid");
      setAccounts(baidu);
      setAccountId(baidu[0]?.id ?? null);
    }).catch((caught: Error) => setError(caught.message));
  }, []);

  useEffect(() => {
    if (accountId === null) return;
    api.files(accountId, directory).then(setEntries).catch((caught: Error) => setError(caught.message));
  }, [accountId, directory]);

  async function submit() {
    if (accountId === null) return;
    setPending(true);
    setError("");
    try {
      const job = await api.createTransfer(accountId, directory, links);
      navigate(`/jobs/${job.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "转存失败");
    } finally {
      setPending(false);
    }
  }

  const parent = directory === "/" ? null : directory.slice(0, directory.lastIndexOf("/")) || "/";

  return (
    <div className="mx-auto max-w-3xl">
      <p className="text-sm font-medium text-primary-dark">转存</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">批量转存</h1>
      <p className="mt-2 text-sm leading-6 text-ink/65">选择百度账号和目录，每行粘贴一条分享链接。一条失败不会停下其余链接。</p>
      {accounts.length === 0 ? <p className="mt-6 text-sm text-ink/60">先绑定一个有效的百度账号。</p> : null}
      {accounts.length > 0 ? (
        <div className="mt-6 space-y-4">
          <label className="block text-sm font-medium">
            百度账号
            <select
              className="mt-2 w-full rounded-2xl border border-line bg-white px-4 py-3"
              value={accountId ?? ""}
              onChange={(event) => {
                setDirectory("/");
                setAccountId(Number(event.target.value));
              }}
            >
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>{account.nickname}</option>
              ))}
            </select>
          </label>
          <section className="rounded-3xl border border-line bg-white p-5">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold">保存到 {directory}</h2>
              {parent !== null ? (
                <button type="button" className="text-sm font-medium text-primary-dark" onClick={() => setDirectory(parent)}>
                  返回上一层
                </button>
              ) : null}
            </div>
            <ul className="mt-4 space-y-2">
              {entries.filter((entry) => entry.is_dir).map((entry) => (
                <li key={entry.path}>
                  <button type="button" className="text-sm font-medium" onClick={() => setDirectory(entry.path)}>
                    {entry.name}
                  </button>
                </li>
              ))}
              {entries.filter((entry) => !entry.is_dir).map((entry) => (
                <li key={entry.path} className="text-sm text-ink/45">{entry.name}</li>
              ))}
            </ul>
          </section>
          <label className="block text-sm font-medium">
            分享链接
            <textarea
              className="mt-2 min-h-40 w-full rounded-2xl border border-line bg-white px-4 py-3"
              value={links}
              onChange={(event) => setLinks(event.target.value)}
              placeholder={"https://pan.baidu.com/s/1xxxx abcd"}
            />
          </label>
          {error ? <p className="rounded-2xl bg-red-50 px-4 py-3 text-sm text-danger">{error}</p> : null}
          <button
            type="button"
            disabled={pending || links.trim() === ""}
            onClick={submit}
            className="rounded-full bg-accent px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
          >
            {pending ? "正在创建" : "开始转存"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
```

`frontend/src/pages/JobPage.tsx`：

```tsx
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Job } from "../api";

const statusName: Record<string, string> = {
  pending: "等待执行",
  running: "正在转存",
  succeeded: "全部成功",
  partial: "部分成功",
  failed: "全部失败",
};

export default function JobPage() {
  const { id } = useParams();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) return;
    let timer = 0;
    let stopped = false;
    async function poll() {
      try {
        const next = await api.job(id);
        if (stopped) return;
        setJob(next);
        if (next.status === "pending" || next.status === "running") {
          timer = window.setTimeout(poll, 2000);
        }
      } catch (caught) {
        if (!stopped) setError(caught instanceof Error ? caught.message : "任务不存在");
      }
    }
    void poll();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [id]);

  return (
    <div className="mx-auto max-w-3xl">
      <Link to="/transfer" className="text-sm font-medium text-primary-dark">返回转存</Link>
      <h1 className="mt-3 text-3xl font-semibold tracking-tight">{job ? statusName[job.status] ?? job.status : "任务"}</h1>
      {job ? <p className="mt-2 text-sm text-ink/60">目录 {job.directory}</p> : null}
      {error ? <p className="mt-4 rounded-2xl bg-red-50 px-4 py-3 text-sm text-danger">{error}</p> : null}
      <ul className="mt-6 space-y-3">
        {job?.items.map((item) => (
          <li key={item.id} className="rounded-3xl border border-line bg-white p-4">
            <p className="break-all text-sm">{item.input_text}</p>
            <p className="mt-2 text-sm text-ink/60">{item.error ?? item.result ?? statusName[item.status] ?? item.status}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

`docker-compose.yml` 的 `api` 服务后面增加 `worker`。环境变量和 `api` 相同，命令覆盖成 Worker，不要再跑 uvicorn：

```yaml
  worker:
    build: ./backend
    command: ["python", "-m", "app.worker"]
    environment:
      DATABASE_URL: postgresql+psycopg://pan:pan@db:5432/pan
      JWT_SECRET: dev-secret-change-me-to-32-characters
      ADMIN_EMAIL: admin@example.com
      ADMIN_PASSWORD: admin-pass-123
      COOKIE_SECURE: "false"
      AUTO_CREATE_TABLES: "false"
      COOKIE_FERNET_KEY: MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=
    depends_on:
      db:
        condition: service_healthy
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npx tsc --noEmit`

Expected: 退出码 0

- [ ] **Step 3: 再跑转存测试**

Run: `cd backend && .venv/bin/python -m pytest tests/test_transfers.py -q`

Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add frontend/src/api.ts frontend/src/App.tsx frontend/src/components/AppShell.tsx frontend/src/pages/HomePage.tsx frontend/src/pages/TransferPage.tsx frontend/src/pages/JobPage.tsx docker-compose.yml
git commit -m "$(cat <<'EOF'
feat: add a page for batch Baidu transfers

EOF
)"
```

---

## 规格覆盖

| 规格要求 | 任务 |
|---|---|
| 选择有效百度账号、当前层目录、多行链接 | Task 5、Task 6 |
| 三种链接写法和可省略提取码 | Task 2 |
| 一条失败不影响其余，任务 succeeded / partial / failed | Task 5 |
| 无法解析、无效、提取码错误、同名文件 | Task 4、Task 5 |
| 不自动改名 | Task 4，`ondup=fail` |
| 限流 3 次，间隔 2 秒、8 秒，第 3 次失败停止 | Task 5 |
| Cookie 失效后停止该账号后续请求 | Task 5 |
| 超过 15 分钟的 running 条目重新排队，最多 3 次 | Task 5 |
| 免费 100 条，超额整批拒绝且用量不变，返回剩余条数 | Task 3、Task 5 |
| 付费计入用量但不拒绝；管理员不计入 | Task 3 |
| 到期按免费 | Task 3 |
| 目标目录不存在则不创建任务 | Task 5 |
| API 只列目录，转存只在 Worker | Task 4、Task 5、Compose |
| 响应不含 Cookie | Task 5 的断言 |
| 分享、CSV、同步、统计 | 不在本计划 |

## 自检

- 额度、解析、适配器、执行、页面各自有失败测试和实现，除页面用 `tsc` 验收。
- `execute_job`、`reserve_transfers`、`transfer_share`、`ParsedLink.surl` 在前后任务里名称一致。
- 没有把分享导出或快照写进任务。
- Worker 的 20 秒间隔故意不睡眠，原因写在锁定规则里。
