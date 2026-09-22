import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type DirEntry, type PanAccount } from "../api";

export default function TransferPage() {
  const navigate = useNavigate();
  const [accounts, setAccounts] = useState<PanAccount[]>([]);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [directory, setDirectory] = useState("/");
  const [entries, setEntries] = useState<DirEntry[]>([]);
  const [links, setLinks] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    api
      .accounts()
      .then((rows) => {
        const baidu = rows.filter((row) => row.provider === "baidu" && row.status === "valid");
        setAccounts(baidu);
        setAccountId(baidu[0]?.id ?? null);
      })
      .catch((caught: Error) => setError(caught.message));
  }, []);

  useEffect(() => {
    if (accountId === null) return;
    api.files(accountId, directory).then(setEntries).catch((caught: Error) => setError(caught.message));
  }, [accountId, directory]);

  async function submit() {
    if (accountId === null) return;
    setPending(true);
    setError("");
    try {
      const job = await api.createTransfer(accountId, directory, links);
      navigate(`/jobs/${job.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "转存失败");
    } finally {
      setPending(false);
    }
  }

  const parent = directory === "/" ? null : directory.slice(0, directory.lastIndexOf("/")) || "/";

  return (
    <div className="mx-auto max-w-3xl">
      <p className="text-sm font-medium text-primary-dark">转存</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">批量转存</h1>
      <p className="mt-2 text-sm leading-6 text-ink/65">选择百度账号和目录，每行粘贴一条分享链接。一条失败不会停下其余链接。</p>
      {accounts.length === 0 ? <p className="mt-6 text-sm text-ink/60">先绑定一个有效的百度账号。</p> : null}
      {accounts.length > 0 ? (
        <div className="mt-6 space-y-4">
          <label className="block text-sm font-medium">
            百度账号
            <select
              className="mt-2 w-full rounded-2xl border border-line bg-white px-4 py-3"
              value={accountId ?? ""}
              onChange={(event) => {
                setDirectory("/");
                setAccountId(Number(event.target.value));
              }}
            >
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.nickname}
                </option>
              ))}
            </select>
          </label>
          <section className="rounded-3xl border border-line bg-white p-5">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold">保存到 {directory}</h2>
              {parent !== null ? (
                <button type="button" className="text-sm font-medium text-primary-dark" onClick={() => setDirectory(parent)}>
                  返回上一层
                </button>
              ) : null}
            </div>
            <ul className="mt-4 space-y-2">
              {entries
                .filter((entry) => entry.is_dir)
                .map((entry) => (
                  <li key={entry.path}>
                    <button type="button" className="text-sm font-medium" onClick={() => setDirectory(entry.path)}>
                      {entry.name}
                    </button>
                  </li>
                ))}
              {entries
                .filter((entry) => !entry.is_dir)
                .map((entry) => (
                  <li key={entry.path} className="text-sm text-ink/45">
                    {entry.name}
                  </li>
                ))}
            </ul>
          </section>
          <label className="block text-sm font-medium">
            分享链接
            <textarea
              className="mt-2 min-h-40 w-full rounded-2xl border border-line bg-white px-4 py-3"
              value={links}
              onChange={(event) => setLinks(event.target.value)}
              placeholder={"https://pan.baidu.com/s/1xxxx abcd"}
            />
          </label>
          {error ? <p className="rounded-2xl bg-red-50 px-4 py-3 text-sm text-danger">{error}</p> : null}
          <button
            type="button"
            disabled={pending || links.trim() === ""}
            onClick={submit}
            className="rounded-full bg-accent px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
          >
            {pending ? "正在创建" : "开始转存"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
