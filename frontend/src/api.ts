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
};

export type DirEntry = {
  name: string;
  path: string;
  is_dir: boolean;
  size: number | null;
  modified_at: number | null;
  fs_id: number | null;
};

export type ShareLink = { url: string; password: string };

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
  downloads: number | null;
};

export type TransferLine = {
  account_id: number;
  account_name: string;
  values: Array<number | null>;
};

export type CreatedShares = {
  page: number;
  page_size: number;
  total: number;
  rows: RankRow[];
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

export type JobSummary = {
  id: number;
  type: string;
  status: string;
  directory: string;
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
  startBaiduLogin: (accountId?: number) =>
    request<{ id: string; status: string; nickname: string | null }>("/api/accounts/baidu/login", {
      method: "POST",
      body: JSON.stringify({ account_id: accountId ?? null }),
    }),
  baiduLoginStatus: (id: string) =>
    request<{ id: string; status: string; nickname: string | null }>(`/api/accounts/baidu/login/${id}`),
  confirmBaiduLogin: (id: string) =>
    request<PanAccount>(`/api/accounts/baidu/login/${id}/confirm`, { method: "POST" }),
  cancelBaiduLogin: (id: string) =>
    request<{ ok: boolean }>(`/api/accounts/baidu/login/${id}`, { method: "DELETE" }),
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
  shareFile: (accountId: number, fsId: number) =>
    request<ShareLink>(`/api/accounts/${accountId}/files/share`, {
      method: "POST",
      body: JSON.stringify({ fs_id: fsId }),
    }),
  downloadFile: (accountId: number, path: string, onError: (message: string) => void) => {
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
    anchor.href = `/api/accounts/${accountId}/files/download?path=${encodeURIComponent(path)}`;
    anchor.target = iframe.name;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => iframe.remove(), 120000);
  },
  createTransfer: (accountId: number, directory: string, links: string) =>
    request<Job>("/api/transfers", {
      method: "POST",
      body: JSON.stringify({ account_id: accountId, directory, links }),
    }),
  createShare: (
    accountId: number,
    directory: string,
    targets: { fs_id: number; path: string; name: string }[],
    period: number,
    password: string | null,
  ) =>
    request<Job>("/api/shares", {
      method: "POST",
      body: JSON.stringify({ account_id: accountId, directory, targets, period, password }),
    }),
  startDownload: (accountId: number, path: string) =>
    request<DownloadTask>(`/api/accounts/${accountId}/files/save`, {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  downloads: () => request<DownloadTask[]>("/api/downloads"),
  cancelDownload: (id: number) => request<DownloadTask>(`/api/downloads/${id}/cancel`, { method: "POST" }),
  jobs: () => request<JobSummary[]>("/api/jobs"),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  syncAccount: (accountId: number) => request<Job>(`/api/accounts/${accountId}/sync`, { method: "POST" }),
  statsQuery: (accountId: number | null, rank: string, page: number, pageSize: number, start: string | null, end: string | null) => {
    const params = new URLSearchParams({ rank, page: String(page), page_size: String(pageSize) });
    if (accountId != null) params.set("account_id", String(accountId));
    if (start && end) {
      params.set("start", start);
      params.set("end", end);
    }
    return request<AccountStats>(`/api/stats?${params}`);
  },
  createdShares: (page: number, pageSize: number, start: string, end: string) => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
      start,
      end,
    });
    return request<CreatedShares>(`/api/stats/created?${params}`);
  },
};
