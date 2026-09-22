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
