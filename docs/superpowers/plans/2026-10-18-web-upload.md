# Web Netdisk Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users upload local files/folders from the Transfer page to Baidu, Quark, or Xunlei via backend-mediated upload tasks with progress and cancel.

**Architecture:** Browser multipart → FastAPI creates `UploadTask` and stores temp files → daemon thread calls provider `ensure_dir` + `upload_file` → frontend polls `/api/uploads` and shows a toast (mirrors `DownloadTask` / `downloads.py`).

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, httpx adapters, React TransferPage.

**Spec:** `docs/superpowers/specs/2026-10-18-web-upload-design.md`

---

## File map

| Path | Responsibility |
|------|----------------|
| `backend/alembic/versions/013_upload_tasks.py` | Create `upload_tasks` |
| `backend/app/models/upload.py` | `UploadTask` model |
| `backend/app/schemas/upload.py` | `UploadTaskOut` |
| `backend/app/crud/uploads.py` | get / list_for_user |
| `backend/app/services/uploads.py` | start/cancel/run/interrupt; account serial lock |
| `backend/app/pans/protocol.py` or inline on adapters | `ensure_dir`, `upload_file` |
| `backend/app/pans/baidu.py` / `quark.py` / `xunlei.py` | Provider upload |
| `backend/app/api/routes/transfers.py` | upload + list + cancel routes |
| `backend/app/main.py` | call upload `interrupt_orphans` |
| `backend/tests/test_uploads.py` | orchestration + API |
| `backend/tests/test_baidu_upload.py` etc. | adapter HTTP mocks |
| `frontend/src/api.ts` | upload helpers |
| `frontend/src/pages/TransferPage.tsx` | toolbar + row upload + toast |

---

### Task 1: Migration + model + schema

**Files:**
- Create: `backend/alembic/versions/013_upload_tasks.py`
- Create: `backend/app/models/upload.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/schemas/upload.py`
- Modify: `backend/app/schemas/__init__.py`
- Create: `backend/app/crud/uploads.py`

- [ ] **Step 1: Add Alembic revision `013_upload_tasks`**

Mirror `006_download_tasks.py` columns:

```python
# upload_tasks: id, user_id, account_id, dest_path, name, status,
# bytes_done, bytes_total, files_done, files_total, current_name, error,
# created_at, updated_at
# indexes on user_id, account_id
```

`down_revision` = `"012_account_stat_days"` (confirm latest head with `cd backend && uv run alembic heads`).

- [ ] **Step 2: Model**

```python
# backend/app/models/upload.py
class UploadTask(Base):
    __tablename__ = "upload_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("pan_accounts.id"), index=True)
    dest_path: Mapped[str] = mapped_column(String(1024))
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="running")
    bytes_done: Mapped[int] = mapped_column(BigInteger, default=0)
    bytes_total: Mapped[int] = mapped_column(BigInteger, default=0)
    files_done: Mapped[int] = mapped_column(Integer, default=0)
    files_total: Mapped[int] = mapped_column(Integer, default=0)
    current_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at / updated_at  # timezone=True, same as DownloadTask
```

Export from `models/__init__.py`.

- [ ] **Step 3: Schema + CRUD**

```python
class UploadTaskOut(BaseModel):
    id: int
    account_id: int
    dest_path: str
    name: str
    status: str
    bytes_done: int
    bytes_total: int
    files_done: int
    files_total: int
    current_name: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
```

`crud/uploads.py`: `get(session, id)`, `list_for_user(session, user_id, limit=100)` ordered by id desc.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/013_upload_tasks.py backend/app/models/upload.py \
  backend/app/models/__init__.py backend/app/schemas/upload.py \
  backend/app/schemas/__init__.py backend/app/crud/uploads.py
git commit -m "feat: add upload_tasks table and model"
```

---

### Task 2: Adapter protocol — `ensure_dir` + stub `upload_file`

**Files:**
- Modify: `backend/app/pans/baidu.py`, `quark.py`, `xunlei.py`, `closed.py`
- Create: `backend/tests/test_ensure_dir.py`

Existing APIs already have `create_dir`. Add:

```python
def ensure_dir(self, cookie: str, path: str) -> None:
    """Ensure absolute pan path exists (create missing parents)."""
```

```python
def upload_file(
    self,
    cookie: str,
    dest_dir: str,
    filename: str,
    stream,
    size: int,
    *,
    on_progress=None,  # callable(bytes_delta: int) -> None
    should_stop=None,  # callable() -> bool
) -> None:
    raise NotImplementedError  # Temporary until provider tasks
```

- [ ] **Step 1: Failing test for `ensure_dir` on Baidu using mocked list/create**

For Baidu: if path is `/a/b`, create `/a` then `/a/b` when missing (use `list_dir` parent or try `create_dir` and ignore “already exists”).

- [ ] **Step 2: Implement `ensure_dir` for all three** using existing `create_dir` + list/existence checks. `ClosedAdapter`: raise `TransferFailed("不支持")`.

- [ ] **Step 3: Add `upload_file` stubs** that raise `TransferFailed("上传尚未实现")` so orchestration can land before real adapters.

- [ ] **Step 4: pytest + commit**

```bash
uv run pytest tests/test_ensure_dir.py -q
git commit -am "feat: add ensure_dir and upload_file adapter hooks"
```

---

### Task 3: Upload orchestration service (fake adapter)

**Files:**
- Create: `backend/app/services/uploads.py`
- Create: `backend/tests/test_uploads_service.py`
- Modify: `backend/app/core/config.py` — optional `upload_max_bytes: int = 4 * 1024**3`

- [ ] **Step 1: Write failing tests with a FakeAdapter**

```python
class FakeAdapter:
    def __init__(self):
        self.dirs = set()
        self.files = []  # (dest_dir, name, data)
    def ensure_dir(self, cookie, path): self.dirs.add(path)
    def upload_file(self, cookie, dest_dir, filename, stream, size, *, on_progress=None, should_stop=None):
        data = stream.read()
        if on_progress: on_progress(len(data))
        self.files.append((dest_dir, filename, data))
```

Tests:
1. `start_upload` creates running task, thread uploads one file → status `done`, bytes match
2. cancel mid-way → `cancelled` (fake sleeps / checks `should_stop`)
3. total size over limit → 422 before thread / or task `failed` with clear error — prefer reject at API later; service raises `ValueError("文件过大")`

- [ ] **Step 2: Implement `uploads.py`**

Pattern after `downloads.py`:

```python
_lock = threading.Lock()
_cancel: set[int] = set()
_account_locks: dict[int, threading.Lock] = {}

def interrupt_upload_orphans(session): ...

def start_upload(session, session_factory, client, cookie, user_id, account_id, dest_path, items: list[tuple[str, Path, int]]) -> UploadTask:
    # items: (relative_path_or_name, local_temp_path, size)
    # name = single filename or f"{root}（{n} 个文件）"
    # spawn thread _run_upload

def cancel_upload(session, task) -> UploadTask: ...

def _run_upload(...):
    with account lock:
      adapter = adapter_for(...)
      for each item:
        if cancelled: finish cancelled; return
        parent = join(dest_path, dirname(relative))
        adapter.ensure_dir(cookie, parent)
        with open(temp, "rb") as stream:
          adapter.upload_file(..., on_progress=lambda d: _bump_bytes(...), should_stop=lambda: _stopped(task_id))
        files_done += 1
        unlink temp
      finish done
```

- [ ] **Step 3: pytest pass + commit**

```bash
uv run pytest tests/test_uploads_service.py -q
git commit -am "feat: add upload task orchestration service"
```

---

### Task 4: HTTP routes

**Files:**
- Modify: `backend/app/api/routes/transfers.py`
- Modify: `backend/app/main.py` — also call `interrupt_upload_orphans`
- Modify: `backend/app/api/routes/accounts.py` — cascade delete `UploadTask` if needed (same loop as DownloadTask)
- Create: `backend/tests/test_uploads_api.py`

- [ ] **Step 1: Failing API test**

```python
def test_upload_file_creates_task(client, monkeypatch, tmp_path):
    # register + bind fake account OR monkeypatch adapter_for + decrypt
    # POST multipart to /api/accounts/{id}/files/upload with dest=/测试
    # assert 201, task running/done after short wait
```

Use existing account fixtures from `test_transfers.py` / register helpers. Monkeypatch `adapter_for` to FakeAdapter and skip real cookie verify if route decrypts cookie — mirror `files/save` auth pattern.

- [ ] **Step 2: Implement routes**

```python
@router.post("/api/accounts/{account_id}/files/upload", response_model=UploadTaskOut, status_code=201)
async def upload_files(account_id, dest: str = Form(...), files: list[UploadFile] = File(...), ...):
    # validate account ownership + membership
    # save each UploadFile to temp dir under tempfile.mkdtemp(prefix="pan-upload-")
    # relative path: prefer form field relative_paths[] aligned by index, else filename only
    # enforce total size <= settings.upload_max_bytes
    # start_upload(...)
    # return to_upload(task)

@router.get("/api/uploads", response_model=list[UploadTaskOut])
@router.post("/api/uploads/{task_id}/cancel", response_model=UploadTaskOut)
```

- [ ] **Step 3: Wire `interrupt_upload_orphans` in `main.py` lifespan next to download orphans**

- [ ] **Step 4: pytest + commit**

```bash
uv run pytest tests/test_uploads_api.py tests/test_uploads_service.py -q
git commit -am "feat: add upload HTTP API and cancel endpoint"
```

---

### Task 5: Baidu `upload_file`

**Files:**
- Modify: `backend/app/pans/baidu.py`
- Create: `backend/tests/test_baidu_upload.py`

- [ ] **Step 1: Research existing Baidu session helpers in `baidu.py`** (bdstoken, headers). Implement PCS-style flow used by pan web:

Typical steps (adjust to whatever the current cookie session already uses — prefer endpoints already proven in this codebase’s HTTP style):

1. `precreate` (path, size, block_list md5s)
2. If `return_type` indicates rapid upload / exists → done (optional)
3. Upload each 4MB slice to PCS upload endpoint
4. `create` to commit

Call `on_progress(len(chunk))` per slice; check `should_stop()` between slices → raise a small `UploadCancelled` or reuse `DownloadCancelled`-like exception caught by service.

- [ ] **Step 2: MockTransport tests** covering happy path + cancel between slices

- [ ] **Step 3: Commit**

```bash
git commit -am "feat: implement Baidu adapter upload_file"
```

---

### Task 6: Quark `upload_file`

**Files:**
- Modify: `backend/app/pans/quark.py`
- Create: `backend/tests/test_quark_upload.py`

- [ ] **Step 1: Implement using Quark drive upload hash/init/upload/finish pattern** consistent with how `quark.py` already talks to APIs (same headers/cookie). Resolve parent folder id from `dest_dir` via existing list/path helpers.

- [ ] **Step 2: httpx mock tests + commit**

```bash
git commit -am "feat: implement Quark adapter upload_file"
```

---

### Task 7: Xunlei `upload_file`

**Files:**
- Modify: `backend/app/pans/xunlei.py`
- Create: `backend/tests/test_xunlei_upload.py`

- [ ] **Step 1: Implement with Xunlei drive upload API; refresh token via existing helpers before upload**

- [ ] **Step 2: mock tests + commit**

```bash
git commit -am "feat: implement Xunlei adapter upload_file"
```

---

### Task 8: Frontend — API + TransferPage UI

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/pages/TransferPage.tsx`

- [ ] **Step 1: API helpers**

```typescript
export type UploadTask = {
  id: number;
  account_id: number;
  dest_path: string;
  name: string;
  status: string;
  bytes_done: number;
  bytes_total: number;
  files_done: number;
  files_total: number;
  current_name: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
};

uploadFiles: async (accountId: number, dest: string, files: File[]) => {
  const body = new FormData();
  body.append("dest", dest);
  for (const file of files) {
    const relative = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
    body.append("relative_paths", relative);
    body.append("files", file, file.name);
  }
  // fetch with credentials; do NOT set Content-Type (browser sets boundary)
  return requestForm<UploadTask>(`/api/accounts/${accountId}/uploads` /* or files/upload */, body);
},
uploads: () => request<UploadTask[]>("/api/uploads"),
cancelUpload: (id: number) => request<UploadTask>(`/api/uploads/${id}/cancel`, { method: "POST" }),
```

Add a `requestForm` that omits JSON Content-Type.

Route path must match Task 4: `/api/accounts/{id}/files/upload`.

- [ ] **Step 2: TransferPage UI**

- Toolbar: dropdown or split button「上传」→ hidden `<input type="file" multiple>` and `<input type="file" webkitdirectory multiple>`
- Folder row:「上传到此」triggers same pickers with `dest = entry.path`
- State `uploads: UploadTask[]`; poll every 1s while any `running`
- Toast panel (reuse download toast layout): show running uploads, progress bar `bytes_done/bytes_total`, cancel button
- On transition to `done` for task targeting current path (or always): refresh `listDir`
- Disable when `!accountId`

- [ ] **Step 3: Manual smoke checklist** (document in commit body): pick file on Baidu account in UI

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api.ts frontend/src/pages/TransferPage.tsx
git commit -m "feat: add transfer page upload entry and progress toast"
```

---

### Task 9: Hardening + acceptance

**Files:**
- Modify tests / config as needed
- Optionally short note in README — skip unless repo already documents features

- [ ] **Step 1: Reject empty file list with 422「请选择文件」**

- [ ] **Step 2: LoginRejected → task failed「登录已失效，请重新登录」**

- [ ] **Step 3: Run full relevant suite**

```bash
cd backend && uv run pytest tests/test_uploads_service.py tests/test_uploads_api.py \
  tests/test_baidu_upload.py tests/test_quark_upload.py tests/test_xunlei_upload.py \
  tests/test_ensure_dir.py -q
```

Expected: all pass

- [ ] **Step 4: Commit**

```bash
git commit -am "fix: harden upload validation and provider error mapping"
```

---

## Spec coverage

| Spec item | Task |
|-----------|------|
| Toolbar upload to current dir | 8 |
| Folder row「上传到此」 | 8 |
| File + folder relative paths | 3, 4, 8 |
| Baidu / Quark / Xunlei | 5, 6, 7 |
| Backend mediate upload | 3, 4 |
| Progress toast + cancel | 3, 4, 8 |
| 4GB limit, serial per account | 3, 4 |
| interrupt orphans | 4 |
| No task-center / pause / drag | (out of scope) |

## Out of scope

- Upload history page, pause/resume, drag-drop, CDN direct upload, desktop app
