# 百度账号绑定 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户可以粘贴百度 Cookie，核对登录成功后加密保存，并在页面上只看到昵称和状态。

**Architecture:** API 进程调用百度适配器的只读动作「核对登录」。适配器只发 HTTP，不访问数据库。Cookie 用 Fernet 加密后写入 `pan_accounts`，密钥来自 `COOKIE_FERNET_KEY`。免费用户最多 1 个状态为 `valid` 的百度账号，付费用户和管理员最多 5 个。夸克和迅雷适配器直接返回「暂未开放」。前端沿用现有 Tailwind 工作台，不装回 Ant Design。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、Alembic、cryptography（Fernet）、httpx、pytest。前端是 Vite + React + TypeScript + Tailwind CSS。

**本计划范围：** 规格《网盘拉新工具设计》的第 2 步。不实现列目录、转存、分享、同步、快照、数据查询，也不实现解绑。用户要换 Cookie 时，更新同一条账号记录。

**已锁定的数量规则：** 只统计 `provider=baidu` 且 `status=valid` 的账号。`expired` 不占名额。管理员 `can_use_paid_features` 为真，因此和管理员自己的付费用户一样，上限是 5，而不是免费的 1。已经是 `valid` 的账号更新 Cookie 不额外占名额；把 `expired` 重新核对为 `valid` 时要占一个空位。

---

## 文件职责

| 文件 | 职责 |
|---|---|
| `backend/app/crypto.py` | Fernet 加密和解密 Cookie |
| `backend/app/config.py` | 增加 `cookie_fernet_key` |
| `backend/app/models.py` | 增加 `pan_accounts` |
| `backend/app/pans/errors.py` | 核对失败、网盘未开放 |
| `backend/app/pans/baidu.py` | 百度核对登录 |
| `backend/app/pans/closed.py` | 夸克、迅雷返回未开放 |
| `backend/app/pans/__init__.py` | 按网盘类型选择适配器 |
| `backend/app/routers/accounts.py` | 列表、绑定、更新 Cookie |
| `backend/alembic/versions/002_pan_accounts.py` | PostgreSQL 建表 |
| `frontend/src/pages/AccountsPage.tsx` | 绑定和更新页面 |

---

### Task 1: Cookie 加密

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/config.py`
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/test_config.py`
- Modify: `backend/tests/test_bootstrap.py`
- Modify: `backend/.env.example`
- Modify: `docker-compose.yml`
- Create: `backend/app/crypto.py`
- Test: `backend/tests/test_crypto.py`

固定测试密钥（32 字节的 urlsafe base64，可被 Fernet 接受）：

`MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_crypto.py
import pytest

from app.crypto import decrypt_cookie, encrypt_cookie

KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
COOKIE = "BDUSS=super-secret-cookie-value"


def test_encrypt_round_trip_hides_plaintext():
    ciphertext = encrypt_cookie(COOKIE, KEY)
    assert COOKIE not in ciphertext
    assert decrypt_cookie(ciphertext, KEY) == COOKIE


def test_invalid_key_is_rejected():
    with pytest.raises(RuntimeError, match="COOKIE_FERNET_KEY 无效"):
        encrypt_cookie(COOKIE, "not-a-fernet-key")


def test_tampered_ciphertext_is_rejected():
    ciphertext = encrypt_cookie(COOKIE, KEY)
    with pytest.raises(RuntimeError, match="Cookie 无法解密"):
        decrypt_cookie(ciphertext[:-2] + "aa", KEY)
```

在 `backend/tests/test_config.py` 的 `test_settings_read_env` 里增加：

```python
    monkeypatch.setenv("COOKIE_FERNET_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=")
```

并在断言里增加：

```python
    assert settings.cookie_fernet_key == "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
```

- [ ] **Step 2: 运行测试，确认失败**

在 `backend/` 执行：

```bash
.venv/bin/pytest tests/test_crypto.py -v
```

Expected: FAIL，`app.crypto` 无法导入。

- [ ] **Step 3: 写实现**

`backend/pyproject.toml` 的 `dependencies` 增加一行：

```toml
  "cryptography>=44",
```

然后在 `backend/` 执行 `pip install -e ".[dev]"`。

`backend/app/config.py` 在 `auto_create_tables` 后面增加：

```python
    cookie_fernet_key: str
```

`backend/app/crypto.py`：

```python
from cryptography.fernet import Fernet, InvalidToken


def _fernet(key: str) -> Fernet:
    try:
        return Fernet(key.encode())
    except Exception as exc:
        raise RuntimeError("COOKIE_FERNET_KEY 无效") from exc


def encrypt_cookie(cookie: str, key: str) -> str:
    return _fernet(key).encrypt(cookie.encode()).decode()


def decrypt_cookie(ciphertext: str, key: str) -> str:
    try:
        return _fernet(key).decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Cookie 无法解密") from exc
```

`backend/tests/conftest.py` 的 `client` fixture 在 `AUTO_CREATE_TABLES` 那行后面增加：

```python
    monkeypatch.setenv("COOKIE_FERNET_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=")
```

`backend/tests/test_bootstrap.py` 里构造 `Settings(...)` 时增加参数：

```python
        cookie_fernet_key="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
```

`backend/.env.example` 增加：

```text
COOKIE_FERNET_KEY=MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=
```

`docker-compose.yml` 的 `api.environment` 增加：

```yaml
      COOKIE_FERNET_KEY: MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=
```

这是本地开发密钥。部署时换成 `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` 生成的新密钥。换密钥后，已经加密的 Cookie 无法解密。

- [ ] **Step 4: 运行测试**

```bash
.venv/bin/pytest -v
```

Expected: 原有测试和 `tests/test_crypto.py` 的 3 个测试都 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/app/config.py backend/app/crypto.py backend/tests/test_crypto.py backend/tests/test_config.py backend/tests/conftest.py backend/tests/test_bootstrap.py backend/.env.example docker-compose.yml
git commit -m "$(cat <<'EOF'
feat: encrypt stored cookies with Fernet

EOF
)"
```

---

### Task 2: 网盘账号表

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/alembic/env.py`
- Create: `backend/alembic/versions/002_pan_accounts.py`
- Test: `backend/tests/test_models.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_models.py` 末尾增加：

```python
from app.models import PanAccount


def test_pan_account_round_trip():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(email="user@example.com", password_hash="hash", role="user", plan="free")
        session.add(user)
        session.commit()
        session.add(
            PanAccount(
                user_id=user.id,
                provider="baidu",
                nickname="网盘昵称",
                cookie_ciphertext="ciphertext",
                status="valid",
            )
        )
        session.commit()
        saved = session.query(PanAccount).one()
        assert saved.user_id == user.id
        assert saved.provider == "baidu"
        assert saved.nickname == "网盘昵称"
        assert saved.cookie_ciphertext == "ciphertext"
        assert saved.status == "valid"
        assert saved.created_at is not None
        assert saved.updated_at is not None
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
.venv/bin/pytest tests/test_models.py::test_pan_account_round_trip -v
```

Expected: FAIL，`PanAccount` 无法导入。

- [ ] **Step 3: 写模型和迁移**

`backend/app/models.py` 增加导入 `Text`、`ForeignKey`，并增加模型：

```python
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class PanAccount(Base):
    __tablename__ = "pan_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(16))
    nickname: Mapped[str] = mapped_column(String(255))
    cookie_ciphertext: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="valid")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
```

`backend/alembic/env.py` 把模型导入改成：

```python
from app.models import PanAccount, User  # noqa: F401
```

`backend/alembic/versions/002_pan_accounts.py`：

```python
"""create pan accounts

Revision ID: 002_pan_accounts
Revises: 001_users
Create Date: 2026-09-22
"""

from alembic import op
import sqlalchemy as sa

revision = "002_pan_accounts"
down_revision = "001_users"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pan_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("nickname", sa.String(length=255), nullable=False),
        sa.Column("cookie_ciphertext", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pan_accounts_user_id", "pan_accounts", ["user_id"])


def downgrade():
    op.drop_index("ix_pan_accounts_user_id", table_name="pan_accounts")
    op.drop_table("pan_accounts")
```

不要用 Alembic autogenerate。测试仍靠 `AUTO_CREATE_TABLES` 建表，模型必须写在 `app.models` 里，应用导入路由时才会注册到 `Base.metadata`。

- [ ] **Step 4: 运行测试**

```bash
.venv/bin/pytest tests/test_models.py -v
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/alembic/env.py backend/alembic/versions/002_pan_accounts.py backend/tests/test_models.py
git commit -m "$(cat <<'EOF'
feat: store pan accounts separately from users

EOF
)"
```

---

### Task 3: 核对登录适配器

**Files:**
- Create: `backend/app/pans/__init__.py`
- Create: `backend/app/pans/errors.py`
- Create: `backend/app/pans/baidu.py`
- Create: `backend/app/pans/closed.py`
- Test: `backend/tests/test_pans.py`

百度核对登录只请求这一个地址，不跟随重定向，避免把 Cookie 发到别的主机：

`GET https://pan.baidu.com/rest/2.0/xpan/nas?method=uinfo`

请求头带上用户粘贴的 `Cookie`，以及固定的浏览器 User-Agent。响应 JSON 的 `errno` 为 `0` 时成功。昵称优先用非空的 `netdisk_name`，否则用 `baidu_name`。HTTP 不是 200、响应不是 JSON、`errno` 不是 0、两个名字都空，都视为核对失败。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_pans.py
import httpx
import pytest

from app.pans import LoginRejected, ProviderClosed, adapter_for

COOKIE = "BDUSS=super-secret-cookie-value"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_baidu_verify_uses_netdisk_name():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.host == "pan.baidu.com"
        assert request.url.params["method"] == "uinfo"
        assert request.headers["cookie"] == COOKIE
        assert request.headers["user-agent"] == UA
        return httpx.Response(200, json={"errno": 0, "netdisk_name": "网盘昵称", "baidu_name": "百度名"})

    nickname = adapter_for("baidu", client_for(handler)).verify_login(COOKIE)
    assert nickname == "网盘昵称"


def test_baidu_verify_falls_back_to_baidu_name():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errno": 0, "netdisk_name": "  ", "baidu_name": "百度名"})

    nickname = adapter_for("baidu", client_for(handler)).verify_login(COOKIE)
    assert nickname == "百度名"


def test_baidu_verify_rejects_bad_cookie():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errno": -6})

    with pytest.raises(LoginRejected):
        adapter_for("baidu", client_for(handler)).verify_login(COOKIE)


def test_baidu_verify_rejects_non_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>login</html>")

    with pytest.raises(LoginRejected):
        adapter_for("baidu", client_for(handler)).verify_login(COOKIE)


def test_closed_providers_do_not_call_http():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("closed provider must not send HTTP")

    for provider in ("quark", "xunlei"):
        with pytest.raises(ProviderClosed, match="暂未开放"):
            adapter_for(provider, client_for(handler)).verify_login(COOKIE)


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="网盘类型无效"):
        adapter_for("dropbox", client_for(lambda request: httpx.Response(500)))
```

实现必须传入 `follow_redirects=False`。上面的测试只检查地址、Cookie 和 User-Agent。

- [ ] **Step 2: 运行测试，确认失败**

```bash
.venv/bin/pytest tests/test_pans.py -v
```

Expected: FAIL，`app.pans` 无法导入。

- [ ] **Step 3: 写适配器**

`backend/app/pans/errors.py`：

```python
class LoginRejected(Exception):
    pass


class ProviderClosed(Exception):
    def __init__(self) -> None:
        super().__init__("暂未开放")
```

`backend/app/pans/baidu.py`：

```python
import httpx

from app.pans.errors import LoginRejected

BAIDU_UINFO = "https://pan.baidu.com/rest/2.0/xpan/nas"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


class BaiduAdapter:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def verify_login(self, cookie: str) -> str:
        try:
            response = self.client.get(
                BAIDU_UINFO,
                params={"method": "uinfo"},
                headers={"Cookie": cookie, "User-Agent": USER_AGENT},
                timeout=10,
                follow_redirects=False,
            )
            payload = response.json() if response.status_code == 200 else None
        except Exception as exc:
            raise LoginRejected() from exc
        if not isinstance(payload, dict) or payload.get("errno") != 0:
            raise LoginRejected()
        for key in ("netdisk_name", "baidu_name"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        raise LoginRejected()
```

`LoginRejected` 不保存 Cookie，也不写日志。

`backend/app/pans/closed.py`：

```python
from app.pans.errors import ProviderClosed


class ClosedAdapter:
    def verify_login(self, cookie: str) -> str:
        raise ProviderClosed()
```

`backend/app/pans/__init__.py`：

```python
import httpx

from app.pans.baidu import BaiduAdapter
from app.pans.closed import ClosedAdapter
from app.pans.errors import LoginRejected, ProviderClosed

__all__ = ["LoginRejected", "ProviderClosed", "adapter_for"]


def adapter_for(provider: str, client: httpx.Client):
    if provider == "baidu":
        return BaiduAdapter(client)
    if provider in {"quark", "xunlei"}:
        return ClosedAdapter()
    raise ValueError("网盘类型无效")
```

- [ ] **Step 4: 运行测试**

```bash
.venv/bin/pytest tests/test_pans.py -v
```

Expected: 6 passed。

- [ ] **Step 5: Commit**

```bash
git add backend/app/pans backend/tests/test_pans.py
git commit -m "$(cat <<'EOF'
feat: verify a Baidu cookie before it is stored

EOF
)"
```

---

### Task 4: 绑定名额

**Files:**
- Modify: `backend/app/membership.py`
- Test: `backend/tests/test_membership.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_membership.py` 末尾增加。文件里如果还没有这些导入，补上 `timedelta`。构造用户时沿用该文件已有的 `User(...)` 写法；下面的辅助函数只给这几个测试用：

```python
from datetime import timedelta

from app.membership import baidu_account_limit


def _user(role: str, plan: str, expires_at):
    return User(
        email="user@example.com",
        password_hash="hash",
        role=role,
        plan=plan,
        plan_expires_at=expires_at,
    )


def test_free_user_can_bind_one_baidu_account():
    user = _user("user", "free", None)
    assert baidu_account_limit(user, datetime.now(timezone.utc)) == 1


def test_paid_user_can_bind_five_baidu_accounts():
    user = _user("user", "paid", datetime.now(timezone.utc) + timedelta(days=1))
    assert baidu_account_limit(user, datetime.now(timezone.utc)) == 5


def test_expired_paid_user_can_bind_one_baidu_account():
    user = _user("user", "paid", datetime.now(timezone.utc) - timedelta(days=1))
    assert baidu_account_limit(user, datetime.now(timezone.utc)) == 1


def test_admin_can_bind_five_baidu_accounts():
    user = _user("admin", "free", None)
    assert baidu_account_limit(user, datetime.now(timezone.utc)) == 5
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
.venv/bin/pytest tests/test_membership.py -v
```

Expected: FAIL，`baidu_account_limit` 不存在。该文件里原有测试仍应通过；如果导入失败，整个文件失败也可以。

- [ ] **Step 3: 写实现**

在 `backend/app/membership.py` 增加：

```python
def baidu_account_limit(user: User, now: datetime) -> int:
    if can_use_paid_features(user, now):
        return 5
    return 1
```

- [ ] **Step 4: 运行测试**

```bash
.venv/bin/pytest tests/test_membership.py -v
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/app/membership.py backend/tests/test_membership.py
git commit -m "$(cat <<'EOF'
feat: cap how many Baidu accounts a plan can bind

EOF
)"
```

---

### Task 5: 绑定和更新接口

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/main.py`
- Create: `backend/app/routers/accounts.py`
- Test: `backend/tests/test_accounts.py`

接口：

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/api/accounts` | 只返回当前用户的账号，字段只有 id、provider、nickname、status、created_at、updated_at |
| POST | `/api/accounts` | body `{provider, cookie}`。成功 201 |
| PATCH | `/api/accounts/{id}` | body `{cookie}`。只能改自己的账号 |

错误：

| 情况 | 状态 | detail |
|---|---|---|
| 未登录 | 401 | 未登录 |
| 空白 Cookie | 422 | Cookie 不能为空 |
| provider 不是 baidu、quark、xunlei | 422 | 网盘类型无效 |
| quark 或 xunlei | 422 | 暂未开放 |
| 百度核对失败 | 422 | 请重新登录百度后再粘贴 Cookie |
| 免费用户已有 1 个 valid 百度账号又新增 | 422 | 免费用户只能绑定 1 个百度账号 |
| 付费或管理员已有 5 个 valid 百度账号又新增 | 422 | 最多绑定 5 个百度账号 |
| 账号不存在，或属于别人 | 404 | 账号不存在 |

核对失败时不插入、不修改。响应正文、`app` 日志里都不能出现本次提交的 Cookie 原文。不要记录请求头和请求体。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_accounts.py
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.crypto import decrypt_cookie
from app.models import PanAccount

KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
SECRET = "BDUSS=super-secret-cookie-value"


def install_baidu(client, payload=None, status_code=200, text=None, calls=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request.headers.get("cookie"))
        if text is not None:
            return httpx.Response(status_code, text=text)
        return httpx.Response(status_code, json=payload)

    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))


def register(client, email="user@example.com"):
    response = client.post("/api/auth/register", json={"email": email, "password": "password-123"})
    assert response.status_code == 201
    return response.json()


def grant_paid(client, user_id: int):
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "admin@example.com", "password": "admin-pass-123"})
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    updated = client.patch(
        f"/api/admin/users/{user_id}",
        json={"plan": "paid", "plan_expires_at": future},
    )
    assert updated.status_code == 200
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "user@example.com", "password": "password-123"})


def test_bind_stores_ciphertext_and_hides_cookie(client, caplog):
    caplog.set_level(logging.DEBUG, logger="app")
    register(client)
    install_baidu(client, {"errno": 0, "netdisk_name": "网盘昵称", "baidu_name": "百度名"})
    response = client.post("/api/accounts", json={"provider": "baidu", "cookie": f"  {SECRET}  "})
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "provider", "nickname", "status", "created_at", "updated_at"}
    assert body["provider"] == "baidu"
    assert body["nickname"] == "网盘昵称"
    assert body["status"] == "valid"
    assert SECRET not in response.text
    assert SECRET not in caplog.text

    listed = client.get("/api/accounts")
    assert listed.status_code == 200
    assert SECRET not in listed.text
    assert listed.json()[0]["nickname"] == "网盘昵称"

    with client.app.state.session_factory() as session:
        saved = session.scalars(select(PanAccount)).one()
        assert saved.cookie_ciphertext != SECRET
        assert decrypt_cookie(saved.cookie_ciphertext, KEY) == SECRET


def test_bind_rejects_failed_check_without_saving(client):
    register(client)
    install_baidu(client, {"errno": -6})
    response = client.post("/api/accounts", json={"provider": "baidu", "cookie": SECRET})
    assert response.status_code == 422
    assert response.json()["detail"] == "请重新登录百度后再粘贴 Cookie"
    assert client.get("/api/accounts").json() == []


def test_bind_rejects_blank_cookie(client):
    register(client)
    response = client.post("/api/accounts", json={"provider": "baidu", "cookie": "   "})
    assert response.status_code == 422
    assert response.json()["detail"] == "Cookie 不能为空"


def test_quark_and_xunlei_are_closed(client):
    register(client)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("closed provider must not send HTTP")

    client.app.state.pan_http_client = httpx.Client(transport=httpx.MockTransport(handler))
    for provider in ("quark", "xunlei"):
        response = client.post("/api/accounts", json={"provider": provider, "cookie": SECRET})
        assert response.status_code == 422
        assert response.json()["detail"] == "暂未开放"
    assert client.get("/api/accounts").json() == []


def test_unknown_provider_is_rejected(client):
    register(client)
    response = client.post("/api/accounts", json={"provider": "dropbox", "cookie": SECRET})
    assert response.status_code == 422
    assert response.json()["detail"] == "网盘类型无效"


def test_guest_cannot_list_accounts(client):
    response = client.get("/api/accounts")
    assert response.status_code == 401
    assert response.json()["detail"] == "未登录"


def test_free_user_cannot_bind_a_second_valid_account(client):
    register(client)
    install_baidu(client, {"errno": 0, "netdisk_name": "第一个"})
    assert client.post("/api/accounts", json={"provider": "baidu", "cookie": SECRET}).status_code == 201
    install_baidu(client, {"errno": 0, "netdisk_name": "第二个"})
    again = client.post("/api/accounts", json={"provider": "baidu", "cookie": "BDUSS=another-secret"})
    assert again.status_code == 422
    assert again.json()["detail"] == "免费用户只能绑定 1 个百度账号"
    assert len(client.get("/api/accounts").json()) == 1


def test_expired_account_does_not_use_a_slot(client):
    register(client)
    install_baidu(client, {"errno": 0, "netdisk_name": "旧账号"})
    created = client.post("/api/accounts", json={"provider": "baidu", "cookie": SECRET})
    with client.app.state.session_factory() as session:
        account = session.get(PanAccount, created.json()["id"])
        account.status = "expired"
        session.commit()
    install_baidu(client, {"errno": 0, "netdisk_name": "新账号"})
    again = client.post("/api/accounts", json={"provider": "baidu", "cookie": "BDUSS=another-secret"})
    assert again.status_code == 201
    assert again.json()["nickname"] == "新账号"


def test_paid_user_stops_at_five_accounts(client):
    user = register(client)
    grant_paid(client, user["id"])
    for index in range(5):
        install_baidu(client, {"errno": 0, "netdisk_name": f"账号{index}"})
        response = client.post("/api/accounts", json={"provider": "baidu", "cookie": f"BDUSS=secret-{index}"})
        assert response.status_code == 201
    install_baidu(client, {"errno": 0, "netdisk_name": "第六个"})
    denied = client.post("/api/accounts", json={"provider": "baidu", "cookie": "BDUSS=secret-6"})
    assert denied.status_code == 422
    assert denied.json()["detail"] == "最多绑定 5 个百度账号"


def test_update_cookie_replaces_ciphertext(client):
    register(client)
    install_baidu(client, {"errno": 0, "netdisk_name": "旧昵称"})
    created = client.post("/api/accounts", json={"provider": "baidu", "cookie": SECRET})
    account_id = created.json()["id"]
    install_baidu(client, {"errno": 0, "netdisk_name": "新昵称"})
    updated = client.patch(f"/api/accounts/{account_id}", json={"cookie": "BDUSS=replacement-secret"})
    assert updated.status_code == 200
    assert updated.json()["nickname"] == "新昵称"
    assert updated.json()["status"] == "valid"
    assert "replacement-secret" not in updated.text
    with client.app.state.session_factory() as session:
        saved = session.get(PanAccount, account_id)
        assert decrypt_cookie(saved.cookie_ciphertext, KEY) == "BDUSS=replacement-secret"


def test_update_keeps_the_row_when_check_fails(client):
    register(client)
    install_baidu(client, {"errno": 0, "netdisk_name": "旧昵称"})
    created = client.post("/api/accounts", json={"provider": "baidu", "cookie": SECRET})
    account_id = created.json()["id"]
    install_baidu(client, {"errno": -6})
    failed = client.patch(f"/api/accounts/{account_id}", json={"cookie": "BDUSS=bad-secret"})
    assert failed.status_code == 422
    with client.app.state.session_factory() as session:
        saved = session.get(PanAccount, account_id)
        assert saved.nickname == "旧昵称"
        assert decrypt_cookie(saved.cookie_ciphertext, KEY) == SECRET


def test_update_of_valid_account_does_not_require_another_slot(client):
    register(client)
    install_baidu(client, {"errno": 0, "netdisk_name": "唯一"})
    created = client.post("/api/accounts", json={"provider": "baidu", "cookie": SECRET})
    install_baidu(client, {"errno": 0, "netdisk_name": "换过"})
    updated = client.patch(f"/api/accounts/{created.json()['id']}", json={"cookie": "BDUSS=replacement-secret"})
    assert updated.status_code == 200
    assert len(client.get("/api/accounts").json()) == 1


def test_cannot_update_someone_elses_account(client):
    register(client, "user@example.com")
    install_baidu(client, {"errno": 0, "netdisk_name": "用户的"})
    created = client.post("/api/accounts", json={"provider": "baidu", "cookie": SECRET})
    client.post("/api/auth/logout")
    register(client, "other@example.com")
    install_baidu(client, {"errno": 0, "netdisk_name": "不该发生"})
    response = client.patch(f"/api/accounts/{created.json()['id']}", json={"cookie": "BDUSS=other-secret"})
    assert response.status_code == 404
    assert response.json()["detail"] == "账号不存在"


def test_missing_account_is_not_found(client):
    register(client)
    response = client.patch("/api/accounts/999", json={"cookie": SECRET})
    assert response.status_code == 404
    assert response.json()["detail"] == "账号不存在"
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
.venv/bin/pytest tests/test_accounts.py -v
```

Expected: FAIL，路由不存在，状态码是 404 且不是「账号不存在」。

- [ ] **Step 3: 写接口**

`backend/app/schemas.py` 增加：

```python
class AccountBindIn(BaseModel):
    provider: str
    cookie: str = Field(min_length=1, max_length=8192)


class AccountCookieIn(BaseModel):
    cookie: str = Field(min_length=1, max_length=8192)


class AccountOut(BaseModel):
    id: int
    provider: str
    nickname: str
    status: str
    created_at: datetime
    updated_at: datetime
```

`backend/app/routers/accounts.py`：

```python
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.crypto import encrypt_cookie
from app.deps import get_current_user, get_db, now_utc
from app.membership import baidu_account_limit
from app.models import PanAccount, User
from app.pans import LoginRejected, ProviderClosed, adapter_for
from app.schemas import AccountBindIn, AccountCookieIn, AccountOut

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def get_pan_http_client(request: Request) -> httpx.Client:
    client = getattr(request.app.state, "pan_http_client", None)
    if client is None:
        client = httpx.Client()
        request.app.state.pan_http_client = client
    return client


def to_account_out(account: PanAccount) -> AccountOut:
    return AccountOut(
        id=account.id,
        provider=account.provider,
        nickname=account.nickname,
        status=account.status,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


def ensure_baidu_slot(session: Session, user: User, now: datetime, account: PanAccount | None) -> None:
    if account is not None and account.provider == "baidu" and account.status == "valid":
        return
    limit = baidu_account_limit(user, now)
    count = session.scalar(
        select(func.count())
        .select_from(PanAccount)
        .where(
            PanAccount.user_id == user.id,
            PanAccount.provider == "baidu",
            PanAccount.status == "valid",
        )
    )
    if count is not None and count >= limit:
        if limit == 1:
            raise HTTPException(status_code=422, detail="免费用户只能绑定 1 个百度账号")
        raise HTTPException(status_code=422, detail="最多绑定 5 个百度账号")


def verified_nickname(provider: str, cookie: str, client: httpx.Client) -> str:
    try:
        adapter = adapter_for(provider, client)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="网盘类型无效") from exc
    try:
        return adapter.verify_login(cookie)
    except ProviderClosed as exc:
        raise HTTPException(status_code=422, detail="暂未开放") from exc
    except LoginRejected as exc:
        raise HTTPException(status_code=422, detail="请重新登录百度后再粘贴 Cookie") from exc


def clean_cookie(cookie: str) -> str:
    value = cookie.strip()
    if not value:
        raise HTTPException(status_code=422, detail="Cookie 不能为空")
    return value


@router.get("")
def list_accounts(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> list[AccountOut]:
    rows = session.scalars(select(PanAccount).where(PanAccount.user_id == user.id).order_by(PanAccount.id)).all()
    return [to_account_out(row) for row in rows]


@router.post("", status_code=201)
def bind_account(
    body: AccountBindIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    now: datetime = Depends(now_utc),
) -> AccountOut:
    cookie = clean_cookie(body.cookie)
    if body.provider not in {"baidu", "quark", "xunlei"}:
        raise HTTPException(status_code=422, detail="网盘类型无效")
    if body.provider == "baidu":
        ensure_baidu_slot(session, user, now, None)
    nickname = verified_nickname(body.provider, cookie, get_pan_http_client(request))
    account = PanAccount(
        user_id=user.id,
        provider=body.provider,
        nickname=nickname,
        cookie_ciphertext=encrypt_cookie(cookie, request.app.state.settings.cookie_fernet_key),
        status="valid",
        created_at=now,
        updated_at=now,
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    return to_account_out(account)


@router.patch("/{account_id}")
def update_cookie(
    account_id: int,
    body: AccountCookieIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    now: datetime = Depends(now_utc),
) -> AccountOut:
    cookie = clean_cookie(body.cookie)
    account = session.scalar(
        select(PanAccount).where(PanAccount.id == account_id, PanAccount.user_id == user.id)
    )
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    if account.provider == "baidu":
        ensure_baidu_slot(session, user, now, account)
    nickname = verified_nickname(account.provider, cookie, get_pan_http_client(request))
    account.nickname = nickname
    account.cookie_ciphertext = encrypt_cookie(cookie, request.app.state.settings.cookie_fernet_key)
    account.status = "valid"
    account.updated_at = now
    session.commit()
    session.refresh(account)
    return to_account_out(account)
```

`backend/app/main.py` 的 lifespan 在 `engine.dispose()` 之前关闭客户端：

```python
    client = getattr(app.state, "pan_http_client", None)
    if client is not None:
        client.close()
    engine.dispose()
```

`create_app` 增加：

```python
from app.routers import accounts, admin, auth
```

以及：

```python
    app.include_router(accounts.router)
```

路由里不要调用 `logging`。异常信息只用上面表里的中文，不要把 Cookie 拼进去。

- [ ] **Step 4: 运行测试**

```bash
.venv/bin/pytest tests/test_accounts.py -v
```

Expected: 13 passed。

再跑全量：

```bash
.venv/bin/pytest -v
```

Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas.py backend/app/routers/accounts.py backend/app/main.py backend/tests/test_accounts.py
git commit -m "$(cat <<'EOF'
feat: bind and refresh a Baidu account cookie

EOF
)"
```

---

### Task 6: 网盘账号页面

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/pages/AccountsPage.tsx`

页面放在现有工作台里。侧栏在「工作台」下面增加「网盘账号」，所有已登录用户都能看到。未登录访问 `/accounts` 时跳到 `/login`。

页面包含：

- 百度 Cookie 多行输入框，按钮文案是「绑定百度」。
- 夸克、迅雷两个按钮是禁用状态，旁边写「暂未开放」，点击不会发请求。
- 已绑定列表显示昵称、网盘名称、状态。状态 `valid` 显示「有效」，`expired` 显示「已失效」。
- 每一行可以再贴一份 Cookie，按钮文案是「更新 Cookie」。
- 接口返回的错误显示在红色提示里。成功后清空对应输入框并重新加载列表。

不要把 Cookie 写进 `localStorage`、页面标题或除了输入框以外的可见文字。

- [ ] **Step 1: 增加 API 方法**

`frontend/src/api.ts` 增加类型和方法：

```typescript
export type PanAccount = {
  id: number;
  provider: string;
  nickname: string;
  status: string;
  created_at: string;
  updated_at: string;
};
```

在 `api` 对象里增加：

```typescript
  accounts: () => request<PanAccount[]>("/api/accounts"),
  bindAccount: (provider: string, cookie: string) =>
    request<PanAccount>("/api/accounts", {
      method: "POST",
      body: JSON.stringify({ provider, cookie }),
    }),
  updateAccountCookie: (id: number, cookie: string) =>
    request<PanAccount>(`/api/accounts/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ cookie }),
    }),
```

- [ ] **Step 2: 写页面**

`frontend/src/pages/AccountsPage.tsx`：

```tsx
import { useEffect, useState } from "react";
import { api, type PanAccount } from "../api";

const providerName: Record<string, string> = { baidu: "百度", quark: "夸克", xunlei: "迅雷" };

function statusName(status: string) {
  if (status === "valid") return "有效";
  if (status === "expired") return "已失效";
  return status;
}

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<PanAccount[]>([]);
  const [cookie, setCookie] = useState("");
  const [replacements, setReplacements] = useState<Record<number, string>>({});
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function load() {
    setAccounts(await api.accounts());
  }

  useEffect(() => {
    load().catch((caught: Error) => setError(caught.message));
  }, []);

  async function bind() {
    setPending(true);
    setError("");
    try {
      await api.bindAccount("baidu", cookie);
      setCookie("");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "绑定失败");
    } finally {
      setPending(false);
    }
  }

  async function update(account: PanAccount) {
    setPending(true);
    setError("");
    try {
      await api.updateAccountCookie(account.id, replacements[account.id] ?? "");
      setReplacements({ ...replacements, [account.id]: "" });
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "更新失败");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <p className="text-sm font-medium text-primary-dark">网盘</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">账号</h1>
      <p className="mt-2 text-sm leading-6 text-ink/65">
        在百度网盘网页登录后，把浏览器里的 Cookie 粘贴到这里。核对通过才会保存，页面只显示昵称和状态。
      </p>

      <section className="mt-8 rounded-3xl border border-line bg-white p-6">
        <h2 className="text-lg font-semibold">绑定百度</h2>
        <textarea
          value={cookie}
          onChange={(event) => setCookie(event.target.value)}
          placeholder="粘贴百度 Cookie"
          rows={5}
          className="mt-4 w-full rounded-2xl border border-line bg-canvas px-4 py-3 text-sm outline-none focus:border-primary focus:bg-white"
        />
        <div className="mt-4 flex flex-wrap gap-3">
          <button
            type="button"
            disabled={pending}
            onClick={bind}
            className="rounded-full bg-accent px-5 py-2.5 text-sm font-semibold text-white hover:bg-orange-700 disabled:opacity-60"
          >
            绑定百度
          </button>
          <button type="button" disabled className="rounded-full border border-line px-5 py-2.5 text-sm text-ink/40">
            夸克 · 暂未开放
          </button>
          <button type="button" disabled className="rounded-full border border-line px-5 py-2.5 text-sm text-ink/40">
            迅雷 · 暂未开放
          </button>
        </div>
      </section>

      {error ? <p className="mt-4 rounded-2xl bg-red-50 px-4 py-3 text-sm text-danger">{error}</p> : null}

      <section className="mt-6 space-y-4">
        {accounts.length === 0 ? (
          <p className="rounded-3xl border border-dashed border-line bg-white px-6 py-8 text-sm text-ink/55">还没有绑定网盘账号。</p>
        ) : null}
        {accounts.map((account) => (
          <article key={account.id} className="rounded-3xl border border-line bg-white p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold">{account.nickname}</h2>
                <p className="mt-1 text-sm text-ink/55">{providerName[account.provider] ?? account.provider}</p>
              </div>
              <span className="rounded-full bg-muted px-3 py-1 text-xs font-semibold text-ink">{statusName(account.status)}</span>
            </div>
            <textarea
              value={replacements[account.id] ?? ""}
              onChange={(event) => setReplacements({ ...replacements, [account.id]: event.target.value })}
              placeholder="粘贴新的 Cookie"
              rows={3}
              aria-label={`${account.nickname} 的新 Cookie`}
              className="mt-4 w-full rounded-2xl border border-line bg-canvas px-4 py-3 text-sm outline-none focus:border-primary focus:bg-white"
            />
            <button
              type="button"
              disabled={pending}
              onClick={() => update(account)}
              className="mt-3 rounded-full border border-line px-4 py-2 text-sm font-semibold text-ink hover:border-ink disabled:opacity-60"
            >
              更新 Cookie
            </button>
          </article>
        ))}
      </section>
    </div>
  );
}
```

- [ ] **Step 3: 接入路由和侧栏**

`frontend/src/components/AppShell.tsx` 的「工作台」链接后面增加，管理员判断之前：

```tsx
          <NavLink to="/accounts" className={({ isActive }) => navClass(isActive)}>
            网盘账号
          </NavLink>
```

`frontend/src/App.tsx` 导入 `AccountsPage`。在 `/admin/users` 路由之前增加：

```tsx
      <Route
        path="/accounts"
        element={
          user ? (
            <AppShell user={user} onLogout={onLogout}>
              <AccountsPage />
            </AppShell>
          ) : (
            <Navigate to="/login" />
          )
        }
      />
```

- [ ] **Step 4: 检查类型和页面**

```bash
npx tsc --noEmit
```

在 `frontend/` 执行。Expected: 没有类型错误。

浏览器里打开 `http://127.0.0.1:5173/accounts`。未登录应进入登录页。用已有账号登录后，侧栏有「网盘账号」，页面有绑定输入框、禁用的夸克和迅雷，以及空列表。不要粘贴真实百度 Cookie。后端测试已经覆盖核对成功和失败。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.ts frontend/src/components/AppShell.tsx frontend/src/App.tsx frontend/src/pages/AccountsPage.tsx
git commit -m "$(cat <<'EOF'
feat: add a page for binding Baidu accounts

EOF
)"
```

---

## 自检

规格「绑定百度」和测试里对应的条目：

- 粘贴 Cookie、核对成功后加密保存，并写入昵称和 `valid`：Task 5 `test_bind_stores_ciphertext_and_hides_cookie`。
- 核对失败不保存，提示重新登录后再贴：Task 5 `test_bind_rejects_failed_check_without_saving`。
- 更新 Cookie 走同一套核对：Task 5 `test_update_cookie_replaces_ciphertext`、`test_update_keeps_the_row_when_check_fails`。
- 有效百度账号不超过等级上限：Task 4 和 Task 5 的免费、付费、过期、管理员用例。
- 夸克、迅雷绑定被拒绝且不发请求：Task 3 和 Task 5。
- 响应和 `app` 日志没有 Cookie 原文：Task 5 的 caplog 断言。
- 前端只显示昵称和状态：Task 6。

不在本计划里：列目录、转存、分享、CSV、同步、快照、解绑、Worker。
