import { useEffect, useMemo, useRef, useState } from "react";
import { api, type LibraryCheckResult, type LibraryItem } from "../api";
import PageHeader from "../components/PageHeader";
import { workbookShareRows } from "../sheets";

type Filter = "all" | "finished" | "complete" | "quark" | "baidu" | "xunlei";
type Draft = {
  name: string;
  finished: boolean;
  latest_episode: string;
  quark_url: string;
  baidu_url: string;
  xunlei_url: string;
};
type CreateDraft = {
  prefix: string;
  name: string;
  finished: boolean;
  latest_episode: string;
  quark_url: string;
  baidu_url: string;
  xunlei_url: string;
};

const emptyCreate: CreateDraft = {
  prefix: "",
  name: "",
  finished: false,
  latest_episode: "",
  quark_url: "",
  baidu_url: "",
  xunlei_url: "",
};

function parseEpisode(value: string): number | null {
  const cleaned = value.trim();
  if (!cleaned) return null;
  const num = Number(cleaned);
  return Number.isInteger(num) && num >= 0 ? num : null;
}

function progressLabel(item: Pick<LibraryItem, "finished" | "latest_episode">) {
  if (item.finished && item.latest_episode != null) return `完结｜${item.latest_episode}`;
  if (item.finished) return "完结";
  if (item.latest_episode != null) return `更新至 ${item.latest_episode}`;
  return "";
}

function cleanCopyName(name: string) {
  return name
    .replace(/#完结/g, "")
    .replace(/#\d+/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function progressCopyLine(item: LibraryItem) {
  const icon = item.finished ? "✅" : "🔥";
  const parts = [item.prefix, cleanCopyName(item.name) || "未填写名称"];
  if (item.latest_episode != null) parts.push(String(item.latest_episode));
  if (item.finished) parts.push("完结");
  return `${icon}  ${parts.join("｜")}`;
}

const filters: { id: Filter; label: string }[] = [
  { id: "all", label: "全部" },
  { id: "finished", label: "完结" },
  { id: "complete", label: "三网盘齐全" },
  { id: "quark", label: "有夸克" },
  { id: "baidu", label: "有百度" },
  { id: "xunlei", label: "有迅雷" },
];

const panNames: Record<string, string> = {
  baidu: "百度网盘",
  quark: "夸克网盘",
  xunlei: "迅雷网盘",
};

const pans = [
  { key: "quark_url" as const, label: "夸克网盘", tone: "bg-[#e8f3ff] text-[#2f6fed] hover:bg-[#dbeafe]" },
  { key: "baidu_url" as const, label: "百度网盘", tone: "bg-[#e8f8ef] text-[#128a45] hover:bg-[#d7f3e3]" },
  { key: "xunlei_url" as const, label: "迅雷网盘", tone: "bg-[#fff6e5] text-[#c56a00] hover:bg-[#ffefd2]" },
];

function loose(value: string) {
  return value.toLowerCase().replace(/[\s《》【】[\]()（）·,，.。!！?？:：\-—_]/g, "");
}

function linkCount(item: LibraryItem) {
  return pans.filter((pan) => item[pan.key].trim()).length;
}

function matchesFilter(item: LibraryItem, filter: Filter) {
  if (filter === "finished") return item.finished;
  if (filter === "complete") return linkCount(item) === pans.length;
  if (filter === "quark") return Boolean(item.quark_url.trim());
  if (filter === "baidu") return Boolean(item.baidu_url.trim());
  if (filter === "xunlei") return Boolean(item.xunlei_url.trim());
  return true;
}

export default function LibraryPage() {
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [toast, setToast] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<LibraryItem | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [draft, setDraft] = useState<Draft>({
    name: "",
    finished: false,
    latest_episode: "",
    quark_url: "",
    baidu_url: "",
    xunlei_url: "",
  });
  const [saving, setSaving] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createDraft, setCreateDraft] = useState<CreateDraft>(emptyCreate);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  const [checking, setChecking] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [checkResult, setCheckResult] = useState<LibraryCheckResult | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const toastTimer = useRef(0);

  async function loadLibrary(opts?: { soft?: boolean }) {
    const soft = Boolean(opts?.soft);
    if (soft) setRefreshing(true);
    else setLoading(true);
    setError("");
    try {
      setItems(await api.library());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "读取失败");
    } finally {
      if (soft) setRefreshing(false);
      else setLoading(false);
    }
  }

  useEffect(() => {
    void loadLibrary();
  }, []);

  const visible = useMemo(() => {
    const needle = loose(query.trim());
    return items.filter((item) => {
      if (!matchesFilter(item, filter)) return false;
      if (!needle) return true;
      return loose(item.name).includes(needle) || item.prefix.includes(query.trim());
    });
  }, [items, query, filter]);

  function showToast(message: string) {
    setToast(message);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(""), 1800);
  }

  async function copyText(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      showToast("已复制");
    } catch {
      showToast("复制失败");
    }
  }

  async function confirmDelete() {
    if (deleteTarget === null || deleting) return;
    setDeleting(true);
    setError("");
    try {
      await api.deleteLibrary(deleteTarget.id);
      setItems((current) => current.filter((item) => item.id !== deleteTarget.id));
      if (editingId === deleteTarget.id) setEditingId(null);
      setDeleteTarget(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "删除失败");
    } finally {
      setDeleting(false);
    }
  }

  async function onUpload(list: FileList | null) {
    if (!list || list.length === 0) return;
    setError("");
    setNotice("");
    setPending(true);
    const rows: { name: string; url: string; password: string }[] = [];
    const problems: string[] = [];
    try {
      for (const file of list) {
        try {
          const parsed = await workbookShareRows(file);
          if (parsed.length === 0) problems.push(`${file.name}：表格里没有分享记录`);
          else rows.push(...parsed);
        } catch (caught) {
          problems.push(`${file.name}：${caught instanceof Error ? caught.message : "无法读取"}`);
        }
      }
      if (rows.length === 0) {
        setError(problems.join("；") || "没有可导入的分享记录");
        return;
      }
      const result = await api.importLibrary(rows);
      setItems(result.items);
      const summary = `新增 ${result.created} 部，更新 ${result.updated} 部${result.skipped ? `，跳过 ${result.skipped} 行` : ""}`;
      setNotice(problems.length ? `${summary}。${problems.join("；")}` : summary);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "导入失败");
    } finally {
      setPending(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function checkLinks() {
    if (checking) return;
    setChecking(true);
    setError("");
    try {
      setCheckResult(await api.checkLibrary());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "检查失败");
    } finally {
      setChecking(false);
    }
  }

  async function syncEpisodes() {
    if (syncing) return;
    setSyncing(true);
    setError("");
    setNotice("");
    try {
      const result = await api.syncLibraryEpisodes();
      const refreshed = await api.library();
      setItems(refreshed);
      setNotice(
        `同步完成：更新 ${result.updated} 部，未变 ${result.unchanged} 部` +
          (result.unmatched ? `，网盘有而资源库没有 ${result.unmatched} 个` : ""),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "同步失败");
    } finally {
      setSyncing(false);
    }
  }

  function startEdit(item: LibraryItem) {
    setEditingId(item.id);
    setDraft({
      name: item.name,
      finished: item.finished,
      latest_episode: item.latest_episode == null ? "" : String(item.latest_episode),
      quark_url: item.quark_url,
      baidu_url: item.baidu_url,
      xunlei_url: item.xunlei_url,
    });
    setError("");
  }

  async function saveEdit(item: LibraryItem) {
    if (saving) return;
    setSaving(true);
    setError("");
    try {
      const updated = await api.updateLibrary(item.id, {
        name: draft.name,
        finished: draft.finished,
        latest_episode: parseEpisode(draft.latest_episode),
        quark_url: draft.quark_url,
        baidu_url: draft.baidu_url,
        xunlei_url: draft.xunlei_url,
      });
      setItems((current) => current.map((row) => (row.id === updated.id ? updated : row)));
      setEditingId(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  function openCreate() {
    setCreateDraft(emptyCreate);
    setCreateError("");
    setCreateOpen(true);
  }

  async function submitCreate() {
    if (creating) return;
    setCreating(true);
    setCreateError("");
    try {
      const created = await api.createLibrary({
        prefix: createDraft.prefix.trim(),
        name: createDraft.name.trim(),
        finished: createDraft.finished,
        latest_episode: parseEpisode(createDraft.latest_episode),
        quark_url: createDraft.quark_url.trim(),
        baidu_url: createDraft.baidu_url.trim(),
        xunlei_url: createDraft.xunlei_url.trim(),
      });
      setItems((current) =>
        [...current.filter((row) => row.id !== created.id), created].sort((left, right) => {
          const byValue = Number(left.prefix) - Number(right.prefix);
          return byValue !== 0 ? byValue : left.prefix.localeCompare(right.prefix);
        }),
      );
      setCreateOpen(false);
      showToast("已新增");
    } catch (caught) {
      setCreateError(caught instanceof Error ? caught.message : "新增失败");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="AI漫剧网盘资源库"
        description="输入剧名即可搜索，点网盘名复制链接。相同数字前缀会归成同一部。"
      />
      {error ? <p className="alert mb-4">{error}</p> : null}
      {notice ? <p className="mb-4 text-sm text-[#067647]">{notice}</p> : null}
      {checkResult ? (
        <section className="mb-4 rounded-2xl border border-[#fecdca] bg-[#fffbfa] px-4 py-4">
          <h2 className="text-sm font-semibold text-[#1f2430]">失效链接</h2>
          {checkResult.invalid.length === 0 ? (
            <p className="mt-2 text-sm text-[#667085]">
              已检查 {checkResult.checked} 条链接，没有失效的。
              {checkResult.unknown ? `另有 ${checkResult.unknown} 条暂时无法确认。` : ""}
            </p>
          ) : (
            <>
              <p className="mt-2 text-sm text-[#667085]">
                已检查 {checkResult.checked} 条链接，{checkResult.invalid.length} 条已失效。
                {checkResult.unknown ? `另有 ${checkResult.unknown} 条暂时无法确认。` : ""}
              </p>
              <ul className="mt-3 flex flex-col gap-2">
                {checkResult.invalid.map((hit) => (
                  <li key={`${hit.id}-${hit.provider}`} className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="inline-flex h-6 min-w-10 items-center justify-center rounded-md bg-[#f2f4f7] px-1.5 font-mono text-xs font-semibold text-[#667085]">
                      {hit.prefix}
                    </span>
                    <span className="min-w-0 flex-1 truncate font-medium text-[#1f2430]">{hit.name || "未填写名称"}</span>
                    <span className="text-[#b42318]">{panNames[hit.provider] ?? hit.provider}</span>
                    <span className="text-[#98a2b3]">{hit.reason}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      ) : null}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <input
          ref={fileInput}
          type="file"
          accept=".xlsx,.xls"
          multiple
          className="sr-only"
          aria-label="上传分享表格"
          onChange={(event) => void onUpload(event.target.files)}
        />
        <button type="button" disabled={pending} onClick={() => fileInput.current?.click()} className="btn btn-primary">
          {pending ? "正在导入" : "上传表格"}
        </button>
        <a
          href="/api/library/export"
          className={`btn btn-secondary ${loading || items.length === 0 ? "pointer-events-none opacity-50" : ""}`}
          aria-disabled={loading || items.length === 0}
        >
          导出表格
        </a>
        <button type="button" disabled={checking || loading} onClick={() => void checkLinks()} className="btn btn-secondary">
          {checking ? "正在检查" : "检查链接"}
        </button>
        <button type="button" disabled={syncing || loading} onClick={() => void syncEpisodes()} className="btn btn-secondary">
          {syncing ? "正在同步" : "同步"}
        </button>
        <button type="button" disabled={pending || creating} onClick={openCreate} className="btn btn-secondary">
          新增资源
        </button>
        <button
          type="button"
          disabled={loading || refreshing}
          onClick={() => void loadLibrary({ soft: true })}
          className="btn btn-secondary disabled:opacity-50"
        >
          {refreshing ? "正在刷新" : "刷新"}
        </button>
        <button
          type="button"
          disabled={loading || visible.length === 0}
          onClick={() => void copyText(visible.map(progressCopyLine).join("\n"))}
          className="btn btn-secondary disabled:opacity-50"
        >
          复制名称
        </button>
      </div>
      <label className="relative block">
        <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-[#98a2b3]" aria-hidden="true">
          ⌕
        </span>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索剧名，如：朝朝入梦"
          aria-label="搜索剧名"
          className="h-12 w-full rounded-2xl border border-[#e6e8ee] bg-white pl-10 pr-4 text-sm outline-none"
        />
      </label>
      <div className="mt-4 flex flex-wrap gap-2">
        {filters.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setFilter(item.id)}
            className={`h-9 rounded-full px-4 text-sm ${
              filter === item.id ? "bg-[#1f2430] font-medium text-white" : "border border-[#e6e8ee] bg-white text-[#475467]"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>
      <p className="mt-4 text-sm text-[#98a2b3]">{loading ? "正在读取" : `共 ${visible.length} 部资源`}</p>
      <div className="mt-3 flex flex-col gap-3">
        {!loading && visible.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-[#e6e8ee] bg-white px-5 py-12 text-center text-sm text-[#98a2b3]">
            {items.length === 0 ? "还没有资源。可以新增单条，或上传分享任务导出的表格。" : "没有符合条件的资源。"}
          </div>
        ) : null}
        {visible.map((item) => {
          const count = linkCount(item);
          const editing = editingId === item.id;
          const lines = [
            ["渡", item.baidu_url],
            ["跨", item.quark_url],
            ["汛", item.xunlei_url],
          ]
            .filter(([, url]) => url.trim())
            .map(([label, url]) => `${label}：${url.trim()}`);
          return (
            <article key={item.id} className="rounded-2xl border border-[#e6e8ee] bg-white px-4 py-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
              <div className="flex items-start gap-3">
                <span className="mt-0.5 inline-flex h-7 min-w-12 shrink-0 items-center justify-center rounded-lg bg-[#f2f4f7] px-2 font-mono text-xs font-semibold text-[#667085]">
                  {item.prefix}
                </span>
                {editing ? (
                  <input
                    value={draft.name}
                    onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
                    aria-label="名称"
                    className="h-9 min-w-0 flex-1 rounded-lg border border-[#e4e7ee] px-3 text-sm font-semibold outline-none"
                  />
                ) : (
                  <div className="min-w-0 flex-1 pt-0.5">
                    <h2 className="truncate text-base font-semibold text-[#1f2430]">{item.name || "未填写名称"}</h2>
                    {progressLabel(item) ? (
                      <p className="mt-0.5 text-xs text-[#667085]">{progressLabel(item)}</p>
                    ) : null}
                  </div>
                )}
                {editing ? null : (
                  <span className="flex shrink-0 items-center gap-2">
                    <button
                      type="button"
                      disabled={count === 0}
                      onClick={() => void copyText(lines.join("\n"))}
                      className="h-8 rounded-lg bg-[#e8f3ff] px-3 text-sm font-medium text-[#2f6fed] disabled:opacity-40"
                    >
                      复制全部
                    </button>
                    <button type="button" onClick={() => startEdit(item)} className="h-8 rounded-lg bg-[#f2f4f7] px-3 text-sm font-medium text-[#344054]">
                      编辑
                    </button>
                    <button type="button" onClick={() => setDeleteTarget(item)} className="h-8 rounded-lg bg-[#fee4e2] px-3 text-sm font-medium text-[#d92d20]">
                      删除
                    </button>
                  </span>
                )}
              </div>
              {editing ? (
                <div className="mt-4 grid gap-3">
                  <div className="flex flex-wrap items-center gap-3 text-sm text-[#344054]">
                    <label className="inline-flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={draft.finished}
                        onChange={(event) => setDraft((current) => ({ ...current, finished: event.target.checked }))}
                      />
                      已完结
                    </label>
                    <label className="inline-flex items-center gap-2">
                      最新集数
                      <input
                        value={draft.latest_episode}
                        onChange={(event) => setDraft((current) => ({ ...current, latest_episode: event.target.value }))}
                        inputMode="numeric"
                        className="h-9 w-24 rounded-lg border border-[#e4e7ee] px-3 text-sm outline-none"
                      />
                    </label>
                  </div>
                  {pans.map((pan) => (
                    <label key={pan.key} className="block text-sm text-[#344054]">
                      {pan.label}链接
                      <input
                        value={draft[pan.key]}
                        onChange={(event) => setDraft((current) => ({ ...current, [pan.key]: event.target.value }))}
                        aria-label={`${pan.label}链接`}
                        className="mt-1 h-10 w-full rounded-lg border border-[#e4e7ee] px-3 text-sm outline-none"
                      />
                    </label>
                  ))}
                  <div className="flex justify-end gap-2">
                    <button type="button" disabled={saving} onClick={() => setEditingId(null)} className="h-9 rounded-lg px-3 text-sm text-[#667085]">
                      取消
                    </button>
                    <button
                      type="button"
                      disabled={saving}
                      onClick={() => void saveEdit(item)}
                      className="h-9 rounded-lg bg-[#1f2430] px-4 text-sm font-medium text-white disabled:opacity-50"
                    >
                      {saving ? "正在保存" : "保存"}
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
                    {pans.map((pan) => {
                      const url = item[pan.key].trim();
                      return (
                        <button
                          key={pan.key}
                          type="button"
                          disabled={!url}
                          onClick={() => void copyText(url)}
                          className={`h-11 rounded-xl text-sm font-semibold disabled:cursor-not-allowed ${
                            url ? pan.tone : "bg-[#f4f5f7] text-[#d0d5dd]"
                          }`}
                        >
                          {pan.label}
                        </button>
                      );
                    })}
                  </div>
                  <p className="mt-3 text-right text-xs text-[#98a2b3]">点网盘名即复制</p>
                </>
              )}
            </article>
          );
        })}
      </div>
      {toast ? (
        <div role="status" className="fixed top-5 left-1/2 z-40 -translate-x-1/2 rounded-full bg-[#12b76a] px-4 py-2 text-sm text-white shadow-lg">
          {toast}
        </div>
      ) : null}
      {deleteTarget ? (
        <div className="fixed inset-0 z-30 grid place-items-center bg-[#101828]/40 px-4" onClick={() => !deleting && setDeleteTarget(null)}>
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-library-title"
            className="w-full max-w-md rounded-2xl border border-[#e6e8ee] bg-white p-6"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="delete-library-title" className="text-lg font-semibold text-[#1f2430]">
              删除
            </h2>
            <p className="mt-3 text-sm leading-6 text-[#667085]">
              {deleting ? "正在删除，请稍候" : `确定删除「${deleteTarget.name || deleteTarget.prefix}」？这条资源里的链接会一起去掉。`}
            </p>
            <div className="mt-5 flex justify-end gap-3">
              <button type="button" disabled={deleting} onClick={() => setDeleteTarget(null)} className="h-10 rounded-xl px-4 text-sm text-[#667085] disabled:opacity-40">
                取消
              </button>
              <button
                type="button"
                disabled={deleting}
                onClick={() => void confirmDelete()}
                className="h-10 rounded-xl bg-[#f04438] px-4 text-sm font-medium text-white disabled:opacity-50"
              >
                {deleting ? "正在删除" : "删除"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
      {createOpen ? (
        <div className="fixed inset-0 z-30 grid place-items-center bg-[#101828]/40 px-4" onClick={() => !creating && setCreateOpen(false)}>
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="create-library-title"
            className="w-full max-w-lg rounded-2xl border border-[#e6e8ee] bg-white p-6"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="create-library-title" className="text-lg font-semibold text-[#1f2430]">
              新增资源
            </h2>
            <p className="mt-2 text-sm text-[#667085]">编号与剧名必填，三家网盘链接至少填一条。</p>
            <div className="mt-4 grid gap-3">
              <label className="block text-sm text-[#344054]">
                编号
                <input
                  value={createDraft.prefix}
                  onChange={(event) => setCreateDraft((current) => ({ ...current, prefix: event.target.value }))}
                  inputMode="numeric"
                  placeholder="如 001"
                  aria-label="编号"
                  className="mt-1 h-10 w-full rounded-lg border border-[#e4e7ee] px-3 text-sm outline-none"
                />
              </label>
              <label className="block text-sm text-[#344054]">
                剧名
                <input
                  value={createDraft.name}
                  onChange={(event) => setCreateDraft((current) => ({ ...current, name: event.target.value }))}
                  placeholder="剧名"
                  aria-label="剧名"
                  className="mt-1 h-10 w-full rounded-lg border border-[#e4e7ee] px-3 text-sm outline-none"
                />
              </label>
              <div className="flex flex-wrap items-center gap-3 text-sm text-[#344054]">
                <label className="inline-flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={createDraft.finished}
                    onChange={(event) => setCreateDraft((current) => ({ ...current, finished: event.target.checked }))}
                  />
                  已完结
                </label>
                <label className="inline-flex items-center gap-2">
                  最新集数
                  <input
                    value={createDraft.latest_episode}
                    onChange={(event) => setCreateDraft((current) => ({ ...current, latest_episode: event.target.value }))}
                    inputMode="numeric"
                    className="h-10 w-24 rounded-lg border border-[#e4e7ee] px-3 text-sm outline-none"
                  />
                </label>
              </div>
              {pans.map((pan) => (
                <label key={pan.key} className="block text-sm text-[#344054]">
                  {pan.label}链接
                  <input
                    value={createDraft[pan.key]}
                    onChange={(event) => setCreateDraft((current) => ({ ...current, [pan.key]: event.target.value }))}
                    aria-label={`${pan.label}链接`}
                    className="mt-1 h-10 w-full rounded-lg border border-[#e4e7ee] px-3 text-sm outline-none"
                  />
                </label>
              ))}
            </div>
            {createError ? <p className="alert mt-4">{createError}</p> : null}
            <div className="mt-5 flex justify-end gap-3">
              <button type="button" disabled={creating} onClick={() => setCreateOpen(false)} className="h-10 rounded-xl px-4 text-sm text-[#667085] disabled:opacity-40">
                取消
              </button>
              <button
                type="button"
                disabled={creating}
                onClick={() => void submitCreate()}
                className="h-10 rounded-xl bg-[#1f2430] px-4 text-sm font-medium text-white disabled:opacity-50"
              >
                {creating ? "正在保存" : "保存"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
