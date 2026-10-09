import { useEffect, useRef, useState } from "react";
import { api, type PanAccount } from "../api";
import PageHeader from "../components/PageHeader";

const providerName: Record<string, string> = { baidu: "百度", quark: "夸克", xunlei: "迅雷" };

function statusName(status: string) {
  if (status === "valid") return "有效";
  if (status === "expired") return "已失效";
  return status;
}

function loginHint(provider: "baidu" | "quark", status: string, nickname: string | null) {
  const name = provider === "quark" ? "夸克" : "百度";
  if (status === "scanned") return "扫码成功，请在手机上点确认";
  if (status === "ready") return `已登录「${nickname ?? `${name}账号`}」`;
  if (status === "expired") return "二维码已过期，请重新发起";
  if (provider === "quark") return "打开夸克 App 扫码登录";
  return "打开百度网盘 App，点首页右上角「扫一扫」";
}

function PanLoginDialog({
  provider,
  accountId,
  onClose,
  onDone,
}: {
  provider: "baidu" | "quark";
  accountId?: number;
  onClose: () => void;
  onDone: () => void;
}) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [status, setStatus] = useState("waiting");
  const [nickname, setNickname] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const sessionRef = useRef<string | null>(null);

  useEffect(() => {
    let stopped = false;
    let timer = 0;

    async function poll(id: string) {
      try {
        const next = await api.panLoginStatus(provider, id);
        if (stopped) return;
        setStatus(next.status);
        setNickname(next.nickname);
        if (next.status === "waiting" || next.status === "scanned") {
          timer = window.setTimeout(() => poll(id), 2000);
        }
      } catch (caught) {
        if (!stopped) setError(caught instanceof Error ? caught.message : "登录失败");
      }
    }

    api
      .startPanLogin(provider, accountId)
      .then((started) => {
        if (stopped) {
          void api.cancelPanLogin(provider, started.id);
          return;
        }
        sessionRef.current = started.id;
        setSessionId(started.id);
        return poll(started.id);
      })
      .catch((caught: Error) => {
        if (!stopped) setError(caught.message);
      });

    return () => {
      stopped = true;
      window.clearTimeout(timer);
      if (sessionRef.current) void api.cancelPanLogin(provider, sessionRef.current);
    };
  }, [accountId, provider]);

  async function confirm() {
    if (!sessionRef.current) return;
    setPending(true);
    setError("");
    const id = sessionRef.current;
    sessionRef.current = null;
    try {
      await api.confirmPanLogin(provider, id);
      onDone();
    } catch (caught) {
      sessionRef.current = id;
      setError(caught instanceof Error ? caught.message : "绑定失败");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="fixed inset-0 z-20 grid place-items-center bg-ink/45 px-4 backdrop-blur-[2px]" role="presentation" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="pan-login-title"
        className="w-full max-w-md rounded-2xl border border-line bg-white p-6"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="pan-login-title" className="text-xl font-semibold">
          {provider === "quark" ? "登录夸克网盘" : "登录百度网盘"}
        </h2>
        <p className="mt-2 text-sm leading-6 text-ink/65">{loginHint(provider, status, nickname)}</p>
        {sessionId && status !== "ready" && status !== "expired" ? (
          <div className="mx-auto mt-6 w-fit rounded-2xl border border-line bg-white p-4">
            <img
              src={`/api/accounts/${provider}/login/${sessionId}/qrcode`}
              alt={provider === "quark" ? "夸克登录二维码" : "百度登录二维码"}
              className="h-56 w-56 bg-white object-contain"
            />
          </div>
        ) : null}
        {status === "waiting" ? (
          <p className="mt-4 text-sm leading-6 text-ink/65">
            请用百度网盘 App 首页右上角的扫一扫。如果提示「不支持在网盘内访问」，回到网盘首页，用右上角扫一扫再扫一次。
          </p>
        ) : null}
        {error ? <p className="alert mt-4">{error}</p> : null}
        <div className="mt-6 flex justify-end gap-3">
          <button type="button" onClick={onClose} className="btn btn-secondary">
            取消
          </button>
          <button
            type="button"
            disabled={status !== "ready" || pending}
            onClick={confirm}
            className="btn btn-primary"
          >
            {pending ? "正在绑定" : "确认绑定"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<PanAccount[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [loginFor, setLoginFor] = useState<{ provider: "baidu" | "quark"; accountId?: number } | null>(null);
  const [cookieProvider, setCookieProvider] = useState<"baidu" | "quark">("baidu");
  const [cookie, setCookie] = useState("");
  const [cookiePending, setCookiePending] = useState(false);

  async function load() {
    setAccounts(await api.accounts());
  }

  useEffect(() => {
    load()
      .catch((caught: Error) => setError(caught.message))
      .finally(() => setLoaded(true));
  }, []);

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="网盘账号"
        description="点击绑定后扫码登录。登录成功并确认后，才会保存这个账号。也可以粘贴自己的 Cookie。"
      />

      <section className="rounded-2xl border border-line bg-white p-6">
        <h2 className="text-base font-semibold">绑定网盘</h2>
        <p className="mt-1.5 text-sm text-ink/55">不需要复制任何登录信息。</p>
        <div className="mt-5 flex flex-wrap gap-2">
          <button type="button" onClick={() => setLoginFor({ provider: "baidu" })} className="btn btn-primary">
            绑定百度
          </button>
          <button type="button" onClick={() => setLoginFor({ provider: "quark" })} className="btn btn-secondary">
            绑定夸克
          </button>
          <button type="button" disabled className="btn btn-secondary">
            迅雷 · 暂未开放
          </button>
        </div>
        <form
          className="mt-5 grid gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            setCookiePending(true);
            setError("");
            api
              .bindAccount(cookieProvider, cookie)
              .then(() => {
                setCookie("");
                return load();
              })
              .catch((caught: Error) => setError(caught.message))
              .finally(() => setCookiePending(false));
          }}
        >
          <label className="text-sm text-ink/70">
            粘贴 Cookie
            <select
              value={cookieProvider}
              onChange={(event) => setCookieProvider(event.target.value as "baidu" | "quark")}
              className="mt-1 block rounded-xl border border-line bg-white px-3 py-2"
            >
              <option value="baidu">百度</option>
              <option value="quark">夸克</option>
            </select>
          </label>
          <textarea
            value={cookie}
            onChange={(event) => setCookie(event.target.value)}
            placeholder="只在这里粘贴，页面不会再显示它"
            className="min-h-20 rounded-xl border border-line px-3 py-2 text-sm"
          />
          <button type="submit" disabled={cookiePending || !cookie.trim()} className="btn btn-secondary w-fit">
            {cookiePending ? "正在绑定" : "保存 Cookie"}
          </button>
        </form>
      </section>

      {error ? <p className="alert mt-4">{error}</p> : null}

      <section className="mt-4 space-y-3">
        {!loaded ? <p className="rounded-2xl border border-dashed border-line bg-white px-6 py-10 text-sm text-ink/50">正在加载</p> : null}
        {loaded && accounts.length === 0 ? (
          <p className="rounded-2xl border border-dashed border-line bg-white px-6 py-10 text-sm text-ink/50">还没有绑定网盘账号。</p>
        ) : null}
        {accounts.map((account) => (
          <article key={account.id} className="rounded-2xl border border-line bg-white p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold">{account.nickname}</h2>
                <p className="mt-1 text-sm text-ink/55">{providerName[account.provider] ?? account.provider}</p>
              </div>
              <span className="rounded-full bg-muted px-3 py-1 text-xs font-semibold text-ink">{statusName(account.status)}</span>
            </div>
            {account.provider === "baidu" || account.provider === "quark" ? (
              <button
                type="button"
                onClick={() => setLoginFor({ provider: account.provider === "quark" ? "quark" : "baidu", accountId: account.id })}
                className="btn btn-secondary mt-4"
              >
                重新登录
              </button>
            ) : null}
          </article>
        ))}
      </section>

      {loginFor !== null ? (
        <PanLoginDialog
          provider={loginFor.provider}
          accountId={loginFor.accountId}
          onClose={() => setLoginFor(null)}
          onDone={() => {
            setLoginFor(null);
            load().catch((caught: Error) => setError(caught.message));
          }}
        />
      ) : null}
    </div>
  );
}
