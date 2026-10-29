import { useEffect, useMemo, useState } from "react";
import { api, type PanAccount } from "../api";
import FolderPicker, { type FolderCrumb } from "../components/FolderPicker";
import PageHeader from "../components/PageHeader";

type DraftSource = {
  key: string;
  account_id: number | "";
  directory: string;
  label: string;
  trail: FolderCrumb[];
  is_primary?: boolean;
};

type PickerTarget = { kind: "sync" | "linked"; index: number };

function providerLabel(provider: string) {
  if (provider === "quark") return "夸克";
  if (provider === "xunlei") return "迅雷";
  return "百度";
}

function usesFileId(provider: string | undefined) {
  return provider === "quark" || provider === "xunlei";
}

function newDraft(accountId: number | "" = "", isPrimary = false): DraftSource {
  return {
    key: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    account_id: accountId,
    directory: "/",
    label: "",
    trail: [{ name: "根目录", path: "/" }],
    is_primary: isPrimary,
  };
}

function rowsToDrafts(
  rows: { id: number; account_id: number; directory: string; label: string; is_primary?: boolean }[],
): DraftSource[] {
  return rows.map((row) => ({
    key: String(row.id),
    account_id: row.account_id,
    directory: row.directory,
    label: row.label,
    is_primary: Boolean(row.is_primary),
    trail:
      row.directory === "/"
        ? [{ name: "根目录", path: "/" }]
        : [
            { name: "根目录", path: "/" },
            {
              name: row.label.split(" / ").filter(Boolean).at(-1) || "已选目录",
              path: row.directory,
            },
          ],
  }));
}

function pathLabelFor(source: DraftSource, account: PanAccount | undefined) {
  return (
    source.label ||
    (usesFileId(account?.provider)
      ? source.trail.map((item) => item.name).join(" / ") || source.directory
      : source.directory)
  );
}

type SettingsTab = "passwords" | "sync" | "linked";

const tabs: { id: SettingsTab; label: string }[] = [
  { id: "passwords", label: "默认提取码" },
  { id: "sync", label: "资源库同步" },
  { id: "linked", label: "关联重命名" },
];

export default function SettingsPage() {
  const [tab, setTab] = useState<SettingsTab>("passwords");
  const [baiduPassword, setBaiduPassword] = useState("");
  const [quarkPassword, setQuarkPassword] = useState("");
  const [xunleiPassword, setXunleiPassword] = useState("");
  const [accounts, setAccounts] = useState<PanAccount[]>([]);
  const [sources, setSources] = useState<DraftSource[]>([]);
  const [linkedMembers, setLinkedMembers] = useState<DraftSource[]>([]);
  const [picking, setPicking] = useState<PickerTarget | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const [syncSaved, setSyncSaved] = useState("");
  const [linkedSaved, setLinkedSaved] = useState("");
  const [pending, setPending] = useState(false);
  const [syncPending, setSyncPending] = useState(false);
  const [linkedPending, setLinkedPending] = useState(false);
  const [loading, setLoading] = useState(true);

  function switchTab(next: SettingsTab) {
    setTab(next);
    setError("");
    setPicking(null);
  }

  const driveAccounts = useMemo(
    () =>
      accounts.filter(
        (row) =>
          (row.provider === "baidu" || row.provider === "quark" || row.provider === "xunlei") &&
          row.status === "valid",
      ),
    [accounts],
  );

  useEffect(() => {
    Promise.all([api.sharePasswords(), api.accounts(), api.librarySyncSources(), api.linkedRenameConfig()])
      .then(([passwords, accountRows, syncRows, linked]) => {
        setBaiduPassword(passwords.baidu_password ?? "");
        setQuarkPassword(passwords.quark_password ?? "");
        setXunleiPassword(passwords.xunlei_password ?? "");
        setAccounts(accountRows);
        setSources(syncRows.length ? rowsToDrafts(syncRows) : []);
        setLinkedMembers(linked.members.length ? rowsToDrafts(linked.members) : []);
      })
      .catch((caught: Error) => setError(caught.message))
      .finally(() => setLoading(false));
  }, []);

  async function submitPasswords() {
    setPending(true);
    setError("");
    setSaved("");
    try {
      const row = await api.saveSharePasswords(baiduPassword, quarkPassword, xunleiPassword);
      setBaiduPassword(row.baidu_password ?? "");
      setQuarkPassword(row.quark_password ?? "");
      setXunleiPassword(row.xunlei_password ?? "");
      setSaved("已保存");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setPending(false);
    }
  }

  async function submitSources() {
    setSyncPending(true);
    setError("");
    setSyncSaved("");
    try {
      for (const [index, source] of sources.entries()) {
        if (source.account_id === "") throw new Error(`第 ${index + 1} 条请选择账号`);
        if (!source.directory.trim()) throw new Error(`第 ${index + 1} 条请选择目录`);
      }
      const rows = await api.saveLibrarySyncSources(
        sources.map((source, index) => ({
          account_id: Number(source.account_id),
          directory: source.directory,
          label: source.label.trim(),
          sort_order: index,
        })),
      );
      setSources(rowsToDrafts(rows));
      setSyncSaved("同步目录已保存");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setSyncPending(false);
    }
  }

  async function submitLinked() {
    setLinkedPending(true);
    setError("");
    setLinkedSaved("");
    try {
      if (linkedMembers.length === 0) {
        const savedRows = await api.saveLinkedRenameConfig([]);
        setLinkedMembers(rowsToDrafts(savedRows.members));
        setLinkedSaved("已清空关联重命名配置");
        return;
      }
      for (const [index, source] of linkedMembers.entries()) {
        if (source.account_id === "") throw new Error(`关联第 ${index + 1} 条请选择账号`);
        if (!source.directory.trim()) throw new Error(`关联第 ${index + 1} 条请选择目录`);
      }
      if (!linkedMembers.some((row) => row.is_primary)) {
        throw new Error("请指定一个主目录");
      }
      const savedRows = await api.saveLinkedRenameConfig(
        linkedMembers.map((source, index) => ({
          account_id: Number(source.account_id),
          directory: source.directory,
          label: source.label.trim(),
          is_primary: Boolean(source.is_primary),
          sort_order: index,
        })),
      );
      setLinkedMembers(rowsToDrafts(savedRows.members));
      setLinkedSaved("关联重命名配置已保存");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setLinkedPending(false);
    }
  }

  const activeList = picking?.kind === "linked" ? linkedMembers : sources;
  const pickingRow = picking ? activeList[picking.index] : null;
  const pickingAccount =
    pickingRow && pickingRow.account_id !== ""
      ? accounts.find((row) => row.id === pickingRow.account_id)
      : undefined;

  function renderDirCard(
    source: DraftSource,
    index: number,
    kind: "sync" | "linked",
    onChange: (updater: (rows: DraftSource[]) => DraftSource[]) => void,
  ) {
    const account = source.account_id === "" ? undefined : accounts.find((row) => row.id === source.account_id);
    return (
      <div key={source.key} className="space-y-3 rounded-xl border border-line p-4">
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm font-medium text-ink">
            {kind === "linked" ? (source.is_primary ? "主目录" : `关联目录 ${index}`) : `目录 ${index + 1}`}
          </span>
          <button
            type="button"
            className="text-sm text-[#b42318]"
            onClick={() => onChange((rows) => rows.filter((_, i) => i !== index))}
          >
            删除
          </button>
        </div>
        {kind === "linked" ? (
          <label className="flex items-center gap-2 text-sm text-ink">
            <input
              type="radio"
              name="linked-primary"
              checked={Boolean(source.is_primary)}
              disabled={loading}
              onChange={() =>
                onChange((rows) => rows.map((row, i) => ({ ...row, is_primary: i === index })))
              }
            />
            设为主目录（仅主目录可发起关联重命名）
          </label>
        ) : null}
        <label className="block text-sm">
          <span className="font-medium text-ink">账号</span>
          <select
            className="mt-2 h-10 w-full rounded-xl border border-line bg-white px-3"
            value={source.account_id === "" ? "" : String(source.account_id)}
            disabled={loading}
            onChange={(event) => {
              const nextId = event.target.value ? Number(event.target.value) : "";
              onChange((rows) =>
                rows.map((row, i) =>
                  i === index
                    ? {
                        ...row,
                        account_id: nextId,
                        directory: "/",
                        label: "",
                        trail: [{ name: "根目录", path: "/" }],
                      }
                    : row,
                ),
              );
            }}
          >
            <option value="">选择账号</option>
            {driveAccounts.map((row) => (
              <option key={row.id} value={row.id}>
                {providerLabel(row.provider)} · {row.nickname || `账号 ${row.id}`}
              </option>
            ))}
          </select>
        </label>
        <div className="text-sm">
          <span className="font-medium text-ink">目录</span>
          <div className="mt-2 flex gap-2">
            <input
              className="h-10 min-w-0 flex-1 rounded-xl border border-line bg-[#f8fafc] px-3"
              value={pathLabelFor(source, account)}
              readOnly
              aria-label={`${kind} 目录 ${index + 1}`}
            />
            <button
              type="button"
              className="btn btn-secondary shrink-0 disabled:opacity-50"
              disabled={loading || source.account_id === ""}
              onClick={() => setPicking({ kind, index })}
            >
              选择
            </button>
          </div>
        </div>
        <label className="block text-sm">
          <span className="font-medium text-ink">备注（可选）</span>
          <input
            className="mt-2 h-10 w-full rounded-xl border border-line bg-white px-3"
            value={source.label}
            placeholder="例如：漫剧已整理"
            disabled={loading}
            onChange={(event) => {
              const value = event.target.value;
              onChange((rows) => rows.map((row, i) => (i === index ? { ...row, label: value } : row)));
            }}
          />
        </label>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-xl">
      <PageHeader title="系统配置" description="按分类设置默认提取码、资源库同步目录和关联重命名。" />
      <div className="mb-5 flex flex-wrap gap-1 rounded-2xl border border-line bg-white p-1" role="tablist" aria-label="配置分类">
        {tabs.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            className={`h-9 flex-1 rounded-xl px-3 text-sm font-medium ${
              tab === item.id ? "bg-ink text-white" : "text-ink/60 hover:bg-muted hover:text-ink"
            }`}
            onClick={() => switchTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {error ? <p className="alert mb-4">{error}</p> : null}

      {tab === "passwords" ? (
        <section>
          {saved ? <p className="mb-4 text-sm text-[#067647]">{saved}</p> : null}
          <form
            className="space-y-5 rounded-2xl border border-line bg-white p-5"
            onSubmit={(event) => {
              event.preventDefault();
              void submitPasswords();
            }}
          >
            <p className="text-sm text-[#667085]">为各网盘设置批量分享时的默认提取码。留空表示创建加密链接时再填写。</p>
            <label className="block text-sm">
              <span className="font-medium text-ink">百度网盘默认提取码</span>
              <input
                className="mt-2 h-10 w-full rounded-xl border border-line bg-white px-3"
                value={baiduPassword}
                maxLength={4}
                placeholder="4 位字母或数字"
                aria-label="百度网盘默认提取码"
                disabled={loading}
                onChange={(event) => setBaiduPassword(event.target.value)}
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium text-ink">夸克网盘默认提取码</span>
              <input
                className="mt-2 h-10 w-full rounded-xl border border-line bg-white px-3"
                value={quarkPassword}
                maxLength={4}
                placeholder="4 位字母或数字"
                aria-label="夸克网盘默认提取码"
                disabled={loading}
                onChange={(event) => setQuarkPassword(event.target.value)}
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium text-ink">迅雷网盘默认提取码</span>
              <input
                className="mt-2 h-10 w-full rounded-xl border border-line bg-white px-3"
                value={xunleiPassword}
                maxLength={4}
                placeholder="4 位字母或数字"
                aria-label="迅雷网盘默认提取码"
                disabled={loading}
                onChange={(event) => setXunleiPassword(event.target.value)}
              />
            </label>
            <button type="submit" className="btn btn-primary disabled:opacity-50" disabled={pending || loading}>
              {pending ? "正在保存" : "保存提取码"}
            </button>
          </form>
        </section>
      ) : null}

      {tab === "sync" ? (
        <section>
          <p className="mb-3 text-sm text-[#667085]">
            资源库页的「同步」会按下方顺序扫描这些目录的文件夹名，只更新已有资源的完结状态与集数。同序号以后扫到的为准。
          </p>
          {syncSaved ? <p className="mb-4 text-sm text-[#067647]">{syncSaved}</p> : null}
          <div className="space-y-4 rounded-2xl border border-line bg-white p-5">
            {sources.length === 0 ? <p className="text-sm text-[#667085]">还没有同步目录。</p> : null}
            {sources.map((source, index) => renderDirCard(source, index, "sync", setSources))}
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn btn-secondary disabled:opacity-50"
                disabled={loading || driveAccounts.length === 0}
                onClick={() => setSources((rows) => [...rows, newDraft(driveAccounts[0]?.id ?? "")])}
              >
                添加目录
              </button>
              <button
                type="button"
                className="btn btn-primary disabled:opacity-50"
                disabled={syncPending || loading}
                onClick={() => void submitSources()}
              >
                {syncPending ? "正在保存" : "保存同步目录"}
              </button>
            </div>
            {driveAccounts.length === 0 && !loading ? (
              <p className="text-sm text-[#667085]">请先绑定并登录网盘账号。</p>
            ) : null}
          </div>
        </section>
      ) : null}

      {tab === "linked" ? (
        <section>
          <p className="mb-3 text-sm text-[#667085]">
            指定一个主目录和若干关联目录。在转存页主目录下使用「关联重命名」时，会按文件夹名开头的数字序号，把同组其他目录里对应项改成相同名字。
          </p>
          {linkedSaved ? <p className="mb-4 text-sm text-[#067647]">{linkedSaved}</p> : null}
          <div className="space-y-4 rounded-2xl border border-line bg-white p-5">
            {linkedMembers.length === 0 ? <p className="text-sm text-[#667085]">还没有关联配置。</p> : null}
            {linkedMembers.map((source, index) => renderDirCard(source, index, "linked", setLinkedMembers))}
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn btn-secondary disabled:opacity-50"
                disabled={loading || driveAccounts.length === 0}
                onClick={() =>
                  setLinkedMembers((rows) => [
                    ...rows,
                    newDraft(driveAccounts[0]?.id ?? "", rows.length === 0),
                  ])
                }
              >
                添加目录
              </button>
              <button
                type="button"
                className="btn btn-primary disabled:opacity-50"
                disabled={linkedPending || loading}
                onClick={() => void submitLinked()}
              >
                {linkedPending ? "正在保存" : "保存关联配置"}
              </button>
            </div>
            {driveAccounts.length === 0 && !loading ? (
              <p className="text-sm text-[#667085]">请先绑定并登录网盘账号。</p>
            ) : null}
          </div>
        </section>
      ) : null}

      {picking && pickingAccount && pickingRow ? (
        <FolderPicker
          accountId={pickingAccount.id}
          initialPath={pickingRow.directory || "/"}
          initialTrail={usesFileId(pickingAccount.provider) ? pickingRow.trail : undefined}
          onCancel={() => setPicking(null)}
          onConfirm={(path, trail) => {
            const label = trail.map((item) => item.name).join(" / ");
            const apply = (rows: DraftSource[]) =>
              rows.map((row, i) =>
                i === picking.index
                  ? {
                      ...row,
                      directory: path,
                      label: row.label.trim() ? row.label : label,
                      trail,
                    }
                  : row,
              );
            if (picking.kind === "linked") setLinkedMembers(apply);
            else setSources(apply);
            setPicking(null);
          }}
          onCreated={() => undefined}
        />
      ) : null}
    </div>
  );
}
