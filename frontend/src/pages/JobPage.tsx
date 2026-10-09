import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Job } from "../api";
import PageHeader from "../components/PageHeader";
import TableLoading from "../components/TableLoading";
import TablePager, { PAGE_SIZE, pageOf } from "../components/TablePager";

const jobStatusName: Record<string, string> = {
  pending: "等待执行",
  succeeded: "全部成功",
  partial: "部分成功",
  failed: "全部失败",
};

const itemStatusName: Record<string, string> = {
  pending: "等待执行",
  succeeded: "成功",
  failed: "失败",
};

function runningName(type: string) {
  if (type === "share") return "正在分享";
  if (type === "sync") return "正在同步";
  return "正在转存";
}

function itemStatus(status: string, type: string) {
  if (status === "running") return runningName(type);
  return itemStatusName[status] ?? status;
}

function itemLabel(text: string) {
  try {
    const data = JSON.parse(text) as { name?: string; path?: string };
    if (typeof data.path === "string") return data.name ? `${data.name} · ${data.path}` : data.path;
  } catch {
    /* 转存任务保存的是原始链接 */
  }
  return text;
}

function statusClass(status: string) {
  if (status === "succeeded") return "bg-[#e7f8ef] text-[#067647]";
  if (status === "failed") return "bg-[#fef3f2] text-[#b42318]";
  if (status === "partial" || status === "running") return "bg-muted text-primary-dark";
  return "bg-[#f2f4f7] text-[#475467]";
}

export default function JobPage() {
  const { id } = useParams();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);

  useEffect(() => {
    if (!id) return;
    setJob(null);
    setError("");
    let timer = 0;
    let stopped = false;
    async function poll() {
      try {
        const next = await api.job(id as string);
        if (stopped) return;
        setJob(next);
        if (next.status === "pending" || next.status === "running") {
          timer = window.setTimeout(poll, 2000);
        }
      } catch (caught) {
        if (!stopped) setError(caught instanceof Error ? caught.message : "任务不存在");
      }
    }
    void poll();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [id]);

  const visible = useMemo(() => {
    const query = keyword.trim().toLowerCase();
    return (job?.items ?? []).filter((item) => {
      if (statusFilter !== "all" && item.status !== statusFilter) return false;
      if (!query) return true;
      const text = `${itemLabel(item.input_text)} ${item.error ?? ""} ${item.result ?? ""}`.toLowerCase();
      return text.includes(query);
    });
  }, [job, keyword, statusFilter]);

  useEffect(() => {
    setPage(1);
  }, [id, keyword, statusFilter]);

  const paged = pageOf(visible, page, pageSize);

  return (
    <div>
      <div className="mb-6 flex flex-wrap gap-4 text-sm">
        <Link to="/jobs" className="font-medium text-ink/55 hover:text-ink">
          ← 任务列表
        </Link>
        <Link to="/transfer" className="font-medium text-ink/55 hover:text-ink">
          返回转存
        </Link>
        {job?.type === "share" ? (
          <a href={`/api/jobs/${job.id}/export`} className="font-medium text-ink/55 hover:text-ink">
            导出 CSV
          </a>
        ) : null}
      </div>
      <PageHeader
        title={job ? (job.status === "running" ? runningName(job.type) : jobStatusName[job.status] ?? job.status) : "任务详情"}
        description={job ? (job.type === "sync" ? "同步这个账号的全部分享记录" : `目录 ${job.directory}`) : undefined}
      />
      {error ? <p className="alert -mt-4 mb-4">{error}</p> : null}
      {job?.error ? <p className="alert -mt-4 mb-4">{job.error}</p> : null}
      <div className="mb-4 flex flex-wrap gap-3">
        <select className="h-10 rounded-xl border border-line bg-white px-3 text-sm" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} aria-label="按状态筛选">
          <option value="all">全部状态</option>
          <option value="pending">等待执行</option>
          <option value="running">{runningName(job?.type ?? "transfer")}</option>
          <option value="succeeded">成功</option>
          <option value="failed">失败</option>
        </select>
        <input
          className="h-10 min-w-56 rounded-xl border border-line bg-white px-3 text-sm"
          value={keyword}
          placeholder={job?.type === "share" ? "筛选文件或结果" : "筛选链接或结果"}
          aria-label="按内容筛选"
          onChange={(event) => setKeyword(event.target.value)}
        />
      </div>
      <div className="overflow-hidden rounded-2xl border border-line bg-white">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] border-collapse text-left text-sm">
            <thead className="bg-canvas text-[12px] text-ink/50">
              <tr>
                <th className="px-4 py-3 font-medium">{job?.type === "share" ? "文件" : "链接"}</th>
                <th className="px-4 py-3 font-medium">状态</th>
                <th className="px-4 py-3 font-medium">结果</th>
                <th className="px-4 py-3 font-medium">重试</th>
              </tr>
            </thead>
            <tbody>
              {!job && !error ? <TableLoading colSpan={4} /> : null}
              {job && job.items.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-10 text-center text-ink/45">
                    这个任务没有条目。
                  </td>
                </tr>
              ) : null}
              {job && job.items.length > 0 && visible.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-10 text-center text-ink/45">
                    没有符合筛选条件的条目。
                  </td>
                </tr>
              ) : null}
              {paged.rows.map((item) => (
                <tr key={item.id} className="border-t border-line">
                  <td className="max-w-md break-all px-4 py-3 text-ink">{itemLabel(item.input_text)}</td>
                  <td className="whitespace-nowrap px-4 py-3">
                    <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${statusClass(item.status)}`}>
                      {itemStatus(item.status, job?.type ?? "transfer")}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-ink/70">{item.error ?? item.result ?? "—"}</td>
                  <td className="px-4 py-3 text-ink/70">{item.attempts}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
      </div>
    </div>
  );
}
