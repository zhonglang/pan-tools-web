import { useEffect, useRef, useState } from "react";
import { api, type AccountStats, type CreatedShares, type PanAccount, type User } from "../api";
import AccountSelect from "../components/AccountSelect";
import DateRangePicker, { shortcutRange } from "../components/DateRangePicker";
import PageHeader from "../components/PageHeader";
import UpgradeContact from "../components/UpgradeContact";
import TableLoading from "../components/TableLoading";
import TablePager, { PAGE_SIZE } from "../components/TablePager";
import TransferChart from "../components/TransferChart";

function formatTime(value: string | null) {
  if (!value) return "尚未同步";
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

function metricText(value: number | null) {
  return value == null ? "暂无" : String(value);
}

function metricNote(metric: { value: number | null; from_time: string | null }, rank: string) {
  if (rank === "history") return metric.value == null ? "暂无累计" : "历史累计";
  if (metric.from_time) return `本段从 ${formatTime(metric.from_time)} 起算`;
  if (metric.value == null) return "快照不足，暂无增量";
  return "按本段开始前的快照计算";
}

export default function StatsPage({ user }: { user: User }) {
  const initialRange = shortcutRange("week");
  const [accounts, setAccounts] = useState<PanAccount[]>([]);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [rank, setRank] = useState("range");
  const [start, setStart] = useState(initialRange.start);
  const [end, setEnd] = useState(initialRange.end);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [stats, setStats] = useState<AccountStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [accountsLoaded, setAccountsLoaded] = useState(false);
  const createdInitial = shortcutRange("week");
  const [createdStart, setCreatedStart] = useState(createdInitial.start);
  const [createdEnd, setCreatedEnd] = useState(createdInitial.end);
  const [createdPage, setCreatedPage] = useState(1);
  const [createdPageSize, setCreatedPageSize] = useState(PAGE_SIZE);
  const [created, setCreated] = useState<CreatedShares | null>(null);
  const [createdLoading, setCreatedLoading] = useState(true);
  const [createdError, setCreatedError] = useState("");
  const [panel, setPanel] = useState<"rank" | "created">("rank");
  const statsTicket = useRef(0);
  const createdTicket = useRef(0);

  useEffect(() => {
    if (!user.paid_features) return;
    api
      .accounts()
      .then((rows) => {
        setAccounts(rows.filter((row) => row.provider === "baidu" || row.provider === "quark"));
      })
      .catch((caught: Error) => setError(caught.message))
      .finally(() => setAccountsLoaded(true));
  }, [user.paid_features]);

  useEffect(() => {
    if (!user.paid_features) return;
    if (rank === "range" && start > end) {
      setError("开始日期不能晚于结束日期");
      setLoading(false);
      return;
    }
    const ticket = ++statsTicket.current;
    setLoading(true);
    api
      .statsQuery(accountId, rank, page, pageSize, start, end)
      .then((next) => {
        if (ticket !== statsTicket.current) return;
        setStats(next);
        setError("");
        setLoading(false);
      })
      .catch((caught: Error) => {
        if (ticket !== statsTicket.current) return;
        setError(caught.message);
        setLoading(false);
      });
  }, [accountId, end, page, pageSize, rank, start, user.paid_features]);

  useEffect(() => {
    if (!user.paid_features) return;
    if (createdStart > createdEnd) {
      setCreatedError("开始日期不能晚于结束日期");
      setCreatedLoading(false);
      return;
    }
    const ticket = ++createdTicket.current;
    setCreatedLoading(true);
    api
      .createdShares(createdPage, createdPageSize, createdStart, createdEnd)
      .then((next) => {
        if (ticket !== createdTicket.current) return;
        setCreated(next);
        setCreatedError("");
        setCreatedLoading(false);
      })
      .catch((caught: Error) => {
        if (ticket !== createdTicket.current) return;
        setCreatedError(caught.message);
        setCreatedLoading(false);
      });
  }, [createdEnd, createdPage, createdPageSize, createdStart, user.paid_features]);

  const account = accounts.find((row) => row.id === accountId) ?? null;

  const syncTargets = accountId == null ? accounts.filter((row) => row.status === "valid") : account?.status === "valid" ? [account] : [];

  async function refresh() {
    if (syncTargets.length === 0) return;
    setSyncing(true);
    setError("");
    try {
      for (const target of syncTargets) {
        let job = await api.syncAccount(target.id);
        while (job.status === "pending" || job.status === "running") {
          await new Promise((resolve) => window.setTimeout(resolve, 2000));
          job = await api.job(String(job.id));
        }
        if (job.status === "failed") setError(job.error || "同步失败");
      }
      setStats(await api.statsQuery(accountId, rank, page, pageSize, start, end));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "同步失败");
    } finally {
      setSyncing(false);
    }
  }

  if (!user.paid_features) {
    return (
      <div>
        <PageHeader title="数据概览" description="该功能仅对付费会员开放。" />
        <UpgradeContact email={user.email} />
      </div>
    );
  }

  const cards = stats
    ? [
        { label: "分享总量", value: String(stats.total), note: "当前仍在分享列表中的记录", tone: "#0f766e" },
        { label: "新增分享", value: String(stats.new_shares), note: rank === "history" ? "全部有效分享" : "按分享创建时间计入本段", tone: "#0e7490" },
        { label: "转存", value: metricText(stats.transfers.value), note: metricNote(stats.transfers, rank), tone: "#9a3412" },
        { label: "浏览", value: metricText(stats.views.value), note: metricNote(stats.views, rank), tone: "#44403c" },
        { label: "下载", value: metricText(stats.downloads.value), note: metricNote(stats.downloads, rank), tone: "#a16207" },
      ]
    : [];

  return (
    <div>
      <PageHeader
        title="数据概览"
        description={`首次成功快照：${formatTime(stats?.first_snapshot_at ?? null)}。数字按北京时间统计。`}
        extra={
          <button type="button" className="btn btn-primary" disabled={syncing || syncTargets.length === 0} onClick={() => void refresh()}>
            {syncing ? "正在同步" : "刷新数据"}
          </button>
        }
      />
      {error ? <p className="alert -mt-4 mb-4">{error}</p> : null}
      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-2xl border border-line bg-white px-4 py-3">
        <AccountSelect
          accounts={accounts}
          value={accountId}
          onChange={(id) => {
            setAccountId(id);
            setPage(1);
          }}
        />
        <div className="inline-flex rounded-xl bg-canvas p-1">
          <button
            type="button"
            aria-pressed={rank === "range"}
            className={`h-8 rounded-lg px-3 text-sm font-semibold ${rank === "range" ? "bg-white text-ink" : "text-ink/55"}`}
            onClick={() => {
              setRank("range");
              setPage(1);
            }}
          >
            时间范围增量
          </button>
          <button
            type="button"
            aria-pressed={rank === "history"}
            className={`h-8 rounded-lg px-3 text-sm font-semibold ${rank === "history" ? "bg-white text-ink" : "text-ink/55"}`}
            onClick={() => {
              setRank("history");
              setPage(1);
            }}
          >
            历史累计
          </button>
        </div>
        {rank === "range" ? (
          <DateRangePicker
            start={start}
            end={end}
            onChange={(nextStart, nextEnd) => {
              setStart(nextStart);
              setEnd(nextEnd);
              setPage(1);
            }}
          />
        ) : null}
      </div>
      {account && account.status !== "valid" ? <p className="mb-4 text-sm text-ink/55">这个账号需要重新登录后才能刷新。</p> : null}
      <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-5">
        {cards.map((card) => (
          <article
            key={card.label}
            className="rounded-2xl border border-line border-t-[3px] bg-white px-3.5 py-3"
            style={{ borderTopColor: card.tone }}
          >
            <div className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: card.tone }} />
              <p className="text-[12px] font-semibold text-ink/55">{card.label}</p>
            </div>
            <p className={`mt-1.5 text-[1.45rem] font-extrabold leading-none tracking-[-0.04em] ${card.value === "暂无" ? "text-ink/30" : "text-ink"}`}>
              {card.value}
            </p>
            <div className="mt-2 h-px bg-line" />
            <p className="mt-1.5 truncate text-[12px] leading-4 text-ink/45" title={card.note}>
              {card.note}
            </p>
          </article>
        ))}
      </div>
      {stats ? (
        <TransferChart dates={stats.dates} lines={stats.lines} mode={rank} start={start} end={end} />
      ) : (
        <section className="mt-4 flex aspect-[720/280] items-center justify-center rounded-2xl border border-line bg-white px-5 text-sm text-ink/45">正在读取转存趋势。</section>
      )}
      <section className="mt-6 overflow-hidden rounded-2xl border border-line bg-white">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
          <div className="flex gap-1 rounded-xl bg-canvas p-1" role="tablist" aria-label="数据表格">
            {(
              [
                ["rank", "分享排名"],
                ["created", "新建分享"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={panel === id}
                className={`h-9 rounded-lg px-4 text-sm font-semibold ${
                  panel === id ? "bg-white text-ink" : "text-ink/50 hover:text-ink"
                }`}
                onClick={() => setPanel(id)}
              >
                {label}
              </button>
            ))}
          </div>
          {panel === "created" ? (
            <DateRangePicker
              label="选择创建时间"
              align="right"
              start={createdStart}
              end={createdEnd}
              onChange={(nextStart, nextEnd) => {
                setCreatedStart(nextStart);
                setCreatedEnd(nextEnd);
                setCreatedPage(1);
              }}
            />
          ) : (
            <p className="text-xs text-ink/45">跟着上方的账号和时间。</p>
          )}
        </div>
        <p className="px-4 py-3 text-sm text-ink/55">
          {panel === "rank"
            ? "按当前账号和时间，比较各分享的浏览、下载和转存。"
            : "只看这段时间里新建的分享。转存、下载和浏览是这些链接现在的数字，不按账号筛选。"}
        </p>
        {panel === "created" && createdError ? <p className="alert mx-4 mb-3">{createdError}</p> : null}
        <div className="max-h-[32rem] overflow-auto">
          {panel === "rank" ? (
          <table className="w-full min-w-[760px] border-collapse text-left text-sm">
            <thead className="sticky top-0 bg-canvas text-[12px] text-ink/50">
              <tr>
                <th className="px-4 py-3 font-medium">排名</th>
                <th className="px-4 py-3 font-medium">分析名称</th>
                <th className="px-4 py-3 font-medium">账号名称</th>
                <th className="px-4 py-3 font-medium">分享链接</th>
                <th className="px-4 py-3 font-medium">浏览量</th>
                <th className="px-4 py-3 font-medium">下载量</th>
                <th className="px-4 py-3 font-medium">转存量</th>
              </tr>
            </thead>
            <tbody>
              {loading ? <TableLoading colSpan={7} /> : null}
              {!loading && accountsLoaded && accounts.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-ink/45">
                    还没有网盘账号。
                  </td>
                </tr>
              ) : null}
              {!loading && stats && accounts.length > 0 && stats.rows.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-ink/45">
                    还没有可统计的分享。
                  </td>
                </tr>
              ) : null}
              {!loading
                ? stats?.rows.map((row, index) => (
                    <tr key={row.url} className="border-t border-line">
                      <td className="px-4 py-3 text-ink/70">{(stats.page - 1) * stats.page_size + index + 1}</td>
                      <td className="max-w-40 truncate px-4 py-3 font-medium">{row.name || "—"}</td>
                      <td className="max-w-40 truncate px-4 py-3">{row.account_name || "—"}</td>
                      <td className="max-w-md break-all px-4 py-3">
                        <a href={row.url} target="_blank" rel="noreferrer" className="text-ink hover:underline">
                          {row.url}
                        </a>
                      </td>
                      <td className="px-4 py-3">{metricText(row.views)}</td>
                      <td className="px-4 py-3">{metricText(row.downloads)}</td>
                      <td className="px-4 py-3">{metricText(row.transfers)}</td>
                    </tr>
                  ))
                : null}
            </tbody>
          </table>
          ) : (
          <table className="w-full min-w-[860px] border-collapse text-left text-sm">
            <thead className="sticky top-0 bg-canvas text-[12px] text-ink/50">
              <tr>
                <th className="px-4 py-3 font-medium">序号</th>
                <th className="px-4 py-3 font-medium">分析名称</th>
                <th className="px-4 py-3 font-medium">账号名称</th>
                <th className="px-4 py-3 font-medium">分享链接</th>
                <th className="px-4 py-3 font-medium">创建时间</th>
                <th className="px-4 py-3 font-medium">浏览量</th>
                <th className="px-4 py-3 font-medium">下载量</th>
                <th className="px-4 py-3 font-medium">转存量</th>
              </tr>
            </thead>
            <tbody>
              {createdLoading ? <TableLoading colSpan={8} /> : null}
              {!createdLoading && created && created.rows.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-10 text-center text-ink/45">
                    这段时间没有新建分享。
                  </td>
                </tr>
              ) : null}
              {!createdLoading
                ? created?.rows.map((row, index) => (
                    <tr key={`${row.url}-${row.created_at}`} className="border-t border-line">
                      <td className="px-4 py-3 text-ink/70">{(created.page - 1) * created.page_size + index + 1}</td>
                      <td className="max-w-40 truncate px-4 py-3 font-medium">{row.name || "—"}</td>
                      <td className="max-w-40 truncate px-4 py-3">{row.account_name || "—"}</td>
                      <td className="max-w-md break-all px-4 py-3">
                        <a href={row.url} target="_blank" rel="noreferrer" className="text-ink hover:underline">
                          {row.url}
                        </a>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-ink/70">{formatTime(row.created_at)}</td>
                      <td className="px-4 py-3">{metricText(row.views)}</td>
                      <td className="px-4 py-3">{metricText(row.downloads)}</td>
                      <td className="px-4 py-3">{metricText(row.transfers)}</td>
                    </tr>
                  ))
                : null}
            </tbody>
          </table>
          )}
        </div>
        {panel === "rank" ? (
          <TablePager
            page={page}
            total={stats?.rank_total ?? 0}
            pageSize={pageSize}
            onPage={setPage}
            onPageSize={(size) => {
              setPageSize(size);
              setPage(1);
            }}
          />
        ) : (
          <TablePager
            page={createdPage}
            total={created?.total ?? 0}
            pageSize={createdPageSize}
            onPage={setCreatedPage}
            onPageSize={(size) => {
              setCreatedPageSize(size);
              setCreatedPage(1);
            }}
          />
        )}
      </section>
    </div>
  );
}
