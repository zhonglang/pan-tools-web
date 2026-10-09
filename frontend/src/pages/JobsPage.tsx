import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type JobSummary } from "../api";
import PageHeader from "../components/PageHeader";
import TableLoading from "../components/TableLoading";
import TablePager, { PAGE_SIZE, pageOf } from "../components/TablePager";

const statusName: Record<string, string> = {
  pending: "等待执行",
  succeeded: "全部成功",
  partial: "部分成功",
  failed: "全部失败",
};

const typeName: Record<string, string> = {
  transfer: "转存",
  share: "分享",
  sync: "同步",
};

function taskStatus(job: JobSummary) {
  if (job.status === "running") {
    if (job.type === "share") return "正在分享";
    if (job.type === "sync") return "正在同步";
    return "正在转存";
  }
  return statusName[job.status] ?? job.status;
}

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

function statusClass(status: string) {
  if (status === "succeeded") return "bg-[#e7f8ef] text-[#067647]";
  if (status === "failed") return "bg-[#fef3f2] text-[#b42318]";
  if (status === "partial") return "bg-[#fffaeb] text-[#b54708]";
  if (status === "running") return "bg-muted text-primary-dark";
  return "bg-[#f2f4f7] text-[#475467]";
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [error, setError] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api
      .jobs()
      .then(setJobs)
      .catch((caught: Error) => setError(caught.message))
      .finally(() => setLoaded(true));
  }, []);

  const visible = useMemo(() => {
    const query = keyword.trim().toLowerCase();
    return jobs.filter((job) => {
      if (typeFilter !== "all" && job.type !== typeFilter) return false;
      if (statusFilter !== "all" && job.status !== statusFilter) return false;
      if (query && !job.directory.toLowerCase().includes(query)) return false;
      return true;
    });
  }, [jobs, keyword, statusFilter, typeFilter]);

  useEffect(() => {
    setPage(1);
  }, [keyword, statusFilter, typeFilter]);

  const paged = pageOf(visible, page, pageSize);

  return (
    <div>
      <PageHeader title="任务" description="转存、分享和同步都会出现在这里。点「详情」查看结果。" />
      {error ? <p className="alert mb-4">{error}</p> : null}
      <div className="mb-4 flex flex-wrap gap-3">
        <select className="h-10 rounded-xl border border-line bg-white px-3 text-sm" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)} aria-label="按类型筛选">
          <option value="all">全部类型</option>
          <option value="transfer">转存</option>
          <option value="share">分享</option>
          <option value="sync">同步</option>
        </select>
        <select className="h-10 rounded-xl border border-line bg-white px-3 text-sm" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} aria-label="按状态筛选">
          <option value="all">全部状态</option>
          <option value="pending">等待执行</option>
          <option value="running">正在执行</option>
          <option value="succeeded">全部成功</option>
          <option value="partial">部分成功</option>
          <option value="failed">全部失败</option>
        </select>
        <input
          className="h-10 min-w-48 rounded-xl border border-line bg-white px-3 text-sm"
          value={keyword}
          placeholder="筛选目录"
          aria-label="按目录筛选"
          onChange={(event) => setKeyword(event.target.value)}
        />
      </div>
      <div className="overflow-hidden rounded-2xl border border-line bg-white">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[960px] border-collapse text-left text-sm">
            <thead className="bg-canvas text-[12px] text-ink/50">
              <tr>
                <th className="px-4 py-3 font-medium">时间</th>
                <th className="px-4 py-3 font-medium">类型</th>
                <th className="px-4 py-3 font-medium">状态</th>
                <th className="px-4 py-3 font-medium">目录</th>
                <th className="px-4 py-3 font-medium">总数</th>
                <th className="px-4 py-3 font-medium">成功</th>
                <th className="px-4 py-3 font-medium">失败</th>
                <th className="px-4 py-3 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {!loaded ? <TableLoading colSpan={8} /> : null}
              {loaded && jobs.length === 0 && !error ? (
                <tr>
                  <td colSpan={8} className="px-4 py-10 text-center text-ink/45">
                    还没有任务。
                  </td>
                </tr>
              ) : null}
              {loaded && jobs.length > 0 && visible.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-10 text-center text-ink/45">
                    没有符合筛选条件的任务。
                  </td>
                </tr>
              ) : null}
              {paged.rows.map((job) => (
                <tr key={job.id} className="border-t border-line hover:bg-canvas">
                  <td className="whitespace-nowrap px-4 py-3 text-ink/70">{formatTime(job.created_at)}</td>
                  <td className="px-4 py-3">{typeName[job.type] ?? job.type}</td>
                  <td className="px-4 py-3">
                    <Link to={`/jobs/${job.id}`} className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${statusClass(job.status)}`}>
                      {taskStatus(job)}
                    </Link>
                  </td>
                  <td className="max-w-xs truncate px-4 py-3">
                    <Link to={`/jobs/${job.id}`} className="text-ink hover:text-primary-dark">
                      {job.type === "sync" && job.directory === "daily-close" ? "凌晨同步" : job.directory}
                    </Link>
                  </td>
                  <td className="px-4 py-3">{job.total}</td>
                  <td className="px-4 py-3">{job.succeeded}</td>
                  <td className="px-4 py-3">{job.failed}</td>
                  <td className="px-4 py-3">
                    <Link to={`/jobs/${job.id}`} className="font-medium text-primary-dark hover:underline">
                      详情
                    </Link>
                  </td>
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
