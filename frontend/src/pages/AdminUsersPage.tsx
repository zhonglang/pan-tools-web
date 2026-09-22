import { useEffect, useState } from "react";
import { api, type User } from "../api";

function formatExpiry(value: string | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function Badge({ children, tone }: { children: string; tone: "ink" | "paid" | "free" }) {
  const styles = {
    ink: "bg-muted text-ink",
    paid: "bg-teal-100 text-primary-dark",
    free: "bg-orange-50 text-accent",
  }[tone];
  return <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${styles}`}>{children}</span>;
}

export default function AdminUsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [expiry, setExpiry] = useState<Record<number, string>>({});
  const [error, setError] = useState("");
  const [pendingId, setPendingId] = useState<number | null>(null);

  async function load() {
    setUsers(await api.users());
  }

  useEffect(() => {
    load().catch((caught: Error) => setError(caught.message));
  }, []);

  async function save(user: User, plan: "free" | "paid") {
    setPendingId(user.id);
    setError("");
    try {
      const selected = expiry[user.id];
      await api.updatePlan(user.id, plan, plan === "paid" ? (selected ? new Date(selected).toISOString() : null) : null);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setPendingId(null);
    }
  }

  return (
    <div className="mx-auto max-w-6xl">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-primary-dark">管理</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">会员</h1>
          <p className="mt-2 text-sm text-ink/65">开通付费时必须填写到期时间。改回免费会清掉到期时间。</p>
        </div>
        <p className="text-sm text-ink/55">{users.length} 个账号</p>
      </div>
      {error ? <p className="mt-4 rounded-2xl bg-red-50 px-4 py-3 text-sm text-danger">{error}</p> : null}
      <div className="mt-6 overflow-hidden rounded-3xl border border-line bg-white">
        <div className="overflow-x-auto">
          <table className="min-w-[860px] w-full text-left text-sm">
            <thead className="bg-canvas text-xs uppercase tracking-wide text-ink/50">
              <tr>
                <th className="px-5 py-4 font-medium">账号</th>
                <th className="px-5 py-4 font-medium">角色</th>
                <th className="px-5 py-4 font-medium">等级</th>
                <th className="px-5 py-4 font-medium">到期</th>
                <th className="px-5 py-4 font-medium">调整</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id} className="border-t border-line">
                  <td className="px-5 py-4">
                    <div className="font-medium">{user.email}</div>
                    <div className="mt-1 text-xs text-ink/45">#{user.id}</div>
                  </td>
                  <td className="px-5 py-4">
                    <Badge tone="ink">{user.role === "admin" ? "管理员" : "用户"}</Badge>
                  </td>
                  <td className="px-5 py-4">
                    <div className="flex flex-col items-start gap-2">
                      <Badge tone={user.plan === "paid" ? "paid" : "free"}>{user.plan === "paid" ? "付费" : "免费"}</Badge>
                      <span className="text-xs text-ink/50">有效：{user.effective_plan === "paid" ? "付费" : "免费"}</span>
                    </div>
                  </td>
                  <td className="px-5 py-4 text-ink/70">{formatExpiry(user.plan_expires_at)}</td>
                  <td className="px-5 py-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        type="datetime-local"
                        aria-label={`${user.email} 的到期时间`}
                        value={expiry[user.id] ?? ""}
                        onChange={(event) => setExpiry({ ...expiry, [user.id]: event.target.value })}
                        className="rounded-xl border border-line bg-canvas px-3 py-2 text-xs"
                      />
                      <button
                        type="button"
                        disabled={pendingId === user.id}
                        onClick={() => save(user, "paid")}
                        className="rounded-full bg-primary px-3 py-2 text-xs font-semibold text-white hover:bg-primary-dark disabled:opacity-60"
                      >
                        开通付费
                      </button>
                      <button
                        type="button"
                        disabled={pendingId === user.id}
                        onClick={() => save(user, "free")}
                        className="rounded-full border border-line px-3 py-2 text-xs font-semibold text-ink hover:border-ink"
                      >
                        改回免费
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
