export type User = {
  id: number;
  email: string;
  role: string;
  plan: string;
  effective_plan: string;
  plan_expires_at: string | null;
  paid_features: boolean;
};

export type PanAccount = {
  id: number;
  provider: string;
  nickname: string;
  status: string;
  created_at: string;
  updated_at: string;
  last_synced_at?: string | null;
};

export type DirEntry = {
  name: string;
  path: string;
  is_dir: boolean;
  size: number | null;
  created_at: number | null;
  modified_at: number | null;
  fs_id: number | null;
};

export type ShareLink = { url: string; password: string };

export type CopyTargetResult = { path: string; name: string; ok: boolean; error: string | null };
export type CopyResult = { succeeded: number; failed: number; results: CopyTargetResult[] };

export type JobItem = {
  id: number;
  status: string;
  input_text: string;
  error: string | null;
  result: string | null;
  attempts: number;
};

export type Job = {
  id: number;
  type: string;
  status: string;
  directory: string;
  directory_label: string | null;
  error: string | null;
  items: JobItem[];
};

export type Metric = { value: number | null; from_time: string | null };

export type RankRow = {
  name: string;
  account_name: string;
  url: string;
  created_at: string;
  views: number | null;
  transfers: number | null;
  transfer_delta?: number | null;
  downloads: number | null;
};

export type TransferLine = {
  account_id: number;
  account_name: string;
  values: Array<number | null>;
  kind?: "delta" | "total" | string | null;
};

export type AccountStats = {
  total: number;
  first_snapshot_at: string | null;
  range_start: string | null;
  range_end: string | null;
  new_shares: number;
  views: Metric;
  transfers: Metric;
  downloads: Metric;
  rank: string;
  page: number;
  page_size: number;
  rank_total: number;
  rows: RankRow[];
  dates: string[];
  lines: TransferLine[];
};

export type DownloadTask = {
  id: number;
  account_id: number;
  name: string;
  path: string;
  status: "running" | "done" | "failed" | "cancelled" | string;
  phase: "list" | "save" | string;
  bytes_done: number;
  bytes_total: number;
  files_done: number;
  files_total: number;
  current_name: string | null;
  directory: string | null;
  error: string | null;
  created_at: string;
};

export type UploadTask = {
  id: number;
  account_id: number;
  dest_path: string;
  name: string;
  status: "running" | "done" | "failed" | "cancelled" | string;
  bytes_done: number;
  bytes_total: number;
  files_done: number;
  files_total: number;
  current_name: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
};

export type LibraryItem = {
  id: number;
  prefix: string;
  name: string;
  xunlei_url: string;
  quark_url: string;
  baidu_url: string;
};

export type LibraryCheckHit = {
  id: number;
  prefix: string;
  name: string;
  provider: "baidu" | "quark" | "xunlei" | string;
  reason: string;
};

export type LibraryCheckResult = {
  checked: number;
  invalid: LibraryCheckHit[];
  unknown: number;
};

export type LibraryImportResult = {
  created: number;
  updated: number;
  skipped: number;
  items: LibraryItem[];
};

export type JobSummary = {
  id: number;
  type: string;
  status: string;
  directory: string;
  directory_label: string | null;
  created_at: string;
  total: number;
  succeeded: number;
  failed: number;
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

async function requestForm<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    body,
    credentials: "include",
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: "请求失败" }));
    throw new Error(typeof payload.detail === "string" ? payload.detail : "请求失败");
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
  accounts: () => request<PanAccount[]>("/api/accounts"),
  startPanLogin: (provider: "baidu" | "quark" | "xunlei", accountId?: number) =>
    request<{ id: string; status: string; nickname: string | null }>(`/api/accounts/${provider}/login`, {
      method: "POST",
      body: JSON.stringify({ account_id: accountId ?? null }),
    }),
  panLoginStatus: (provider: "baidu" | "quark" | "xunlei", id: string) =>
    request<{ id: string; status: string; nickname: string | null }>(`/api/accounts/${provider}/login/${id}`),
  confirmPanLogin: (provider: "baidu" | "quark" | "xunlei", id: string) =>
    request<PanAccount>(`/api/accounts/${provider}/login/${id}/confirm`, { method: "POST" }),
  cancelPanLogin: (provider: "baidu" | "quark" | "xunlei", id: string) =>
    request<{ ok: boolean }>(`/api/accounts/${provider}/login/${id}`, { method: "DELETE" }),
  files: (accountId: number, dir: string) =>
    request<DirEntry[]>(`/api/accounts/${accountId}/files?dir=${encodeURIComponent(dir)}`),
  createFolder: (accountId: number, directory: string, name: string) =>
    request<DirEntry>(`/api/accounts/${accountId}/folders`, {
      method: "POST",
      body: JSON.stringify({ directory, name }),
    }),
  renameFile: (accountId: number, path: string, name: string) =>
    request<{ ok: boolean }>(`/api/accounts/${accountId}/files/rename`, {
      method: "POST",
      body: JSON.stringify({ path, name }),
    }),
  deleteFile: (accountId: number, path: string) =>
    request<{ ok: boolean }>(`/api/accounts/${accountId}/files/delete`, {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  copyFiles: (
    accountId: number,
    body: { path: string; fs_id: number | null; name: string; is_dir: boolean; targets: string[] },
  ) =>
    request<CopyResult>(`/api/accounts/${accountId}/files/copy`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  shareFile: (accountId: number, body: { fs_id: number | null; path: string; name: string }) =>
    request<ShareLink>(`/api/accounts/${accountId}/files/share`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  downloadFile: (accountId: number, path: string, onError: (message: string) => void, name?: string) => {
    const iframe = document.createElement("iframe");
    iframe.name = `pan-download-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    iframe.style.display = "none";
    iframe.onload = () => {
      try {
        const text = iframe.contentDocument?.body?.innerText ?? "";
        const data = JSON.parse(text) as { detail?: unknown };
        if (typeof data.detail === "string") onError(data.detail);
      } catch {
        /* 浏览器已经开始下载 */
      }
    };
    document.body.appendChild(iframe);
    const anchor = document.createElement("a");
    const params = new URLSearchParams({ path });
    if (name) params.set("name", name);
    anchor.href = `/api/accounts/${accountId}/files/download?${params.toString()}`;
    anchor.target = iframe.name;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => iframe.remove(), 120000);
  },
  createTransfer: (accountId: number, directory: string, links: string, directoryLabel?: string | null) =>
    request<Job>("/api/transfers", {
      method: "POST",
      body: JSON.stringify({ account_id: accountId, directory, directory_label: directoryLabel || null, links }),
    }),
  sharePasswords: () =>
    request<{ baidu_password: string | null; quark_password: string | null; xunlei_password: string | null }>(
      "/api/settings/share-passwords",
    ),
  saveSharePasswords: (baiduPassword: string, quarkPassword: string, xunleiPassword: string) =>
    request<{ baidu_password: string | null; quark_password: string | null; xunlei_password: string | null }>(
      "/api/settings/share-passwords",
      {
        method: "PUT",
        body: JSON.stringify({
          baidu_password: baiduPassword.trim() || null,
          quark_password: quarkPassword.trim() || null,
          xunlei_password: xunleiPassword.trim() || null,
        }),
      },
    ),
  createShare: (
    accountId: number,
    directory: string,
    targets: { fs_id: number | null; path: string; name: string }[],
    period: number,
    visibility: "public" | "private",
    password: string | null,
    directoryLabel?: string | null,
  ) =>
    request<Job>("/api/shares", {
      method: "POST",
      body: JSON.stringify({
        account_id: accountId,
        directory,
        directory_label: directoryLabel || null,
        targets,
        period,
        visibility,
        password,
      }),
    }),
  startDownload: (accountId: number, path: string) =>
    request<DownloadTask>(`/api/accounts/${accountId}/files/save`, {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  downloads: () => request<DownloadTask[]>("/api/downloads"),
  cancelDownload: (id: number) => request<DownloadTask>(`/api/downloads/${id}/cancel`, { method: "POST" }),
  uploadFiles: (accountId: number, dest: string, files: File[]) => {
    const body = new FormData();
    body.append("dest", dest);
    for (const file of files) {
      const relative =
        (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
      body.append("relative_paths", relative);
      body.append("files", file, file.name);
    }
    return requestForm<UploadTask>(`/api/accounts/${accountId}/files/upload`, body);
  },
  uploads: () => request<UploadTask[]>("/api/uploads"),
  cancelUpload: (id: number) => request<UploadTask>(`/api/uploads/${id}/cancel`, { method: "POST" }),
  jobs: () => request<JobSummary[]>("/api/jobs"),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  syncAccount: (accountId: number) => request<Job>(`/api/accounts/${accountId}/sync`, { method: "POST" }),
  statsQuery: (
    accountId: number | null,
    page: number,
    pageSize: number,
    start: string | null,
    end: string | null,
    name?: string | null,
  ) => {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (accountId != null) params.set("account_id", String(accountId));
    if (start && end) {
      params.set("start", start);
      params.set("end", end);
    }
    if (name?.trim()) params.set("name", name.trim());
    return request<AccountStats>(`/api/stats?${params}`);
  },
  library: () => request<LibraryItem[]>("/api/library"),
  checkLibrary: () => request<LibraryCheckResult>("/api/library/check", { method: "POST" }),
  createLibrary: (body: { prefix: string; name: string; xunlei_url: string; quark_url: string; baidu_url: string }) =>
    request<LibraryItem>("/api/library", { method: "POST", body: JSON.stringify(body) }),
  importLibrary: (rows: { name: string; url: string; password: string }[]) =>
    request<LibraryImportResult>("/api/library/import", { method: "POST", body: JSON.stringify({ rows }) }),
  updateLibrary: (id: number, body: Pick<LibraryItem, "name" | "xunlei_url" | "quark_url" | "baidu_url">) =>
    request<LibraryItem>(`/api/library/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteLibrary: (id: number) => request<{ ok: boolean }>(`/api/library/${id}`, { method: "DELETE" }),
};
