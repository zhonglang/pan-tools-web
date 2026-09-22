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
