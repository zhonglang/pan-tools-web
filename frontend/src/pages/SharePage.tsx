import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type DirEntry, type PanAccount, type User } from "../api";
import PageHeader from "../components/PageHeader";
import UpgradeContact from "../components/UpgradeContact";
import TableLoading from "../components/TableLoading";
import TablePager, { PAGE_SIZE, pageOf } from "../components/TablePager";

function parentOf(directory: string) {
  if (directory === "/") return null;
  const parent = directory.slice(0, directory.lastIndexOf("/"));
  return parent || "/";
}

export default function SharePage({ user }: { user: User }) {
  const navigate = useNavigate();
  const [accounts, setAccounts] = useState<PanAccount[]>([]);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [directory, setDirectory] = useState("/");
  const [entries, setEntries] = useState<DirEntry[]>([]);
  const [selected, setSelected] = useState<Record<string, DirEntry>>({});
  const [period, setPeriod] = useState(0);
  const [shared, setShared] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [trail, setTrail] = useState<{ name: string; path: string }[]>([{ name: "根目录", path: "/" }]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [loading, setLoading] = useState(false);
  const paged = pageOf(entries, page, pageSize);
  const account = accounts.find((item) => item.id === accountId) ?? null;

  function openDirectory(path: string, name?: string) {
    setDirectory(path);
    if (account?.provider !== "quark") return;
    setTrail((current) => {
      const index = current.findIndex((item) => item.path === path);
      if (index >= 0) return current.slice(0, index + 1);
      return [...current, { name: name || "文件夹", path }];
    });
  }

  useEffect(() => {
    api
      .accounts()
      .then((rows) => {
        const drives = rows.filter((row) => (row.provider === "baidu" || row.provider === "quark") && row.status === "valid");
        setAccounts(drives);
        setAccountId(drives[0]?.id ?? null);
      })
      .catch((caught: Error) => setError(caught.message));
  }, []);

  useEffect(() => {
    if (!user.paid_features || accountId == null) return;
    let cancelled = false;
    setLoading(true);
    api
      .files(accountId, directory)
      .then((rows) => {
        if (!cancelled) setEntries(rows);
      })
      .catch((caught: Error) => {
        if (!cancelled) setError(caught.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [accountId, directory, user.paid_features]);

  useEffect(() => {
    setPage(1);
  }, [accountId, directory]);

  function toggle(entry: DirEntry) {
    setSelected((current) => {
      const next = { ...current };
      if (next[entry.path]) delete next[entry.path];
      else next[entry.path] = entry;
      return next;
    });
  }

  const chosen = Object.values(selected).filter((entry) => {
    const parent = entry.path.slice(0, entry.path.lastIndexOf("/")) || "/";
    return parent === directory;
  });

  async function submit() {
    if (accountId == null) return;
    const targets = chosen.map((entry) => ({ fs_id: entry.fs_id, path: entry.path, name: entry.name }));
    if (targets.length === 0) {
      setError("请选择要分享的文件");
      return;
    }
    setPending(true);
    setError("");
    try {
      const job = await api.createShare(accountId, directory, targets, period, shared ? password : null);
      navigate(`/jobs/${job.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "分享失败");
    } finally {
      setPending(false);
    }
  }

  if (!user.paid_features) {
    return (
      <div>
        <PageHeader title="批量分享" description="该功能仅对付费会员开放。" />
        <UpgradeContact email={user.email} />
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="批量分享" description="只分享当前这一层勾选的文件和文件夹。默认永久有效，每条使用各自的提取码。" />
      {error ? <p className="alert mb-4">{error}</p> : null}
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <select
          className="h-10 rounded-xl border border-line bg-white px-3 text-sm"
          value={accountId ?? ""}
          onChange={(event) => {
            setAccountId(Number(event.target.value));
            setDirectory("/");
            setTrail([{ name: "根目录", path: "/" }]);
            setSelected({});
          }}
        >
          {accounts.length === 0 ? <option value="">还没有可用的网盘账号</option> : null}
          {accounts.map((account) => (
            <option key={account.id} value={account.id}>
              {account.nickname}
            </option>
          ))}
        </select>
        <button type="button" className="text-sm text-primary-dark" disabled={!parentOf(directory)} onClick={() => parentOf(directory) && openDirectory(parentOf(directory) as string)}>
          返回上一级
        </button>
        <span className="text-sm text-ink/60">
          {account?.provider === "quark" ? trail.map((item) => item.name).join(" / ") : directory}
        </span>
      </div>
      <div className="mt-4 overflow-hidden rounded-2xl border border-line bg-white">
        <table className="w-full min-w-[640px] border-collapse text-left text-sm">
          <thead className="bg-canvas text-[12px] text-ink/50">
            <tr>
              <th className="px-4 py-3 font-medium">选择</th>
              <th className="px-4 py-3 font-medium">名称</th>
              <th className="px-4 py-3 font-medium">类型</th>
            </tr>
          </thead>
          <tbody>
            {loading ? <TableLoading colSpan={3} /> : null}
            {!loading && entries.length === 0 ? (
              <tr>
                <td colSpan={3} className="px-4 py-10 text-center text-ink/45">
                  这个目录是空的。
                </td>
              </tr>
            ) : null}
            {!loading
              ? paged.rows.map((entry) => (
              <tr key={entry.path} className="border-t border-line">
                <td className="px-4 py-3">
                  <input type="checkbox" checked={Boolean(selected[entry.path])} onChange={() => toggle(entry)} aria-label={`选择 ${entry.name}`} />
                </td>
                <td className="px-4 py-3">
                  {entry.is_dir ? (
                    <button type="button" className="font-medium text-primary-dark" onClick={() => openDirectory(entry.path, entry.name)}>
                      {entry.name}
                    </button>
                  ) : (
                    entry.name
                  )}
                </td>
                <td className="px-4 py-3 text-ink/60">{entry.is_dir ? "文件夹" : "文件"}</td>
              </tr>
            ))
              : null}
          </tbody>
        </table>
        <TablePager
          page={paged.page}
          total={entries.length}
          pageSize={pageSize}
          onPage={setPage}
          onPageSize={(size) => {
            setPageSize(size);
            setPage(1);
          }}
        />
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-4 text-sm">
        <label className="flex items-center gap-2">
          有效期
          <select className="h-10 rounded-xl border border-line bg-white px-3" value={period} onChange={(event) => setPeriod(Number(event.target.value))}>
            <option value={0}>永久</option>
            <option value={1}>1 天</option>
            <option value={7}>7 天</option>
          </select>
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={shared} onChange={(event) => setShared(event.target.checked)} />
          所有分享共用一个提取码
        </label>
        {shared ? (
          <input
            className="h-10 w-28 rounded-xl border border-line bg-white px-3"
            value={password}
            maxLength={4}
            placeholder="4 位"
            onChange={(event) => setPassword(event.target.value)}
          />
        ) : null}
        <button
          type="button"
          disabled={pending || chosen.length === 0}
          onClick={() => void submit()}
          className="btn btn-primary disabled:opacity-50"
        >
          {pending ? "正在提交" : `分享已选 ${chosen.length} 项`}
        </button>
      </div>
    </div>
  );
}
