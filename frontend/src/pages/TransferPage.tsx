import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type DirEntry, type DownloadTask, type PanAccount } from "../api";
import FolderPicker from "../components/FolderPicker";
import TablePager, { PAGE_SIZE, pageOf } from "../components/TablePager";
import { workbookText } from "../sheets";

const providerName: Record<string, string> = { baidu: "百度网盘", quark: "夸克", xunlei: "迅雷" };

function formatBytes(value: number) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${unit === 0 ? size : size.toFixed(1)} ${units[unit]}`;
}

function downloadLabel(task: DownloadTask) {
  if (task.status === "running" && task.phase === "list") return `正在读取「${task.name}」`;
  if (task.status === "running") return `正在下载「${task.name}」`;
  if (task.status === "done") return `已保存到 ${task.directory ?? task.name}`;
  if (task.status === "cancelled") return `已取消「${task.name}」`;
  return task.error || "下载失败";
}

function formatSize(entry: DirEntry) {
  if (entry.is_dir || entry.size == null) return "--";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = entry.size;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = unit === 0 || value >= 10 ? 0 : 1;
  return `${value.toFixed(digits)} ${units[unit]}`;
}

function formatTime(entry: DirEntry) {
  if (entry.modified_at == null) return "--";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(entry.modified_at * 1000));
}

function fileKind(entry: DirEntry) {
  if (entry.is_dir) return "文件夹";
  const dot = entry.name.lastIndexOf(".");
  if (dot <= 0 || dot === entry.name.length - 1) return "文件";
  return entry.name.slice(dot + 1).toUpperCase();
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

function parentOf(directory: string) {
  if (directory === "/") return null;
  const parent = directory.slice(0, directory.lastIndexOf("/"));
  return parent || "/";
}

const SHARE_URL = /https?:\/\/(?:pan\.baidu\.com\/s\/1[0-9A-Za-z_-]+|pan\.quark\.cn\/s\/[0-9A-Za-z]+)(?:\?[^\s\u00a0]*)?/;
const SHARE_CAPTION = /通过百度网盘分享|通过夸克网盘|我用夸克网盘|超级会员/;
const SHARE_FOOTER = /复制这段内容|即可获取|点击链接或复制整段内容|提取码\s*[:：]\s*[0-9A-Za-z]{4}/;
const SHARE_TITLE = /分享的文件\s*[:：]\s*(.+)\s*$/m;
const QUARK_TITLE = /分享了「([^」]+)」/;

type RecognizedShare = { title: string | null; url: string; provider: "baidu" | "quark" | "unknown" };

function recognizeShares(text: string): RecognizedShare[] {
  const lines = text.split(/\r?\n/);
  const found: { index: number; item: RecognizedShare }[] = [];
  lines.forEach((line, index) => {
    const url = line.match(SHARE_URL)?.[0];
    if (!url) return;
    const around: string[] = [];
    for (let cursor = index - 1; cursor >= 0 && lines[cursor].trim() && !SHARE_URL.test(lines[cursor]); cursor -= 1) {
      if (!SHARE_CAPTION.test(lines[cursor])) break;
      around.push(lines[cursor]);
    }
    for (let cursor = index + 1; cursor < lines.length && lines[cursor].trim() && !SHARE_URL.test(lines[cursor]); cursor += 1) {
      if (!SHARE_FOOTER.test(lines[cursor])) break;
      around.push(lines[cursor]);
    }
    const block = [...around, line].join("\n");
    const title = block.match(SHARE_TITLE)?.[1]?.trim() || block.match(QUARK_TITLE)?.[1]?.trim() || null;
    found.push({
      index,
      item: { title, url, provider: url.includes("pan.quark.cn") ? "quark" : "baidu" },
    });
  });
  const seen = new Set<string>();
  return found
    .sort((left, right) => left.index - right.index)
    .map((entry) => entry.item)
    .filter((item) => {
      const identity = item.url.match(/pan\.baidu\.com\/s\/1([0-9A-Za-z_-]+)/)?.[1]
        || item.url.match(/pan\.quark\.cn\/s\/([0-9A-Za-z]+)/)?.[1]
        || item.url;
      if (seen.has(identity)) return false;
      seen.add(identity);
      return true;
    });
}

function Spinner({ light = false }: { light?: boolean }) {
  return (
    <span
      className={`inline-block h-4 w-4 shrink-0 animate-spin rounded-full border-2 ${
        light ? "border-white/40 border-t-white" : "border-[#d0d5dd] border-t-primary"
      }`}
      aria-hidden="true"
    />
  );
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

function FileIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0 text-ink/35" aria-hidden="true">
      <path
        fill="currentColor"
        d="M7 3.5h6.2L19 9.2V20a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 6 20V5A1.5 1.5 0 0 1 7.5 3.5H7Zm6 1.8V9h3.8L13 5.3Z"
      />
    </svg>
  );
}

export default function TransferPage() {
  const navigate = useNavigate();
  const [accounts, setAccounts] = useState<PanAccount[]>([]);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [directory, setDirectory] = useState("/");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [entries, setEntries] = useState<DirEntry[]>([]);
  const [query, setQuery] = useState("");
  const [keyword, setKeyword] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [links, setLinks] = useState("");
  const [error, setError] = useState("");
  const [dialogError, setDialogError] = useState("");
  const [loading, setLoading] = useState(false);
  const [pending, setPending] = useState(false);
  const [composer, setComposer] = useState(false);
  const [importMode, setImportMode] = useState<"manual" | "table">("manual");
  const [renameAfter, setRenameAfter] = useState(false);
  const [intervalMin, setIntervalMin] = useState(3);
  const [intervalMax, setIntervalMax] = useState(6);
  const [targetPath, setTargetPath] = useState("/");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [sheetName, setSheetName] = useState("");
  const [sheetOver, setSheetOver] = useState(false);
  const [busyPath, setBusyPath] = useState<string | null>(null);
  const [renameTarget, setRenameTarget] = useState<DirEntry | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<DirEntry | null>(null);
  const [mkdirOpen, setMkdirOpen] = useState(false);
  const [mkdirName, setMkdirName] = useState("");
  const [mkdirPending, setMkdirPending] = useState(false);
  const [downloads, setDownloads] = useState<DownloadTask[]>([]);
  const [shareResult, setShareResult] = useState<{ name: string; url: string; password: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const sheetInput = useRef<HTMLInputElement>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const account = accounts.find((item) => item.id === accountId) ?? null;
  const canBrowse = (account?.provider === "baidu" || account?.provider === "quark") && account.status === "valid";
  const [trail, setTrail] = useState<{ name: string; path: string }[]>([{ name: "根目录", path: "/" }]);

  useEffect(() => {
    api
      .accounts()
      .then((rows) => {
        setAccounts(rows);
        setAccountId((current) => {
          if (current !== null && rows.some((row) => row.id === current)) return current;
          const first = rows.find((row) => (row.provider === "baidu" || row.provider === "quark") && row.status === "valid") ?? rows[0];
          return first?.id ?? null;
        });
      })
      .catch((caught: Error) => setError(caught.message));
  }, []);

  useEffect(() => {
    let stopped = false;
    let timer = 0;
    async function tick() {
      try {
        const rows = await api.downloads();
        if (!stopped) setDownloads(rows);
        timer = window.setTimeout(tick, rows.some((row) => row.status === "running") ? 1000 : 4000);
      } catch {
        timer = window.setTimeout(tick, 4000);
      }
    }
    void tick();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    if (accountId === null || !canBrowse) {
      setEntries([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api
      .files(accountId, directory)
      .then((rows) => {
        if (cancelled) return;
        setEntries(rows);
        setSelected(null);
        setError("");
      })
      .catch((caught: Error) => {
        if (!cancelled) {
          setEntries([]);
          setError(caught.message);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [accountId, canBrowse, directory, reloadKey]);

  const recognized = useMemo(() => recognizeShares(links), [links]);

  const visible = useMemo(() => {
    const needle = keyword.trim().toLowerCase();
    return entries
      .filter((entry) => (needle ? entry.name.toLowerCase().includes(needle) : true))
      .slice()
      .sort((left, right) => {
        if (left.is_dir !== right.is_dir) return left.is_dir ? -1 : 1;
        return left.name.localeCompare(right.name, "zh-CN");
      });
  }, [entries, keyword]);

  useEffect(() => {
    setPage(1);
  }, [accountId, directory, keyword]);

  const paged = pageOf(visible, page, pageSize);

  function openAccount(next: PanAccount) {
    setAccountId(next.id);
    setDirectory("/");
    setTrail([{ name: "根目录", path: "/" }]);
    setQuery("");
    setKeyword("");
    setComposer(false);
    setError("");
  }

  async function shareEntry(entry: DirEntry) {
    if (accountId === null || busyPath) return;
    setBusyPath(entry.path);
    setError("");
    try {
      const shared = await api.shareFile(accountId, { fs_id: entry.fs_id, path: entry.path, name: entry.name });
      setCopied(false);
      setShareResult({ name: entry.name, url: shared.url, password: shared.password });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "分享失败");
    } finally {
      setBusyPath(null);
    }
  }

  async function downloadEntry(entry: DirEntry) {
    if (accountId === null || busyPath) return;
    setError("");
    if (!entry.is_dir) {
      api.downloadFile(accountId, entry.path, setError, entry.name);
      return;
    }
    try {
      const task = await api.startDownload(accountId, entry.path);
      setDownloads((current) => [task, ...current.filter((item) => item.id !== task.id)]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "下载失败");
    }
  }

  async function cancelDownload(id: number) {
    try {
      const task = await api.cancelDownload(id);
      setDownloads((current) => current.map((item) => (item.id === id ? task : item)));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "取消失败");
    }
  }

  async function confirmMkdir() {
    if (accountId === null || mkdirPending) return;
    const name = mkdirName.trim();
    if (!name || name === "." || name === ".." || name.includes("/") || name.includes("\\")) {
      setError("名称无效");
      return;
    }
    setMkdirPending(true);
    setError("");
    try {
      await api.createFolder(accountId, directory, name);
      setMkdirOpen(false);
      setReloadKey((value) => value + 1);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "新建文件夹失败");
    } finally {
      setMkdirPending(false);
    }
  }

  async function confirmRename() {
    if (accountId === null || renameTarget === null || busyPath) return;
    const name = renameValue.trim();
    if (!name || name === "." || name === ".." || name.includes("/") || name.includes("\\")) {
      setError("名称无效");
      return;
    }
    setBusyPath(renameTarget.path);
    setError("");
    try {
      await api.renameFile(accountId, renameTarget.path, name);
      setRenameTarget(null);
      setReloadKey((value) => value + 1);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "重命名失败");
    } finally {
      setBusyPath(null);
    }
  }

  async function confirmDelete() {
    if (accountId === null || deleteTarget === null || busyPath) return;
    setBusyPath(deleteTarget.path);
    setError("");
    try {
      await api.deleteFile(accountId, deleteTarget.path);
      setDeleteTarget(null);
      setReloadKey((value) => value + 1);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "删除失败");
    } finally {
      setBusyPath(null);
    }
  }

  function openDirectory(path: string, name?: string) {
    setDirectory(path);
    setQuery("");
    setKeyword("");
    if (account?.provider !== "quark") return;
    setTrail((current) => {
      const index = current.findIndex((item) => item.path === path);
      if (index >= 0) return current.slice(0, index + 1);
      return [...current, { name: name || "文件夹", path }];
    });
  }

  async function loadSheet(file: File) {
    const lower = file.name.toLowerCase();
    if (!lower.endsWith(".xlsx") && !lower.endsWith(".xls") && !lower.endsWith(".csv")) {
      setDialogError("请上传 .xlsx、.xls 或 .csv 文件");
      return;
    }
    try {
      const text = await workbookText(file);
      setLinks(text);
      setSheetName(file.name);
      setDialogError(text.trim() ? "" : "这个表格里没有分享链接");
    } catch {
      setDialogError("这个表格无法读取");
    }
  }

  function linkNote(provider: RecognizedShare["provider"]) {
    if (provider === "unknown") return "无法识别";
    if (!account) return "";
    if (provider !== account.provider) return provider === "baidu" ? "请使用百度账号" : "请使用夸克账号";
    return "";
  }

  async function submit() {
    if (accountId === null) return;
    const blocked = recognized.map((item) => linkNote(item.provider)).find(Boolean);
    if (blocked) {
      setDialogError(blocked);
      return;
    }
    if (/pan\.xunlei\.com/i.test(links)) {
      setDialogError("暂未开放");
      return;
    }
    setPending(true);
    setError("");
    try {
      const job = await api.createTransfer(accountId, targetPath.trim() || directory, links);
      navigate(`/jobs/${job.id}`);
    } catch (caught) {
      setDialogError(caught instanceof Error ? caught.message : "转存失败");
    } finally {
      setPending(false);
    }
  }

  const parent = parentOf(directory);

  return (
    <div className="flex min-h-[calc(100dvh-6.5rem)] flex-col bg-canvas lg:h-dvh lg:min-h-0 lg:flex-row">
      <aside className="flex w-full shrink-0 flex-col border-b border-line bg-white lg:w-[232px] lg:border-r lg:border-b-0">
        <div className="px-4 py-4">
          <p className="text-sm font-semibold text-ink">网盘</p>
        </div>
        <div className="flex gap-2 overflow-x-auto px-3 pb-3 lg:block lg:min-h-0 lg:flex-1 lg:space-y-2 lg:overflow-y-auto">
          {accounts.length === 0 ? (
            <p className="px-2 py-4 text-sm leading-6 text-ink/55">
              还没有网盘。先去
              <Link to="/accounts" className="font-medium text-primary-dark">
                绑定网盘账号
              </Link>
              。
            </p>
          ) : null}
          {accounts.map((item) => {
            const active = item.id === accountId;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => openAccount(item)}
                className={`flex min-w-44 items-center gap-3 rounded-xl px-3 py-3 text-left lg:w-full lg:min-w-0 ${
                  active ? "bg-muted ring-1 ring-primary/25" : "hover:bg-[#f7f8fa]"
                }`}
              >
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-muted text-sm font-semibold text-primary-dark">
                  {(providerName[item.provider] ?? "盘").slice(0, 1)}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold text-ink">{item.nickname}</span>
                  <span className="mt-0.5 block truncate text-xs text-[#8b909a]">
                    {providerName[item.provider] ?? item.provider}
                    {item.status === "valid" ? " · 已登录" : " · 请重新登录"}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      </aside>

      <section className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center gap-2 border-b border-[#e8eaef] bg-white px-4 py-3">
          <form
            className="flex min-w-[16rem] flex-1 items-center"
            onSubmit={(event) => {
              event.preventDefault();
              setKeyword(query);
            }}
          >
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索当前目录中的文件"
              className="h-9 min-w-0 flex-1 rounded-l-full border border-[#e4e7ee] bg-[#f7f8fa] px-4 text-sm outline-none"
            />
            <button type="submit" className="h-9 rounded-r-full bg-ink px-4 text-sm font-medium text-white">
              搜索
            </button>
          </form>
          <button
            type="button"
            disabled={!canBrowse}
            onClick={() => {
              setTargetPath(directory);
              setDialogError("");
              setComposer(true);
            }}
            className="h-9 rounded-full bg-ink px-4 text-sm font-medium text-white disabled:opacity-40"
          >
            批量转存
          </button>
          <button
            type="button"
            disabled={!canBrowse || accountId === null}
            onClick={() => {
              setMkdirName("");
              setError("");
              setMkdirOpen(true);
            }}
            className="h-9 rounded-full border border-[#e4e7ee] bg-white px-4 text-sm font-medium text-[#344054] disabled:opacity-40"
          >
            新建目录
          </button>
          <button
            type="button"
            onClick={() => setReloadKey((value) => value + 1)}
            className="grid h-9 w-9 place-items-center rounded-full border border-[#e4e7ee] bg-white text-[#667085]"
            aria-label="刷新"
          >
            ↻
          </button>
        </div>

        <div className="flex items-center gap-3 border-b border-[#eef0f4] bg-white px-4 py-2.5 text-sm text-[#344054]">
          <button
            type="button"
            disabled={parent === null}
            onClick={() => parent && openDirectory(parent)}
            className="inline-flex items-center gap-1 rounded-lg px-1 py-1 text-[#667085] disabled:opacity-35"
          >
            <span aria-hidden="true">←</span>
            返回
          </button>
          <span className="h-4 w-px bg-[#e4e7ee]" />
          <nav className="flex min-w-0 flex-1 flex-wrap items-center gap-1">
            {(account?.provider === "quark" ? trail : crumbs(directory)).map((crumb, index) => (
              <span key={crumb.path} className="flex items-center gap-1">
                {index > 0 ? <span className="text-[#d0d5dd]">/</span> : null}
                <button
                  type="button"
                  className="inline-flex items-center gap-1 rounded-lg px-1.5 py-1 hover:bg-muted"
                  onClick={() => openDirectory(crumb.path)}
                >
                  {index === 0 ? (
                    <svg viewBox="0 0 24 24" className="h-4 w-4 text-[#98a2b3]" aria-hidden="true">
                      <path fill="currentColor" d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-5v-6H10v6H5a1 1 0 0 1-1-1v-9.5Z" />
                    </svg>
                  ) : null}
                  {crumb.name}
                </button>
              </span>
            ))}
          </nav>
          <span className="hidden shrink-0 text-xs text-[#98a2b3] sm:inline">双击文件夹进入下一级</span>
        </div>

        {error ? <p className="mx-4 mt-3 rounded-xl bg-red-50 px-4 py-3 text-sm text-danger">{error}</p> : null}

        <div className="min-h-0 flex-1 overflow-auto">
          {account === null ? (
            <p className="px-6 py-16 text-sm text-[#667085]">左侧选择一个网盘，右侧会显示它的文件目录。</p>
          ) : !canBrowse ? (
            <p className="px-6 py-16 text-sm text-[#667085]">
              这个账号还不能浏览目录。请到
              <Link to="/accounts" className="font-medium text-primary-dark">
                网盘账号
              </Link>
              重新登录。
            </p>
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 z-10 bg-[#f7f8fa] text-xs text-[#98a2b3]">
                <tr>
                  <th className="sticky left-0 bg-[#f7f8fa] px-5 py-3 font-medium">文件名</th>
                  <th className="w-52 px-3 py-3 font-medium">操作</th>
                  <th className="w-24 px-3 py-3 font-medium">大小</th>
                  <th className="w-24 px-3 py-3 font-medium">类型</th>
                  <th className="hidden w-40 px-3 py-3 font-medium md:table-cell">修改时间</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={5} className="px-5 py-10 text-[#98a2b3]">
                      正在读取目录
                    </td>
                  </tr>
                ) : null}
                {!loading && visible.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-5 py-10 text-[#98a2b3]">
                      这个目录是空的。双击文件夹可以进入下一级。
                    </td>
                  </tr>
                ) : null}
                {!loading
                  ? paged.rows.map((entry) => (
                      <tr
                        key={entry.path}
                        role={entry.is_dir ? "button" : undefined}
                        tabIndex={entry.is_dir ? 0 : undefined}
                        aria-label={entry.is_dir ? `打开文件夹 ${entry.name}` : undefined}
                        onClick={() => setSelected(entry.path)}
                        onDoubleClick={() => {
                          if (entry.is_dir) openDirectory(entry.path, entry.name);
                        }}
                        onKeyDown={(event) => {
                          if (entry.is_dir && event.key === "Enter") openDirectory(entry.path, entry.name);
                        }}
                        className={`group border-t border-[#f2f4f7] ${
                          selected === entry.path ? "bg-muted" : "bg-white hover:bg-[#fafafa]"
                        } ${entry.is_dir ? "cursor-pointer" : ""}`}
                      >
                        <td
                          className={`sticky left-0 px-5 py-3.5 ${
                            selected === entry.path ? "bg-muted" : "bg-white group-hover:bg-[#fafafa]"
                          }`}
                        >
                          <span className="flex min-w-0 items-center gap-2.5">
                            {entry.is_dir ? <FolderIcon /> : <FileIcon />}
                            <span className="truncate font-medium text-[#1f2430]">{entry.name}</span>
                            {busyPath === entry.path ? <Spinner /> : null}
                          </span>
                        </td>
                        <td className="px-3 py-3.5">
                          <span
                            className={`flex gap-3 whitespace-nowrap text-sm font-medium ${
                              selected === entry.path
                                ? "opacity-100"
                                : "opacity-0 pointer-events-none group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100"
                            }`}
                          >
                            <button
                              type="button"
                              className="text-[#12b76a] disabled:opacity-40"
                              disabled={busyPath === entry.path}
                              onClick={(event) => {
                                event.stopPropagation();
                                void shareEntry(entry);
                              }}
                              onDoubleClick={(event) => event.stopPropagation()}
                            >
                              分享
                            </button>
                            <button
                              type="button"
                              className="text-primary disabled:opacity-40"
                              disabled={busyPath === entry.path}
                              onClick={(event) => {
                                event.stopPropagation();
                                void downloadEntry(entry);
                              }}
                              onDoubleClick={(event) => event.stopPropagation()}
                            >
                              下载
                            </button>
                            <button
                              type="button"
                              className="text-[#f79009] disabled:opacity-40"
                              disabled={busyPath === entry.path}
                              onClick={(event) => {
                                event.stopPropagation();
                                setError("");
                                setRenameValue(entry.name);
                                setRenameTarget(entry);
                              }}
                              onDoubleClick={(event) => event.stopPropagation()}
                            >
                              重命名
                            </button>
                            <button
                              type="button"
                              className="text-[#f04438] disabled:opacity-40"
                              disabled={busyPath === entry.path}
                              onClick={(event) => {
                                event.stopPropagation();
                                setError("");
                                setDeleteTarget(entry);
                              }}
                              onDoubleClick={(event) => event.stopPropagation()}
                            >
                              删除
                            </button>
                          </span>
                        </td>
                        <td className="px-3 py-3.5 text-[#98a2b3]">{formatSize(entry)}</td>
                        <td className="px-3 py-3.5">
                          <span
                            className={`inline-flex rounded-md px-2 py-0.5 text-xs ${
                              entry.is_dir ? "bg-[#fff4e8] text-[#f97316]" : "bg-[#f2f4f7] text-[#667085]"
                            }`}
                          >
                            {fileKind(entry)}
                          </span>
                        </td>
                        <td className="hidden px-3 py-3.5 text-[#667085] md:table-cell">{formatTime(entry)}</td>
                      </tr>
                    ))
                  : null}
              </tbody>
            </table>
          )}
        </div>
        {account !== null && canBrowse ? (
          <TablePager
            page={paged.page}
            total={visible.length}
            pageSize={pageSize}
            onPage={setPage}
            onPageSize={(size) => {
              setPageSize(size);
              setPage(1);
            }}
          />
        ) : null}
      </section>

      {composer ? (
        <div className="fixed inset-0 z-20 grid place-items-center bg-[#101828]/40 px-4 py-6" onClick={() => setComposer(false)}>
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="transfer-title"
            className="max-h-full w-full max-w-3xl overflow-y-auto rounded-2xl bg-white p-6 border border-line"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h2 id="transfer-title" className="text-xl font-semibold text-[#1f2430]">
                批量转存
              </h2>
              <button type="button" aria-label="关闭" onClick={() => setComposer(false)} className="grid h-8 w-8 place-items-center text-xl text-[#98a2b3]">
                ×
              </button>
            </div>

            <div className="mt-5 flex flex-wrap items-start justify-between gap-4">
              <div className="inline-flex rounded-xl bg-[#f2f4f7] p-1">
                <button
                  type="button"
                  onClick={() => setImportMode("manual")}
                  className={`rounded-lg px-4 py-1.5 text-sm font-medium ${importMode === "manual" ? "bg-ink text-white" : "text-[#667085]"}`}
                >
                  手动输入
                </button>
                <button
                  type="button"
                  onClick={() => setImportMode("table")}
                  className={`rounded-lg px-4 py-1.5 text-sm font-medium ${importMode === "table" ? "bg-ink text-white" : "text-[#667085]"}`}
                >
                  表格导入
                </button>
              </div>
              <div className="text-right">
                <button type="button" role="switch" aria-checked={renameAfter} onClick={() => setRenameAfter((value) => !value)} className="inline-flex items-center gap-2">
                  <span className={`relative h-6 w-11 rounded-full transition-colors ${renameAfter ? "bg-ink" : "bg-[#e4e7ee]"}`}>
                    <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow ${renameAfter ? "left-5" : "left-0.5"}`} />
                  </span>
                  <span className="text-sm font-medium text-[#344054]">转存后重命名</span>
                </button>
                <p className="mt-1 text-xs text-[#98a2b3]">转存成功后，使用文案中的标题进行重命名</p>
              </div>
            </div>

            {importMode === "manual" ? (
              <textarea
                className="mt-4 min-h-44 w-full rounded-xl border border-[#e4e7ee] px-4 py-3 text-sm leading-6 text-[#1f2430] outline-none placeholder:text-[#c0c5ce]"
                value={links}
                onChange={(event) => setLinks(event.target.value)}
                placeholder={"每行一个分享链接，支持附带提取码\n例: https://pan.baidu.com/s/1xxx 提取码: abcd\n\n支持粘贴包含描述文字的内容，系统会自动识别提取网盘链接"}
              />
            ) : (
              <button
                type="button"
                onClick={() => sheetInput.current?.click()}
                onDragOver={(event) => {
                  event.preventDefault();
                  setSheetOver(true);
                }}
                onDragLeave={() => setSheetOver(false)}
                onDrop={(event) => {
                  event.preventDefault();
                  setSheetOver(false);
                  const file = event.dataTransfer.files[0];
                  if (file) void loadSheet(file);
                }}
                className={`mt-4 flex min-h-44 w-full flex-col items-center justify-center rounded-xl border border-dashed px-6 py-8 ${
                  sheetOver ? "border-primary bg-muted" : "border-[#d9deea] bg-[#fbfbfe]"
                }`}
              >
                <span className="text-2xl text-[#b0b7c3]">↑</span>
                <span className="mt-3 text-sm font-medium text-[#667085]">{sheetName || "点击或拖拽 Excel / CSV 文件"}</span>
                <span className="mt-2 text-xs text-[#b0b7c3]">支持 .xlsx .xls .csv 格式</span>
              </button>
            )}
            <input
              ref={sheetInput}
              type="file"
              accept=".xlsx,.xls,.csv,text/csv"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void loadSheet(file);
                event.target.value = "";
              }}
            />
            {links.trim() ? (
              <ul className="mt-3 space-y-2 rounded-xl bg-[#f8f9fc] px-4 py-3 text-sm">
                <li className="text-xs text-[#98a2b3]">已识别 {recognized.length} 个链接</li>
                {recognized.length === 0 ? <li className="text-[#98a2b3]">没有识别到分享链接</li> : null}
                {/pan\.xunlei\.com/i.test(links) ? <li className="text-[#667085]">迅雷 · 暂未开放</li> : null}
                {recognized.map((item, index) => (
                  <li key={`${item.url}-${index}`} className="min-w-0">
                    {item.title ? <div className="truncate font-medium text-[#1f2430]">{item.title}</div> : null}
                    <div className="truncate text-[#667085]">
                      {linkNote(item.provider) ? `${linkNote(item.provider)} · ` : ""}
                      {item.url}
                    </div>
                  </li>
                ))}
              </ul>
            ) : null}

            <h3 className="mt-6 text-base font-semibold text-[#1f2430]">其它选项</h3>
            <div className="mt-3 flex items-center justify-between gap-4 rounded-xl border border-[#eef0f4] bg-[#fafafa] px-4 py-3">
              <div className="flex items-center gap-3">
                <span className="grid h-9 w-9 place-items-center rounded-full bg-white text-[#98a2b3]">⏱</span>
                <div>
                  <div className="text-sm font-medium text-[#1f2430]">转存间隔</div>
                  <div className="text-xs text-[#98a2b3]">每个任务之间的随机等待时间，建议设置 3~6 秒</div>
                </div>
              </div>
              <div className="flex items-center gap-2 text-sm text-[#667085]">
                <input
                  type="number"
                  min={0}
                  max={60}
                  value={intervalMin}
                  onChange={(event) => setIntervalMin(Number(event.target.value))}
                  className="h-9 w-14 rounded-lg border border-[#e4e7ee] bg-white text-center"
                  aria-label="最短间隔秒数"
                />
                <span>~</span>
                <input
                  type="number"
                  min={0}
                  max={60}
                  value={intervalMax}
                  onChange={(event) => setIntervalMax(Number(event.target.value))}
                  className="h-9 w-14 rounded-lg border border-[#e4e7ee] bg-white text-center"
                  aria-label="最长间隔秒数"
                />
                <span>秒</span>
              </div>
            </div>

            <h3 className="mt-6 text-base font-semibold text-[#1f2430]">转存路径</h3>
            <div className="mt-3 flex items-center gap-3">
              <div className="flex h-12 min-w-0 flex-1 items-center rounded-xl border border-[#e4e7ee] bg-white px-4">
                <input
                  value={targetPath}
                  onChange={(event) => setTargetPath(event.target.value)}
                  aria-label="转存路径"
                  className="min-w-0 flex-1 bg-transparent text-sm outline-none"
                />
                <button type="button" aria-label="选择文件夹" onClick={() => setPickerOpen(true)} className="text-[#f97316]">
                  <FolderIcon />
                </button>
              </div>
              <button
                type="button"
                disabled={pending || recognized.length === 0}
                onClick={submit}
                className="h-12 shrink-0 rounded-xl bg-gradient-to-r from-[#7c6bff] to-[#b7a8ff] px-5 text-sm font-medium text-white disabled:opacity-50"
              >
                {pending ? "正在创建" : "开始转存"}
              </button>
            </div>
            {dialogError ? <p className="mt-3 text-sm text-danger">{dialogError}</p> : null}
          </div>
        </div>
      ) : null}
      {composer && pickerOpen && accountId !== null ? (
        <FolderPicker
          accountId={accountId}
          initialPath={targetPath}
          onCancel={() => setPickerOpen(false)}
          onConfirm={(path) => {
            setTargetPath(path);
            setPickerOpen(false);
          }}
          onCreated={() => setReloadKey((value) => value + 1)}
        />
      ) : null}
      {renameTarget ? (
        <div className="fixed inset-0 z-30 grid place-items-center bg-[#101828]/40 px-4" onClick={() => setRenameTarget(null)}>
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="rename-title"
            className="w-full max-w-md rounded-2xl bg-white p-6 border border-line"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="rename-title" className="text-lg font-semibold text-[#1f2430]">
              重命名
            </h2>
            <input
              value={renameValue}
              onChange={(event) => setRenameValue(event.target.value)}
              aria-label="新名称"
              className="mt-4 h-11 w-full rounded-xl border border-[#e4e7ee] px-3 text-sm outline-none"
              onKeyDown={(event) => {
                if (event.key === "Enter") void confirmRename();
              }}
            />
            <div className="mt-5 flex justify-end gap-3">
              <button type="button" onClick={() => setRenameTarget(null)} className="h-10 rounded-xl px-4 text-sm text-[#667085]">
                取消
              </button>
              <button
                type="button"
                disabled={busyPath !== null}
                onClick={() => void confirmRename()}
                className="h-10 rounded-xl bg-ink px-4 text-sm font-medium text-white disabled:opacity-50"
              >
                确认
              </button>
            </div>
          </div>
        </div>
      ) : null}
      {deleteTarget ? (
        <div
          className="fixed inset-0 z-30 grid place-items-center bg-[#101828]/40 px-4"
          onClick={() => {
            if (busyPath !== deleteTarget.path) setDeleteTarget(null);
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-title"
            className="w-full max-w-md rounded-2xl bg-white p-6 border border-line"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="delete-title" className="text-lg font-semibold text-[#1f2430]">
              删除
            </h2>
            <p className="mt-3 text-sm leading-6 text-[#667085]">
              {busyPath === deleteTarget.path ? "正在删除，请稍候" : `确定把「${deleteTarget.name}」移到网盘回收站？`}
            </p>
            <div className="mt-5 flex justify-end gap-3">
              <button
                type="button"
                disabled={busyPath === deleteTarget.path}
                onClick={() => setDeleteTarget(null)}
                className="h-10 rounded-xl px-4 text-sm text-[#667085] disabled:opacity-40"
              >
                取消
              </button>
              <button
                type="button"
                disabled={busyPath !== null}
                onClick={() => void confirmDelete()}
                className="inline-flex h-10 items-center gap-2 rounded-xl bg-[#f04438] px-4 text-sm font-medium text-white disabled:opacity-50"
              >
                {busyPath === deleteTarget.path ? <Spinner light /> : null}
                {busyPath === deleteTarget.path ? "正在删除" : "删除"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
      {mkdirOpen ? (
        <div className="fixed inset-0 z-30 grid place-items-center bg-[#101828]/40 px-4" onClick={() => !mkdirPending && setMkdirOpen(false)}>
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="mkdir-title"
            className="w-full max-w-md rounded-2xl bg-white p-6 border border-line"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="mkdir-title" className="text-lg font-semibold text-[#1f2430]">
              新建目录
            </h2>
            <p className="mt-2 text-sm text-[#667085]">将创建在当前打开的目录里。</p>
            <input
              value={mkdirName}
              onChange={(event) => setMkdirName(event.target.value)}
              aria-label="目录名称"
              className="mt-4 h-11 w-full rounded-xl border border-[#e4e7ee] px-3 text-sm outline-none"
              onKeyDown={(event) => {
                if (event.key === "Enter") void confirmMkdir();
              }}
            />
            <div className="mt-5 flex justify-end gap-3">
              <button type="button" disabled={mkdirPending} onClick={() => setMkdirOpen(false)} className="h-10 rounded-xl px-4 text-sm text-[#667085] disabled:opacity-40">
                取消
              </button>
              <button
                type="button"
                disabled={mkdirPending}
                onClick={() => void confirmMkdir()}
                className="inline-flex h-10 items-center gap-2 rounded-xl bg-ink px-4 text-sm font-medium text-white disabled:opacity-50"
              >
                {mkdirPending ? <Spinner light /> : null}
                {mkdirPending ? "正在创建" : "创建"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
      {downloads.some((task) => task.status === "running") ? (
        <div className="fixed bottom-5 right-5 z-30 flex w-80 flex-col gap-3">
          {downloads
            .filter((task) => task.status === "running")
            .map((task) => {
              const percent = task.bytes_total > 0 ? Math.min(100, Math.round((task.bytes_done / task.bytes_total) * 100)) : 0;
              return (
                <div key={task.id} className="rounded-2xl bg-white px-4 py-3 border border-line">
                  <div className="flex items-start justify-between gap-3">
                    <p className="break-all text-sm font-medium text-[#1f2430]">{downloadLabel(task)}</p>
                    <button type="button" onClick={() => void cancelDownload(task.id)} className="shrink-0 text-sm text-[#f04438]">
                      取消
                    </button>
                  </div>
                  {task.phase === "save" && task.bytes_total > 0 ? (
                    <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[#eaecf0]">
                      <div className="h-full rounded-full bg-primary" style={{ width: `${percent}%` }} />
                    </div>
                  ) : null}
                  <p className="mt-2 break-all text-xs text-[#667085]">
                    {task.phase === "list"
                      ? "正在统计大小"
                      : `${formatBytes(task.bytes_done)} / ${formatBytes(task.bytes_total)} · ${task.files_done}/${task.files_total}${task.current_name ? ` · ${task.current_name}` : ""}`}
                  </p>
                </div>
              );
            })}
          <Link to="/downloads" className="rounded-2xl bg-white px-4 py-2 text-center text-sm text-primary border border-line">
            查看下载记录
          </Link>
        </div>
      ) : null}
      {shareResult ? (
        <div className="fixed inset-0 z-30 grid place-items-center bg-[#101828]/40 px-4" onClick={() => setShareResult(null)}>
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="share-title"
            className="w-full max-w-md rounded-2xl bg-white p-6 border border-line"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="share-title" className="text-lg font-semibold text-[#1f2430]">
              分享「{shareResult.name}」
            </h2>
            <p className="mt-4 break-all rounded-xl bg-[#f8f9fc] px-4 py-3 text-sm leading-6 text-[#344054]">
              链接：{shareResult.url}
              <br />
              提取码：{shareResult.password}
            </p>
            <div className="mt-5 flex justify-end gap-3">
              <button type="button" onClick={() => setShareResult(null)} className="h-10 rounded-xl px-4 text-sm text-[#667085]">
                关闭
              </button>
              <button
                type="button"
                onClick={() => {
                  void navigator.clipboard.writeText(`链接：${shareResult.url}\n提取码：${shareResult.password}`).then(() => setCopied(true));
                }}
                className="h-10 rounded-xl bg-[#12b76a] px-4 text-sm font-medium text-white"
              >
                {copied ? "已复制" : "复制"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
