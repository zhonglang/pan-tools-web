import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Job } from "../api";

const statusName: Record<string, string> = {
  pending: "等待执行",
  running: "正在转存",
  succeeded: "全部成功",
  partial: "部分成功",
  failed: "全部失败",
};

export default function JobPage() {
  const { id } = useParams();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) return;
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

  return (
    <div className="mx-auto max-w-3xl">
      <Link to="/transfer" className="text-sm font-medium text-primary-dark">
        返回转存
      </Link>
      <h1 className="mt-3 text-3xl font-semibold tracking-tight">{job ? statusName[job.status] ?? job.status : "任务"}</h1>
      {job ? <p className="mt-2 text-sm text-ink/60">目录 {job.directory}</p> : null}
      {error ? <p className="mt-4 rounded-2xl bg-red-50 px-4 py-3 text-sm text-danger">{error}</p> : null}
      <ul className="mt-6 space-y-3">
        {job?.items.map((item) => (
          <li key={item.id} className="rounded-3xl border border-line bg-white p-4">
            <p className="break-all text-sm">{item.input_text}</p>
            <p className="mt-2 text-sm text-ink/60">{item.error ?? item.result ?? statusName[item.status] ?? item.status}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
