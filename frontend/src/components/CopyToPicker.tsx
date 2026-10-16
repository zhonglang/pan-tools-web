import { useEffect, useMemo, useState } from "react";
import { api, type CopyTargetResult, type DirEntry } from "../api";

function parentOf(directory: string) {
  if (directory === "/") return null;
  const parent = directory.slice(0, directory.lastIndexOf("/"));
  return parent || "/";
}

type Crumb = { name: string; path: string };

function crumbs(directory: string): Crumb[] {
  const items = [{ name: "根目录", path: "/" }];
  if (directory === "/") return items;
  let current = "";
  for (const part of directory.split("/").filter(Boolean)) {
    current += `/${part}`;
    items.push({ name: part, path: current });
  }
  return items;
}

function isSelfOrDescendant(source: string, target: string) {
  const src = source.replace(/\/+$/, "") || "/";
  const tgt = target.replace(/\/+$/, "") || "/";
  if (src === "/") return false;
  return tgt === src || tgt.startsWith(`${src}/`);
}

function FolderIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0 text-[#f97316]" aria-hidden="true">
      <path
        fill="currentColor"
        d="M3.2 6.8A2.2 2.2 0 0 1 5.4 4.6h4.1c.5 0 1 .2 1.4.6l1.2 1.3h6.5a2.2 2.2 0 0 1 2.2 2.2v8.5a2.2 2.2 0 0 1-2.2 2.2H5.4a2.2 2.2 0 0 1-2.2-2.2V6.8Z"
      />
    </svg>
  );
}

export default function CopyToPicker({
  accountId,
  sourcePath,
  sourceName,
  pending = false,
  error = "",
  failures = [],
  onCancel,
  onConfirm,
}: {
  accountId: number;
  sourcePath: string;
  sourceName: string;
  pending?: boolean;
  error?: string;
  failures?: CopyTargetResult[];
  onCancel: () => void;
  onConfirm: (targets: string[]) => void;
}) {
  const [view, setView] = useState("/");
  const [trail, setTrail] = useState<Crumb[]>([{ name: "根目录", path: "/" }]);
  const [entries, setEntries] = useState<DirEntry[]>([]);
  const [checked, setChecked] = useState<Record<string, DirEntry>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  const selectedCount = Object.keys(checked).length;
  const locked = selectedCount > 0;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .files(accountId, view)
      .then((rows) => {
        if (cancelled) return;
        setEntries(rows);
        setLoadError("");
      })
      .catch((caught: Error) => {
        if (cancelled) return;
        setLoadError(caught.message);
        setEntries([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [accountId, view]);

  const folders = useMemo(
    () => entries.filter((entry) => entry.is_dir).slice().sort((left, right) => left.name.localeCompare(right.name, "zh-CN")),
    [entries],
  );
  const selectable = useMemo(
    () => folders.filter((folder) => !isSelfOrDescendant(sourcePath, folder.path)),
    [folders, sourcePath],
  );
  const allSelectableChecked =
    selectable.length > 0 && selectable.every((folder) => Boolean(checked[folder.path]));
  const parent = parentOf(view);

  function open(path: string, folderName?: string) {
    if (locked || pending) return;
    setView(path);
    setChecked({});
    setTrail((current) => {
      const index = current.findIndex((item) => item.path === path);
      if (index >= 0) return current.slice(0, index + 1);
      return [...current, { name: folderName || "文件夹", path }];
    });
    setLoadError("");
  }

  function toggle(folder: DirEntry) {
    if (pending || isSelfOrDescendant(sourcePath, folder.path)) return;
    setChecked((current) => {
      if (current[folder.path]) {
        const next = { ...current };
        delete next[folder.path];
        return next;
      }
      return { ...current, [folder.path]: folder };
    });
  }

  function toggleAll() {
    if (pending || selectable.length === 0) return;
    if (allSelectableChecked) {
      setChecked({});
      return;
    }
    setChecked(Object.fromEntries(selectable.map((folder) => [folder.path, folder])));
  }

  return (
    <div
      className="fixed inset-0 z-30 flex items-center justify-center bg-[#101828]/40 px-4 py-6"
      onClick={() => {
        if (!pending) onCancel();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="copy-to-title"
        className="flex max-h-[calc(100vh-3rem)] w-full max-w-lg min-h-0 flex-col overflow-hidden rounded-2xl border border-line bg-white"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="shrink-0 px-6 pt-6">
          <div className="flex items-center justify-between">
            <h2 id="copy-to-title" className="text-xl font-semibold text-[#1f2430]">
              复制到
            </h2>
            <button type="button" aria-label="关闭" disabled={pending} onClick={onCancel} className="grid h-8 w-8 place-items-center text-xl text-[#98a2b3] disabled:opacity-40">
              ×
            </button>
          </div>
          <p className="mt-2 text-sm text-[#667085]">
            将「{sourceName}」复制到同级目录。进入父目录后勾选一个或多个子文件夹。
          </p>

          <div className="mt-4 flex items-center gap-3 border-b border-[#eef0f4] pb-3 text-sm">
            <button
              type="button"
              disabled={pending || locked || (trail.length <= 1 && parent === null)}
              onClick={() => {
                const previous = trail[trail.length - 2];
                if (previous) open(previous.path);
              }}
              className="text-[#98a2b3] disabled:opacity-35"
            >
              〈 返回
            </button>
            <nav className="flex min-w-0 flex-wrap items-center gap-1 font-medium text-[#1f2430]">
              {trail.map((crumb, index) => (
                <span key={crumb.path} className="flex items-center gap-1">
                  {index > 0 ? <span className="text-[#d0d5dd]">/</span> : null}
                  <button type="button" disabled={pending || locked} onClick={() => open(crumb.path)}>
                    {crumb.name}
                  </button>
                </span>
              ))}
            </nav>
          </div>
          {locked ? <p className="mt-2 text-xs text-[#98a2b3]">已勾选目录时不能切换层级，清空勾选后可继续浏览。</p> : null}
        </div>

        <div className="mt-2 min-h-0 flex-1 overflow-y-auto px-6">
          {loading ? <p className="px-2 py-8 text-sm text-[#98a2b3]">正在读取目录</p> : null}
          {!loading && folders.length === 0 ? <p className="px-2 py-8 text-sm text-[#98a2b3]">这个目录下没有文件夹</p> : null}
          {!loading && folders.length > 0 ? (
            <label className="flex cursor-pointer items-center gap-2 rounded-xl px-3 py-2 text-sm text-[#344054] hover:bg-[#fafafa]">
              <input
                type="checkbox"
                checked={allSelectableChecked}
                disabled={pending || selectable.length === 0}
                aria-label="全选当前同级目录"
                onChange={toggleAll}
              />
              <span className="font-medium">全选</span>
              <span className="text-xs text-[#98a2b3]">
                {selectable.length}/{folders.length} 可选
              </span>
            </label>
          ) : null}
          {!loading
            ? folders.map((folder) => {
                const blocked = isSelfOrDescendant(sourcePath, folder.path);
                const active = Boolean(checked[folder.path]);
                return (
                  <div key={folder.path} className={`flex items-center gap-2 rounded-xl px-3 py-3 ${active ? "bg-muted" : "hover:bg-[#fafafa]"}`}>
                    <input
                      type="checkbox"
                      checked={active}
                      disabled={pending || blocked}
                      aria-label={`选择 ${folder.name}`}
                      onChange={() => toggle(folder)}
                    />
                    <button
                      type="button"
                      disabled={pending || locked}
                      onClick={() => open(folder.path, folder.name)}
                      className="flex min-w-0 flex-1 items-center gap-2 text-left disabled:opacity-50"
                    >
                      <FolderIcon />
                      <span className="truncate text-sm font-medium text-[#1f2430]">{folder.name}</span>
                      {blocked ? <span className="shrink-0 text-xs text-[#98a2b3]">不可选</span> : null}
                    </button>
                    <button
                      type="button"
                      disabled={pending || locked}
                      onClick={() => open(folder.path, folder.name)}
                      className="shrink-0 px-2 text-sm text-[#667085] disabled:opacity-40"
                    >
                      进入
                    </button>
                  </div>
                );
              })
            : null}
        </div>

        <div className="shrink-0 px-6 pb-6 pt-3">
          {loadError ? <p className="mb-2 text-sm text-danger">{loadError}</p> : null}
          {error ? <p className="mb-2 text-sm text-danger">{error}</p> : null}
          {failures.length > 0 ? (
            <ul className="mb-2 max-h-24 overflow-y-auto rounded-xl bg-[#fef3f2] px-3 py-2 text-sm text-[#b42318]">
              {failures.map((row) => (
                <li key={row.path}>
                  {row.path}：{row.error || "复制失败"}
                </li>
              ))}
            </ul>
          ) : null}

          <div className="rounded-xl bg-[#f7f8fa] px-4 py-3 text-sm text-[#98a2b3]">
            已选 <span className="font-medium text-[#344054]">{selectedCount}</span> 个
          </div>

          <div className="mt-4 flex justify-end gap-3">
            <button type="button" disabled={pending} onClick={onCancel} className="h-10 rounded-xl border border-[#e4e7ee] px-4 text-sm disabled:opacity-40">
              取消
            </button>
            <button
              type="button"
              disabled={pending || selectedCount === 0}
              onClick={() => onConfirm(Object.keys(checked))}
              className="h-10 rounded-xl bg-ink px-4 text-sm font-medium text-white disabled:opacity-50"
            >
              {pending ? "正在复制" : "开始复制"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
