# 注册登录与会员 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户可以用邮箱注册并登录，管理员可以手动把用户设为付费并填写到期时间，到期后按免费用户处理。

**Architecture:** FastAPI 提供 JSON API，JWT 放在 HttpOnly Cookie 中。会员是否有效放在纯函数里，路由只负责读写数据库。测试使用 SQLite 内存库，不连接真实 PostgreSQL。生产用 Alembic 建表，再用 uvicorn 启动。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、Alembic、PyJWT、bcrypt、Pydantic Settings、pytest、httpx。前端是 Vite + React + TypeScript + Ant Design。

**本计划范围：** 规格《网盘拉新工具设计》的第 1 步，以及跑起来所需的仓库骨架。不包含百度绑定、转存、分享、同步和数据查询。那些各写一份后续计划。

---

## 文件职责

| 文件 | 职责 |
|---|---|
| `backend/pyproject.toml` | 依赖和 pytest 配置 |
| `backend/app/config.py` | 从环境变量读取配置 |
| `backend/app/db.py` | 引擎、会话、建表开关 |
| `backend/app/models.py` | `users` 表 |
| `backend/app/security.py` | 密码哈希和 JWT |
| `backend/app/membership.py` | 有效等级、付费功能是否可用 |
| `backend/app/schemas.py` | 请求和响应模型 |
| `backend/app/deps.py` | 当前用户、数据库会话、管理员校验 |
| `backend/app/bootstrap.py` | 没有管理员时创建第一个管理员 |
| `backend/app/routers/auth.py` | 注册、登录、退出、当前用户 |
| `backend/app/routers/admin.py` | 用户列表、修改等级 |
| `backend/app/main.py` | 组装应用和生命周期 |
| `backend/alembic/` | PostgreSQL 迁移 |
| `backend/Dockerfile` | API 镜像 |
| `docker-compose.yml` | PostgreSQL 和 API |
| `frontend/` | 登录、注册、管理用户页面 |

后续计划会新增 `backend/app/crypto.py`、`backend/app/pans/`、`backend/app/worker.py`，本计划不要提前创建这些文件。

---

### Task 1: 后端项目骨架

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/tests/test_smoke.py`

- [ ] **Step 1: 写 pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "pan-tools-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn>=0.32",
  "sqlalchemy>=2.0",
  "alembic>=1.14",
  "psycopg[binary]>=3.2",
  "pydantic-settings>=2.6",
  "pyjwt>=2.10",
  "bcrypt>=4.2",
  "httpx>=0.27",
]

[project.optional-dependencies]
dev = ["pytest>=8.3"]

[tool.setuptools.packages.find]
include = ["app*"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 2: 写冒烟测试**

```python
# backend/tests/test_smoke.py
def test_smoke():
    assert True
```

`backend/app/__init__.py` 留空。

- [ ] **Step 3: 安装并运行测试**

在 `backend/` 执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -v
```

Expected: `1 passed`

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml backend/app/__init__.py backend/tests/test_smoke.py
git commit -m "$(cat <<'EOF'
chore: scaffold the backend test project

EOF
)"
```

---

### Task 2: 配置

**Files:**
- Create: `backend/app/config.py`
- Test: `backend/tests/test_config.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_config.py
import pytest

from app.config import Settings, get_settings


def test_settings_read_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("JWT_SECRET", "secret")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-pass-123")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("AUTO_CREATE_TABLES", "true")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.database_url == "sqlite+pysqlite:///:memory:"
    assert settings.jwt_secret == "secret"
    assert settings.admin_email == "admin@example.com"
    assert settings.cookie_secure is False
    assert settings.auto_create_tables is True
    assert settings.jwt_ttl_seconds == 604800
    get_settings.cache_clear()


def test_settings_require_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-pass-123")
    get_settings.cache_clear()
    with pytest.raises(Exception):
        Settings(_env_file=None)
    get_settings.cache_clear()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && pytest tests/test_config.py -v
```

Expected: FAIL，`app.config` 不存在

- [ ] **Step 3: 实现配置**

```python
# backend/app/config.py
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://pan:pan@localhost:5432/pan"
    jwt_secret: str
    jwt_ttl_seconds: int = 604800
    cookie_secure: bool = False
    admin_email: str
    admin_password: str
    auto_create_tables: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd backend && pytest tests/test_config.py -v
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/tests/test_config.py
git commit -m "$(cat <<'EOF'
feat: load runtime settings from the environment

EOF
)"
```

---

### Task 3: 用户模型和会话

**Files:**
- Create: `backend/app/models.py`
- Create: `backend/app/db.py`
- Test: `backend/tests/test_models.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_models.py
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import User


def test_user_round_trip():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    expires = datetime(2026, 10, 1, tzinfo=timezone.utc)
    with Session(engine) as session:
        session.add(
            User(
                email="user@example.com",
                password_hash="hash",
                role="user",
                plan="paid",
                plan_expires_at=expires,
            )
        )
        session.commit()
        saved = session.query(User).filter_by(email="user@example.com").one()
        assert saved.role == "user"
        assert saved.plan == "paid"
        assert saved.plan_expires_at is not None
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && pytest tests/test_models.py -v
```

Expected: FAIL，模块不存在

- [ ] **Step 3: 实现模型和数据库工具**

```python
# backend/app/db.py
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str):
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(database_url, connect_args=connect_args)


def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
```

```python
# backend/app/models.py
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user")
    plan: Mapped[str] = mapped_column(String(16), default="free")
    plan_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd backend && pytest tests/test_models.py -v
```

Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/db.py backend/app/models.py backend/tests/test_models.py
git commit -m "$(cat <<'EOF'
feat: add the users table

EOF
)"
```

---

### Task 4: 密码哈希

**Files:**
- Create: `backend/app/security.py`
- Test: `backend/tests/test_security.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_security.py
from app.security import hash_password, verify_password


def test_hash_verifies_same_password():
    hashed = hash_password("admin-pass-123")
    assert hashed != "admin-pass-123"
    assert verify_password("admin-pass-123", hashed) is True


def test_hash_rejects_wrong_password():
    hashed = hash_password("admin-pass-123")
    assert verify_password("other-pass-123", hashed) is False
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && pytest tests/test_security.py -v
```

Expected: FAIL，`hash_password` 不存在

- [ ] **Step 3: 实现哈希**

```python
# backend/app/security.py
import bcrypt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd backend && pytest tests/test_security.py -v
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/security.py backend/tests/test_security.py
git commit -m "$(cat <<'EOF'
feat: hash passwords with bcrypt

EOF
)"
```

---

### Task 5: 会员规则

**Files:**
- Create: `backend/app/membership.py`
- Test: `backend/tests/test_membership.py`

规则：

- `plan == "paid"` 且 `plan_expires_at` 晚于当前时间，有效等级是 `paid`。
- 到期、等级为 `free`、或付费但没有到期时间，有效等级都是 `free`。
- 管理员不靠等级绕过限制。`can_use_paid_features` 在 `role == "admin"` 时为真，否则看有效等级是不是 `paid`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_membership.py
from datetime import datetime, timezone

from app.membership import can_use_paid_features, effective_plan
from app.models import User


def _user(role: str, plan: str, expires: datetime | None) -> User:
    return User(
        email="user@example.com",
        password_hash="hash",
        role=role,
        plan=plan,
        plan_expires_at=expires,
        created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )


NOW = datetime(2026, 9, 22, tzinfo=timezone.utc)


def test_paid_before_expiry():
    user = _user("user", "paid", datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert effective_plan(user, NOW) == "paid"
    assert can_use_paid_features(user, NOW) is True


def test_paid_after_expiry_is_free():
    user = _user("user", "paid", datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert effective_plan(user, NOW) == "free"
    assert can_use_paid_features(user, NOW) is False


def test_paid_without_expiry_is_free():
    user = _user("user", "paid", None)
    assert effective_plan(user, NOW) == "free"


def test_naive_expiry_is_treated_as_utc():
    user = _user("user", "paid", datetime(2026, 10, 1))
    assert effective_plan(user, NOW) == "paid"


def test_admin_can_use_paid_features_on_free_plan():
    user = _user("admin", "free", None)
    assert effective_plan(user, NOW) == "free"
    assert can_use_paid_features(user, NOW) is True
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && pytest tests/test_membership.py -v
```

Expected: FAIL，`app.membership` 不存在

- [ ] **Step 3: 实现规则**

```python
# backend/app/membership.py
from datetime import datetime, timezone

from app.models import User


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def effective_plan(user: User, now: datetime) -> str:
    expires = as_utc(user.plan_expires_at)
    current = as_utc(now)
    if user.plan == "paid" and expires is not None and current is not None and expires > current:
        return "paid"
    return "free"


def can_use_paid_features(user: User, now: datetime) -> bool:
    return user.role == "admin" or effective_plan(user, now) == "paid"
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd backend && pytest tests/test_membership.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/membership.py backend/tests/test_membership.py
git commit -m "$(cat <<'EOF'
feat: derive the effective membership plan

EOF
)"
```

---

### Task 6: JWT

**Files:**
- Modify: `backend/app/security.py`
- Modify: `backend/tests/test_security.py`

- [ ] **Step 1: 把下面的测试追加到 `backend/tests/test_security.py`**

```python
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.security import create_access_token, decode_access_token


def test_token_contains_user_id():
    now = datetime(2026, 9, 22, tzinfo=timezone.utc)
    token = create_access_token(7, "secret", 3600, now=now)
    assert decode_access_token(token, "secret", now=now) == 7


def test_expired_token_is_rejected():
    now = datetime(2026, 9, 22, tzinfo=timezone.utc)
    token = create_access_token(7, "secret", 3600, now=now)
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, "secret", now=now + timedelta(seconds=3601))
```

保留 Task 4 已有的两个密码测试。

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && pytest tests/test_security.py -v
```

Expected: FAIL，`create_access_token` 不存在

- [ ] **Step 3: 把 `backend/app/security.py` 写成完整文件**

```python
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(user_id: int, secret: str, ttl_seconds: int, now: datetime | None = None) -> str:
    issued = now or datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "exp": issued + timedelta(seconds=ttl_seconds)}
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, secret: str, now: datetime | None = None) -> int:
    payload = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        options={"verify_exp": now is None},
    )
    if now is not None:
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        if exp <= now:
            raise jwt.ExpiredSignatureError("token expired")
    return int(payload["sub"])
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd backend && pytest tests/test_security.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/security.py backend/tests/test_security.py
git commit -m "$(cat <<'EOF'
feat: issue and verify session tokens

EOF
)"
```

---

### Task 7: 注册

**Files:**
- Create: `backend/app/schemas.py`
- Create: `backend/app/deps.py`
- Create: `backend/app/routers/auth.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/conftest.py`
- Test: `backend/tests/test_auth.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/conftest.py
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-pass-123")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("AUTO_CREATE_TABLES", "true")
    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()
```

```python
# backend/tests/test_auth.py
def test_register_sets_httponly_cookie_and_hides_password(client):
    response = client.post(
        "/api/auth/register",
        json={"email": "User@Example.com", "password": "password-123"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "user@example.com"
    assert body["role"] == "user"
    assert body["plan"] == "free"
    assert body["effective_plan"] == "free"
    assert body["paid_features"] is False
    assert "password" not in body
    assert "password_hash" not in body
    cookie = response.headers["set-cookie"]
    assert "access_token=" in cookie
    assert "HttpOnly" in cookie


def test_register_rejects_short_password(client):
    response = client.post(
        "/api/auth/register",
        json={"email": "user@example.com", "password": "short"},
    )
    assert response.status_code == 422


def test_register_rejects_duplicate_email(client):
    payload = {"email": "user@example.com", "password": "password-123"}
    assert client.post("/api/auth/register", json=payload).status_code == 201
    again = client.post("/api/auth/register", json=payload)
    assert again.status_code == 409
    assert again.json()["detail"] == "邮箱已注册"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && pytest tests/test_auth.py -v
```

Expected: FAIL，应用或路由不存在

- [ ] **Step 3: 实现注册**

```python
# backend/app/schemas.py
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    role: str
    plan: str
    effective_plan: str
    plan_expires_at: datetime | None
    paid_features: bool


class PlanUpdateIn(BaseModel):
    plan: str
    plan_expires_at: datetime | None = None
```

`EmailStr` 需要额外依赖。在 `backend/pyproject.toml` 的 dependencies 增加 `email-validator>=2.2`，然后重新 `pip install -e ".[dev]"`。

```python
# backend/app/deps.py
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import User
from app.security import decode_access_token


def get_db(request: Request):
    session: Session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_current_user(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        user_id = decode_access_token(token, settings.jwt_secret)
    except Exception:
        raise HTTPException(status_code=401, detail="未登录")
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
```

```python
# backend/app/routers/auth.py
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.deps import get_db, now_utc
from app.membership import can_use_paid_features, effective_plan
from app.models import User
from app.schemas import RegisterIn, UserOut
from app.security import create_access_token, hash_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def to_user_out(user: User, now: datetime) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        role=user.role,
        plan=user.plan,
        effective_plan=effective_plan(user, now),
        plan_expires_at=user.plan_expires_at,
        paid_features=can_use_paid_features(user, now),
    )


def set_session_cookie(response: Response, user: User, settings: Settings) -> None:
    token = create_access_token(user.id, settings.jwt_secret, settings.jwt_ttl_seconds)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.jwt_ttl_seconds,
        path="/",
    )


@router.post("/register", response_model=UserOut, status_code=201)
def register(
    payload: RegisterIn,
    response: Response,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    email = payload.email.lower()
    exists = session.scalar(select(User).where(func.lower(User.email) == email))
    if exists is not None:
        raise HTTPException(status_code=409, detail="邮箱已注册")
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        role="user",
        plan="free",
        plan_expires_at=None,
        created_at=datetime.now(timezone.utc),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    set_session_cookie(response, user, settings)
    return to_user_out(user, now_utc())
```

```python
# backend/app/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.db import Base, make_engine, make_session_factory
from app.routers import auth


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = make_engine(app.state.settings.database_url)
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    if app.state.settings.auto_create_tables:
        Base.metadata.create_all(engine)
    yield
    engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(lifespan=lifespan)
    app.state.settings = settings
    app.include_router(auth.router)
    return app
```

新增空文件 `backend/app/routers/__init__.py`。

- [ ] **Step 4: 运行测试确认通过**

```bash
cd backend && pytest tests/test_auth.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/app/schemas.py backend/app/deps.py backend/app/routers backend/app/main.py backend/tests/conftest.py backend/tests/test_auth.py
git commit -m "$(cat <<'EOF'
feat: register users with an httpOnly session cookie

EOF
)"
```

---

### Task 8: 登录、退出和当前用户

**Files:**
- Modify: `backend/app/routers/auth.py`
- Modify: `backend/tests/test_auth.py`

- [ ] **Step 1: 追加失败测试**

```python
def test_login_and_me(client):
    client.post("/api/auth/register", json={"email": "user@example.com", "password": "password-123"})
    client.post("/api/auth/logout")
    denied = client.get("/api/auth/me")
    assert denied.status_code == 401

    logged_in = client.post(
        "/api/auth/login",
        json={"email": "USER@example.com", "password": "password-123"},
    )
    assert logged_in.status_code == 200
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "user@example.com"


def test_login_rejects_bad_password(client):
    client.post("/api/auth/register", json={"email": "user@example.com", "password": "password-123"})
    response = client.post(
        "/api/auth/login",
        json={"email": "user@example.com", "password": "wrong-pass-123"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "邮箱或密码错误"


def test_login_rejects_unknown_email(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "missing@example.com", "password": "password-123"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "邮箱或密码错误"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && pytest tests/test_auth.py::test_login_and_me tests/test_auth.py::test_login_rejects_bad_password tests/test_auth.py::test_login_rejects_unknown_email -v
```

Expected: FAIL，`/api/auth/login` 返回 404 或 405

- [ ] **Step 3: 在 `backend/app/routers/auth.py` 增加登录、退出和当前用户**

从 `app.deps` 额外导入 `get_current_user`。从 `app.schemas` 额外导入 `LoginIn`。从 `app.security` 额外导入 `verify_password`。

```python
@router.post("/login", response_model=UserOut)
def login(
    payload: LoginIn,
    response: Response,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    email = payload.email.lower()
    user = session.scalar(select(User).where(func.lower(User.email) == email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    set_session_cookie(response, user, settings)
    return to_user_out(user, now_utc())


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return to_user_out(user, now_utc())
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd backend && pytest tests/test_auth.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/auth.py backend/tests/test_auth.py
git commit -m "$(cat <<'EOF'
feat: log users in and out with the session cookie

EOF
)"
```

---

### Task 9: 启动时创建管理员

**Files:**
- Create: `backend/app/bootstrap.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_bootstrap.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_bootstrap.py
def test_startup_creates_admin(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "admin-pass-123"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "admin"
    assert body["paid_features"] is True
    assert "password" not in body
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && pytest tests/test_bootstrap.py -v
```

Expected: FAIL，登录返回 401

- [ ] **Step 3: 启动时创建管理员**

```python
# backend/app/bootstrap.py
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import User
from app.security import hash_password


def ensure_admin(session: Session, settings: Settings) -> None:
    existing = session.scalar(select(User).where(User.role == "admin"))
    if existing is not None:
        return
    session.add(
        User(
            email=settings.admin_email.lower(),
            password_hash=hash_password(settings.admin_password),
            role="admin",
            plan="free",
            plan_expires_at=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    session.commit()
```

把 `backend/app/main.py` 的 lifespan 改成：

```python
from app.bootstrap import ensure_admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = make_engine(app.state.settings.database_url)
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    if app.state.settings.auto_create_tables:
        Base.metadata.create_all(engine)
    with app.state.session_factory() as session:
        ensure_admin(session, app.state.settings)
    yield
    engine.dispose()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd backend && pytest tests/test_bootstrap.py tests/test_auth.py -v
```

Expected: 全部通过。注册测试仍然创建普通用户，不把第二个用户变成管理员。

- [ ] **Step 5: Commit**

```bash
git add backend/app/bootstrap.py backend/app/main.py backend/tests/test_bootstrap.py
git commit -m "$(cat <<'EOF'
feat: seed the first admin on startup

EOF
)"
```

---

### Task 10: 管理后台修改等级

**Files:**
- Create: `backend/app/routers/admin.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_admin.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_admin.py
from datetime import datetime, timedelta, timezone


def register(client, email: str):
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password-123"},
    )
    assert response.status_code == 201
    return response.json()


def test_user_cannot_list_or_change_plans(client):
    register(client, "user@example.com")
    assert client.get("/api/admin/users").status_code == 403
    assert client.patch(
        "/api/admin/users/1",
        json={"plan": "paid", "plan_expires_at": "2026-10-01T00:00:00Z"},
    ).status_code == 403


def test_admin_sets_paid_until_expiry(client):
    user = register(client, "user@example.com")
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "admin-pass-123"},
    )
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    updated = client.patch(
        f"/api/admin/users/{user['id']}",
        json={"plan": "paid", "plan_expires_at": future},
    )
    assert updated.status_code == 200
    assert updated.json()["plan"] == "paid"
    assert updated.json()["effective_plan"] == "paid"
    assert updated.json()["paid_features"] is True

    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "user@example.com", "password": "password-123"})
    me = client.get("/api/auth/me")
    assert me.json()["effective_plan"] == "paid"
    assert me.json()["paid_features"] is True


def test_expired_paid_user_is_free(client):
    user = register(client, "user@example.com")
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "admin-pass-123"},
    )
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    updated = client.patch(
        f"/api/admin/users/{user['id']}",
        json={"plan": "paid", "plan_expires_at": past},
    )
    assert updated.status_code == 200
    assert updated.json()["plan"] == "paid"
    assert updated.json()["effective_plan"] == "free"
    assert updated.json()["paid_features"] is False


def test_paid_without_expiry_is_rejected(client):
    user = register(client, "user@example.com")
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "admin-pass-123"},
    )
    response = client.patch(f"/api/admin/users/{user['id']}", json={"plan": "paid"})
    assert response.status_code == 422


def test_setting_free_clears_expiry(client):
    user = register(client, "user@example.com")
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "admin-pass-123"},
    )
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    client.patch(
        f"/api/admin/users/{user['id']}",
        json={"plan": "paid", "plan_expires_at": future},
    )
    cleared = client.patch(
        f"/api/admin/users/{user['id']}",
        json={"plan": "free", "plan_expires_at": future},
    )
    assert cleared.status_code == 200
    assert cleared.json()["plan"] == "free"
    assert cleared.json()["plan_expires_at"] is None
    assert cleared.json()["effective_plan"] == "free"


def test_unauthenticated_admin_route_is_rejected(client):
    assert client.get("/api/admin/users").status_code == 401
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && pytest tests/test_admin.py -v
```

Expected: FAIL，`/api/admin/users` 不存在

- [ ] **Step 3: 实现管理接口**

```python
# backend/app/routers/admin.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_db, now_utc, require_admin
from app.membership import as_utc
from app.models import User
from app.routers.auth import to_user_out
from app.schemas import PlanUpdateIn, UserOut

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
def list_users(session: Session = Depends(get_db), _: User = Depends(require_admin)):
    now = now_utc()
    users = session.scalars(select(User).order_by(User.id)).all()
    return [to_user_out(user, now) for user in users]


@router.patch("/users/{user_id}", response_model=UserOut)
def update_plan(
    user_id: int,
    payload: PlanUpdateIn,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    if payload.plan not in {"free", "paid"}:
        raise HTTPException(status_code=422, detail="等级只能是 free 或 paid")
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if payload.plan == "paid":
        expires = as_utc(payload.plan_expires_at)
        if expires is None:
            raise HTTPException(status_code=422, detail="付费等级必须填写到期时间")
        user.plan = "paid"
        user.plan_expires_at = expires
    else:
        user.plan = "free"
        user.plan_expires_at = None
    session.commit()
    session.refresh(user)
    return to_user_out(user, now_utc())
```

在 `create_app` 里增加：

```python
from app.routers import admin, auth

app.include_router(auth.router)
app.include_router(admin.router)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd backend && pytest tests/test_admin.py tests/test_auth.py tests/test_bootstrap.py -v
```

Expected: 全部通过。普通用户访问管理接口得到 403，未登录得到 401。响应里没有 `password_hash`。

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/admin.py backend/app/main.py backend/tests/test_admin.py
git commit -m "$(cat <<'EOF'
feat: let an admin set membership expiry

EOF
)"
```

---

### Task 11: PostgreSQL 迁移和本地运行

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/versions/001_users.py`
- Create: `backend/Dockerfile`
- Create: `docker-compose.yml`
- Create: `backend/.env.example`

- [ ] **Step 1: 写迁移**

`backend/alembic.ini`：

```ini
[alembic]
script_location = alembic
sqlalchemy.url = postgresql+psycopg://pan:pan@localhost:5432/pan

[loggers]
keys = root
[handlers]
keys = console
[formatters]
keys = generic
[logger_root]
level = WARN
handlers = console
[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic
[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

`backend/alembic/env.py`：

```python
from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.db import Base
from app.models import User  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

`backend/alembic/versions/001_users.py`：

```python
"""create users

Revision ID: 001_users
Revises:
Create Date: 2026-09-22
"""

from alembic import op
import sqlalchemy as sa

revision = "001_users"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("plan", sa.String(length=16), nullable=False),
        sa.Column("plan_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)


def downgrade():
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
```

创建空文件 `backend/alembic/script.py.mako` 不是必须的，因为迁移文件已经手写。不要运行 `alembic revision --autogenerate` 覆盖这份文件。

- [ ] **Step 2: 写运行文件**

`backend/.env.example`：

```env
DATABASE_URL=postgresql+psycopg://pan:pan@db:5432/pan
JWT_SECRET=replace-me
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=admin-pass-123
COOKIE_SECURE=false
AUTO_CREATE_TABLES=false
```

`backend/Dockerfile`：

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY . .
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000"]
```

`docker-compose.yml`：

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: pan
      POSTGRES_PASSWORD: pan
      POSTGRES_DB: pan
    ports:
      - "5432:5432"
    volumes:
      - pan_pg:/var/lib/postgresql/data
  api:
    build: ./backend
    environment:
      DATABASE_URL: postgresql+psycopg://pan:pan@db:5432/pan
      JWT_SECRET: dev-secret-change-me
      ADMIN_EMAIL: admin@example.com
      ADMIN_PASSWORD: admin-pass-123
      COOKIE_SECURE: "false"
      AUTO_CREATE_TABLES: "false"
    ports:
      - "8000:8000"
    depends_on:
      - db

volumes:
  pan_pg:
```

- [ ] **Step 3: 跑全部后端测试**

```bash
cd backend && pytest -v
```

Expected: 全部通过。这一步不要求本机已经启动 Docker。

- [ ] **Step 4: Commit**

```bash
git add backend/alembic.ini backend/alembic backend/Dockerfile backend/.env.example docker-compose.yml
git commit -m "$(cat <<'EOF'
chore: run the API against PostgreSQL

EOF
)"
```

---

### Task 12: 登录、注册和管理页面

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/api.ts`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/pages/LoginPage.tsx`
- Create: `frontend/src/pages/RegisterPage.tsx`
- Create: `frontend/src/pages/AdminUsersPage.tsx`

- [ ] **Step 1: 建立前端工程**

`frontend/package.json`：

```json
{
  "name": "pan-tools-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build"
  },
  "dependencies": {
    "antd": "^5.22.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.28.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.4",
    "typescript": "^5.6.3",
    "vite": "^6.0.0"
  }
}
```

`frontend/vite.config.ts`：

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
```

`frontend/tsconfig.json`：

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "skipLibCheck": true,
    "noEmit": true
  },
  "include": ["src"]
}
```

`frontend/index.html`：

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <title>网盘工具</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 2: 写 API 和页面**

`frontend/src/api.ts`：

```ts
export type User = {
  id: number;
  email: string;
  role: string;
  plan: string;
  effective_plan: string;
  plan_expires_at: string | null;
  paid_features: boolean;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    credentials: "include",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "请求失败" }));
    throw new Error(typeof body.detail === "string" ? body.detail : "请求失败");
  }
  return response.json();
}

export const api = {
  register: (email: string, password: string) =>
    request<User>("/api/auth/register", { method: "POST", body: JSON.stringify({ email, password }) }),
  login: (email: string, password: string) =>
    request<User>("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  me: () => request<User>("/api/auth/me"),
  users: () => request<User[]>("/api/admin/users"),
  updatePlan: (id: number, plan: string, planExpiresAt: string | null) =>
    request<User>(`/api/admin/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ plan, plan_expires_at: planExpiresAt }),
    }),
};
```

`frontend/src/main.tsx`：

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
```

`frontend/src/pages/LoginPage.tsx`：

```tsx
import { Button, Form, Input, Typography, message } from "antd";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";

export default function LoginPage() {
  const navigate = useNavigate();
  return (
    <Form
      style={{ maxWidth: 360, margin: "80px auto" }}
      onFinish={async (values: { email: string; password: string }) => {
        try {
          const user = await api.login(values.email, values.password);
          navigate(user.role === "admin" ? "/admin/users" : "/");
        } catch (error) {
          message.error(error instanceof Error ? error.message : "登录失败");
        }
      }}
    >
      <Typography.Title level={3}>登录</Typography.Title>
      <Form.Item name="email" rules={[{ required: true, type: "email" }]}>
        <Input placeholder="邮箱" />
      </Form.Item>
      <Form.Item name="password" rules={[{ required: true, min: 8 }]}>
        <Input.Password placeholder="密码" />
      </Form.Item>
      <Button type="primary" htmlType="submit" block>
        登录
      </Button>
      <Link to="/register">注册</Link>
    </Form>
  );
}
```

`frontend/src/pages/RegisterPage.tsx`：

```tsx
import { Button, Form, Input, Typography, message } from "antd";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";

export default function RegisterPage() {
  const navigate = useNavigate();
  return (
    <Form
      style={{ maxWidth: 360, margin: "80px auto" }}
      onFinish={async (values: { email: string; password: string }) => {
        try {
          await api.register(values.email, values.password);
          navigate("/");
        } catch (error) {
          message.error(error instanceof Error ? error.message : "注册失败");
        }
      }}
    >
      <Typography.Title level={3}>注册</Typography.Title>
      <Form.Item name="email" rules={[{ required: true, type: "email" }]}>
        <Input placeholder="邮箱" />
      </Form.Item>
      <Form.Item name="password" rules={[{ required: true, min: 8 }]}>
        <Input.Password placeholder="至少 8 位密码" />
      </Form.Item>
      <Button type="primary" htmlType="submit" block>
        注册
      </Button>
      <Link to="/login">已有账号</Link>
    </Form>
  );
}
```

`frontend/src/pages/AdminUsersPage.tsx`：

```tsx
import { Button, DatePicker, Select, Space, Table, message } from "antd";
import type { Dayjs } from "dayjs";
import { useEffect, useState } from "react";
import { api, type User } from "../api";

export default function AdminUsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [expiry, setExpiry] = useState<Record<number, Dayjs | null>>({});

  async function load() {
    setUsers(await api.users());
  }

  useEffect(() => {
    load().catch((error: Error) => message.error(error.message));
  }, []);

  return (
    <Table
      rowKey="id"
      dataSource={users}
      columns={[
        { title: "邮箱", dataIndex: "email" },
        { title: "角色", dataIndex: "role" },
        { title: "等级", dataIndex: "plan" },
        { title: "当前有效", dataIndex: "effective_plan" },
        {
          title: "调整",
          render: (_, user) => (
            <Space>
              <DatePicker
                showTime
                onChange={(value) => setExpiry({ ...expiry, [user.id]: value })}
              />
              <Select
                defaultValue={user.plan}
                style={{ width: 100 }}
                options={[
                  { value: "free", label: "免费" },
                  { value: "paid", label: "付费" },
                ]}
                onChange={async (plan) => {
                  try {
                    const selected = expiry[user.id];
                    await api.updatePlan(user.id, plan, plan === "paid" ? selected?.toISOString() ?? null : null);
                    await load();
                  } catch (error) {
                    message.error(error instanceof Error ? error.message : "保存失败");
                  }
                }}
              />
            </Space>
          ),
        },
      ]}
    />
  );
}
```

`dayjs` 是 Ant Design DatePicker 的依赖。在 `frontend/package.json` 的 dependencies 中加入 `"dayjs": "^1.11.13"`。

`frontend/src/App.tsx`：

```tsx
import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { Button, Layout, Typography } from "antd";
import { api, type User } from "./api";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import AdminUsersPage from "./pages/AdminUsersPage";

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    api.me().then(setUser).catch(() => setUser(null));
  }, []);

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Layout.Header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Typography.Text style={{ color: "white" }}>网盘工具</Typography.Text>
        {user ? (
          <Button
            onClick={async () => {
              await api.logout();
              setUser(null);
              navigate("/login");
            }}
          >
            退出
          </Button>
        ) : null}
      </Layout.Header>
      <Layout.Content>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/admin/users" element={user?.role === "admin" ? <AdminUsersPage /> : <Navigate to="/login" />} />
          <Route path="/" element={<Typography.Paragraph style={{ padding: 24 }}>{user ? `已登录：${user.email}（${user.effective_plan}）` : "请登录"}</Typography.Paragraph>} />
        </Routes>
      </Layout.Content>
    </Layout>
  );
}
```

- [ ] **Step 3: 安装并构建**

```bash
cd frontend && npm install && npm run build
```

Expected: 构建成功，没有 TypeScript 错误。

- [ ] **Step 4: 手工核对页面**

先启动数据库和 API：

```bash
docker compose up --build
```

另开一个终端：

```bash
cd frontend && npm run dev
```

打开 `http://localhost:5173`：

1. 用 `admin@example.com` / `admin-pass-123` 登录，进入 `/admin/users`。
2. 注册一个普通用户。
3. 管理员把该用户改成付费并选择未来的到期时间，列表里的「当前有效」变成 `paid`。
4. 把到期时间改成过去，或改回免费后，「当前有效」变成 `free`。
5. 普通用户打开 `/admin/users` 会回到登录页。

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "$(cat <<'EOF'
feat: add login, registration, and admin plan screens

EOF
)"
```

---

## 规格覆盖

本计划覆盖：

- 邮箱注册、登录、退出、HttpOnly Cookie
- 第一个管理员由环境变量创建
- 管理员修改免费或付费，以及到期时间
- 到期后有效等级变为免费
- 管理员可以使用付费功能；这个判断通过 `can_use_paid_features` 留给后续接口
- 页面 `/login`、`/register`、`/admin/users`

本计划明确不做：

- 百度 Cookie、转存额度、分享、导出、同步、快照、排行
- Worker、网盘适配器、前端的转存和数据页面

后续计划按规格里的实现顺序继续：百度账号绑定、批量转存、批量分享导出、数据查询。

## 自检

- 规格第 1 步的每条行为都有对应测试：注册、登录、未登录 401、非管理员 403、付费到期变免费、付费必须带到期时间。
- 没有把百度或额度写进本计划。
- `effective_plan`、`can_use_paid_features`、`UserOut` 在后面的任务里使用的是 Task 5 和 Task 7 定义的名字。
