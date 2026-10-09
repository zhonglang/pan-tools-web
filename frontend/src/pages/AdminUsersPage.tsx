import { useEffect, useState } from "react";
import { api, type User } from "../api";
import PageHeader from "../components/PageHeader";
import TableLoading from "../components/TableLoading";
import TablePager, { PAGE_SIZE, pageOf } from "../components/TablePager";

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
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [loaded, setLoaded] = useState(false);
  const paged = pageOf(users, page, pageSize);

  async function load() {
    setUsers(await api.users());
  }

  useEffect(() => {
    load()
      .catch((caught: Error) => setError(caught.message))
      .finally(() => setLoaded(true));
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
    <div>
      <PageHeader
        title="会员"
        description="开通付费时必须填写到期时间。改回免费会清掉到期时间。"
        extra={<p className="text-sm text-ink/50">{users.length} 个账号</p>}
      />
      {error ? <p className="alert mb-4">{error}</p> : null}
      <div className="overflow-hidden rounded-2xl border border-line bg-white">
        <div className="overflow-x-auto">
          <table className="min-w-[860px] w-full text-left text-sm">
            <thead className="bg-canvas text-[12px] text-ink/50">
              <tr>
                <th className="px-5 py-4 font-medium">账号</th>
                <th className="px-5 py-4 font-medium">角色</th>
                <th className="px-5 py-4 font-medium">等级</th>
                <th className="px-5 py-4 font-medium">到期</th>
                <th className="px-5 py-4 font-medium">调整</th>
              </tr>
            </thead>
            <tbody>
              {!loaded ? <TableLoading colSpan={5} /> : null}
              {paged.rows.map((user) => (
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
                        className="h-9 rounded-lg border border-line bg-white px-3 text-xs"
                      />
                      <button
                        type="button"
                        disabled={pendingId === user.id}
                        onClick={() => save(user, "paid")}
                        className="h-9 rounded-lg bg-accent px-3 text-xs font-bold text-white hover:bg-[#c2410c] disabled:opacity-60"
                      >
                        开通付费
                      </button>
                      <button
                        type="button"
                        disabled={pendingId === user.id}
                        onClick={() => save(user, "free")}
                        className="h-9 rounded-lg border border-line bg-white px-3 text-xs font-semibold text-ink hover:bg-canvas"
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
        <TablePager
          page={paged.page}
          total={users.length}
          pageSize={pageSize}
          onPage={setPage}
          onPageSize={(size) => {
            setPageSize(size);
            setPage(1);
          }}
        />
      </div>
    </div>
  );
}
