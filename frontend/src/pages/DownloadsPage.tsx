import { useEffect, useState } from "react";
import { api, type DownloadTask } from "../api";
import PageHeader from "../components/PageHeader";
import TableLoading from "../components/TableLoading";
import TablePager, { PAGE_SIZE, pageOf } from "../components/TablePager";

const statusName: Record<string, string> = {
  running: "正在下载",
  done: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

function formatTime(value: string) {
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`;
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(normalized));
}

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

function statusLabel(task: DownloadTask) {
  if (task.status === "running" && task.phase === "list") return "正在读取";
  return statusName[task.status] ?? task.status;
}

function statusClass(status: string) {
  if (status === "done") return "bg-[#e7f8ef] text-[#067647]";
  if (status === "failed") return "bg-[#fef3f2] text-[#b42318]";
  if (status === "cancelled") return "bg-[#fffaeb] text-[#b54708]";
  if (status === "running") return "bg-muted text-primary-dark";
  return "bg-[#f2f4f7] text-[#475467]";
}

export default function DownloadsPage() {
  const [tasks, setTasks] = useState<DownloadTask[]>([]);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [loaded, setLoaded] = useState(false);
  const paged = pageOf(tasks, page, pageSize);

  useEffect(() => {
    let stopped = false;
    let timer = 0;
    async function tick() {
      try {
        const rows = await api.downloads();
        if (!stopped) {
          setTasks(rows);
          setError("");
        }
        if (rows.some((row) => row.status === "running")) timer = window.setTimeout(tick, 1000);
      } catch (caught) {
        if (!stopped) setError(caught instanceof Error ? caught.message : "加载失败");
      } finally {
        if (!stopped) setLoaded(true);
      }
    }
    void tick();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, []);

  async function cancelDownload(id: number) {
    try {
      const task = await api.cancelDownload(id);
      setTasks((current) => current.map((item) => (item.id === id ? task : item)));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "取消失败");
    }
  }

  return (
    <div>
      <PageHeader title="下载记录" description="每次目录下载都记在这里。正在进行的任务可以看进度，也可以取消。" />
      {error ? <p className="alert mb-4">{error}</p> : null}
      <div className="overflow-hidden rounded-2xl border border-line bg-white">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] border-collapse text-left text-sm">
            <thead className="bg-canvas text-[12px] text-ink/50">
              <tr>
                <th className="px-4 py-3 font-medium">时间</th>
                <th className="px-4 py-3 font-medium">状态</th>
                <th className="px-4 py-3 font-medium">名称</th>
                <th className="px-4 py-3 font-medium">网盘路径</th>
                <th className="px-4 py-3 font-medium">进度</th>
                <th className="px-4 py-3 font-medium">本地位置</th>
                <th className="px-4 py-3 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {!loaded ? <TableLoading colSpan={7} /> : null}
              {loaded && tasks.length === 0 && !error ? (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-ink/45">
                    还没有下载记录。
                  </td>
                </tr>
              ) : null}
              {paged.rows.map((task) => {
                const percent = task.bytes_total > 0 ? Math.min(100, Math.round((task.bytes_done / task.bytes_total) * 100)) : 0;
                return (
                  <tr key={task.id} className="border-t border-line align-top hover:bg-canvas">
                    <td className="whitespace-nowrap px-4 py-3 text-ink/70">{formatTime(task.created_at)}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${statusClass(task.status)}`}>
                        {statusLabel(task)}
                      </span>
                      {task.status === "failed" && task.error ? <p className="mt-1 max-w-40 text-xs text-danger">{task.error}</p> : null}
                    </td>
                    <td className="max-w-40 truncate px-4 py-3 font-medium">{task.name}</td>
                    <td className="max-w-52 truncate px-4 py-3 text-ink/70" title={task.path}>
                      {task.path}
                    </td>
                    <td className="min-w-40 px-4 py-3 text-ink/70">
                      {task.status === "running" && task.phase === "list" ? "正在统计大小" : null}
                      {task.status === "running" && task.phase !== "list" ? (
                        <div>
                          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                            <div className="h-full rounded-full bg-primary" style={{ width: `${percent}%` }} />
                          </div>
                          <p className="mt-1 text-xs">
                            {formatBytes(task.bytes_done)} / {formatBytes(task.bytes_total)} · {task.files_done}/{task.files_total}
                            {task.current_name ? ` · ${task.current_name}` : ""}
                          </p>
                        </div>
                      ) : null}
                      {task.status !== "running" ? `${task.files_done}/${task.files_total || task.files_done}` : null}
                    </td>
                    <td className="max-w-64 truncate px-4 py-3 text-ink/70" title={task.directory ?? ""}>
                      {task.directory || "—"}
                    </td>
                    <td className="px-4 py-3">
                      {task.status === "running" ? (
                        <button type="button" onClick={() => void cancelDownload(task.id)} className="text-sm text-[#f04438]">
                          取消
                        </button>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <TablePager
          page={paged.page}
          total={tasks.length}
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
