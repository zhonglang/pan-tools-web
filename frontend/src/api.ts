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

  files: (accountId: number, dir: string) =>
    request<DirEntry[]>(`/api/accounts/${accountId}/files?dir=${encodeURIComponent(dir)}`),
  createTransfer: (accountId: number, directory: string, links: string) =>
    request<Job>("/api/transfers", {
      method: "POST",
      body: JSON.stringify({ account_id: accountId, directory, links }),
    }),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
};
