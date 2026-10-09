import { useEffect, useMemo, useState } from "react";
import { api, type DirEntry } from "../api";

function parentOf(directory: string) {
  if (directory === "/") return null;
  const parent = directory.slice(0, directory.lastIndexOf("/"));
  return parent || "/";
}

function crumbs(directory: string) {
  const items = [{ name: "根目录", path: "/" }];
  if (directory === "/") return items;
  let current = "";
  for (const part of directory.split("/").filter(Boolean)) {
    current += `/${part}`;
    items.push({ name: part, path: current });
  }
  return items;
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

export default function FolderPicker({
  accountId,
  initialPath,
  onCancel,
  onConfirm,
  onCreated,
}: {
  accountId: number;
  initialPath: string;
  onCancel: () => void;
  onConfirm: (path: string) => void;
  onCreated: () => void;
}) {
  const [view, setView] = useState(initialPath.startsWith("/") ? initialPath : "/");
  const [selected, setSelected] = useState(initialPath.startsWith("/") ? initialPath : "/");
  const [entries, setEntries] = useState<DirEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .files(accountId, view)
      .then((rows) => {
        if (cancelled) return;
        setEntries(rows);
        setError("");
      })
      .catch((caught: Error) => {
        if (cancelled) return;
        if (view !== "/") {
          setView("/");
          setSelected("/");
        }
        setError(caught.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [accountId, view, reloadKey]);

  const folders = useMemo(
    () => entries.filter((entry) => entry.is_dir).slice().sort((left, right) => left.name.localeCompare(right.name, "zh-CN")),
    [entries],
  );
  const parent = parentOf(view);

  function open(path: string) {
    setView(path);
    setSelected(path);
    setNaming(false);
    setName("");
    setError("");
  }

  async function createFolder() {
    const folderName = name.trim();
    if (!folderName) {
      setError("请输入文件夹名称");
      return;
    }
    setCreating(true);
    setError("");
    try {
      const created = await api.createFolder(accountId, view, folderName);
      setName("");
      setNaming(false);
      setSelected(created.path);
      setReloadKey((value) => value + 1);
      onCreated();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "新建文件夹失败");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="fixed inset-0 z-30 grid place-items-center bg-[#101828]/40 px-4 py-6" onClick={onCancel}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="folder-picker-title"
        className="flex max-h-full w-full max-w-lg flex-col rounded-2xl border border-line bg-white p-6"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 id="folder-picker-title" className="text-xl font-semibold text-[#1f2430]">
            选择文件夹
          </h2>
          <button type="button" aria-label="关闭" onClick={onCancel} className="grid h-8 w-8 place-items-center text-xl text-[#98a2b3]">
            ×
          </button>
        </div>

        <div className="mt-4 flex items-center gap-3 border-b border-[#eef0f4] pb-3 text-sm">
          <button
            type="button"
            disabled={parent === null}
            onClick={() => parent && open(parent)}
            className="text-[#98a2b3] disabled:opacity-35"
          >
            〈 返回
          </button>
          <nav className="flex min-w-0 flex-wrap items-center gap-1 font-medium text-[#1f2430]">
            {crumbs(view).map((crumb, index) => (
              <span key={crumb.path} className="flex items-center gap-1">
                {index > 0 ? <span className="text-[#d0d5dd]">/</span> : null}
                <button type="button" onClick={() => open(crumb.path)}>
                  {crumb.name}
                </button>
              </span>
            ))}
          </nav>
        </div>

        <div className="mt-2 min-h-64 flex-1 overflow-y-auto">
          {loading ? <p className="px-2 py-8 text-sm text-[#98a2b3]">正在读取目录</p> : null}
          {!loading && folders.length === 0 ? <p className="px-2 py-8 text-sm text-[#98a2b3]">这个目录下没有文件夹</p> : null}
          {!loading
            ? folders.map((folder) => (
                <div
                  key={folder.path}
                  onDoubleClick={() => open(folder.path)}
                  className={`flex items-center rounded-xl px-3 py-3 ${selected === folder.path ? "bg-muted" : "hover:bg-[#fafafa]"}`}
                >
                  <button type="button" onClick={() => setSelected(folder.path)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
                    <FolderIcon />
                    <span className="truncate text-sm font-medium text-[#1f2430]">{folder.name}</span>
                  </button>
                  <button type="button" onClick={() => open(folder.path)} className="shrink-0 px-2 text-sm text-[#667085]">
                    进入
                  </button>
                </div>
              ))
            : null}
        </div>

        {error ? <p className="mt-2 text-sm text-danger">{error}</p> : null}

        <div className="mt-3 rounded-xl bg-[#f7f8fa] px-4 py-3 text-sm text-[#98a2b3]">
          已选择： <span className="text-[#344054]">{selected}</span>
        </div>

        {naming ? (
          <form
            className="mt-3 flex gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              void createFolder();
            }}
          >
            <input
              autoFocus
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="请输入文件夹名称"
              aria-label="文件夹名称"
              className="h-10 min-w-0 flex-1 rounded-xl border border-[#e4e7ee] px-3 text-sm outline-none"
            />
            <button type="submit" disabled={creating} className="h-10 rounded-xl bg-ink px-4 text-sm font-medium text-white disabled:opacity-50">
              {creating ? "正在创建" : "创建"}
            </button>
          </form>
        ) : (
          <button
            type="button"
            onClick={() => {
              setNaming(true);
              setError("");
            }}
            className="mt-3 inline-flex h-10 items-center gap-2 rounded-xl border border-[#e4e7ee] px-3 text-sm text-[#344054]"
          >
            新建文件夹
          </button>
        )}

        <div className="mt-5 flex justify-end gap-3">
          <button type="button" onClick={onCancel} className="h-10 rounded-xl border border-[#e4e7ee] px-4 text-sm">
            取消
          </button>
          <button type="button" onClick={() => onConfirm(selected)} className="h-10 rounded-xl bg-ink px-4 text-sm font-medium text-white">
            确认选择
          </button>
        </div>
      </div>
    </div>
  );
}
