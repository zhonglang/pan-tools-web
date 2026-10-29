import { useEffect, useRef, useState } from "react";
import { api, type AccountStats, type PanAccount, type User } from "../api";
import AccountSelect from "../components/AccountSelect";
import DateRangePicker, { shortcutRange } from "../components/DateRangePicker";
import PageHeader from "../components/PageHeader";
import UpgradeContact from "../components/UpgradeContact";
import TableLoading from "../components/TableLoading";
import TablePager, { PAGE_SIZE } from "../components/TablePager";
import TransferChart from "../components/TransferChart";

function formatTime(value: string | null | undefined) {
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

function deltaText(value: number | null) {
  if (value == null) return "暂无";
  if (value > 0) return `+${value}`;
  return String(value);
}

function CopyIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" aria-hidden="true">
      <rect x="9" y="3" width="11" height="14" rx="2" stroke="currentColor" strokeWidth="1.75" />
      <rect x="4" y="7" width="11" height="14" rx="2" stroke="currentColor" strokeWidth="1.75" />
    </svg>
  );
}

export default function StatsPage({ user }: { user: User }) {
  const initialRange = shortcutRange("today");
  const [accounts, setAccounts] = useState<PanAccount[]>([]);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [start, setStart] = useState(initialRange.start);
  const [end, setEnd] = useState(initialRange.end);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [nameInput, setNameInput] = useState("");
  const [nameQuery, setNameQuery] = useState("");
  const [stats, setStats] = useState<AccountStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [accountsLoaded, setAccountsLoaded] = useState(false);
  const [toast, setToast] = useState("");
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const statsTicket = useRef(0);
  const toastTimer = useRef(0);
  const ranged = Boolean(start && end);

  function showToast(message: string) {
    setToast(message);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(""), 1800);
  }

  async function copyLink(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      showToast("已复制");
    } catch {
      showToast("复制失败");
    }
  }

  async function copySelected() {
    const urls = [...selected];
    if (urls.length === 0) return;
    try {
      await navigator.clipboard.writeText(urls.join("\n"));
      showToast(`已复制 ${urls.length} 条`);
    } catch {
      showToast("复制失败");
    }
  }

  function toggleUrl(url: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(url)) next.delete(url);
      else next.add(url);
      return next;
    });
  }

  function togglePage(urls: string[]) {
    setSelected((current) => {
      const next = new Set(current);
      const allOn = urls.length > 0 && urls.every((url) => next.has(url));
      if (allOn) {
        for (const url of urls) next.delete(url);
      } else {
        for (const url of urls) next.add(url);
      }
      return next;
    });
  }

  function loadAccounts() {
    return api
      .accounts()
      .then((rows) => {
        setAccounts(rows.filter((row) => row.provider === "baidu"));
      })
      .catch((caught: Error) => setError(caught.message))
      .finally(() => setAccountsLoaded(true));
  }

  useEffect(() => {
    if (!user.paid_features) return;
    void loadAccounts();
  }, [user.paid_features]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const next = nameInput.trim();
      setNameQuery((prev) => {
        if (prev !== next) setPage(1);
        return next;
      });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [nameInput]);

  useEffect(() => {
    setSelected(new Set());
  }, [accountId, end, nameQuery, start]);

  useEffect(() => {
    if (!user.paid_features) return;
    if (ranged && start > end) {
      setError("开始日期不能晚于结束日期");
      setLoading(false);
      return;
    }
    const ticket = ++statsTicket.current;
    setLoading(true);
    api
      .statsQuery(accountId, page, pageSize, ranged ? start : null, ranged ? end : null, nameQuery || null)
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
  }, [accountId, end, nameQuery, page, pageSize, ranged, start, user.paid_features]);

  const account = accounts.find((row) => row.id === accountId) ?? null;
  const pageUrls = stats?.rows.map((row) => row.url) ?? [];
  const pageAllSelected = pageUrls.length > 0 && pageUrls.every((url) => selected.has(url));
  const pageSomeSelected = pageUrls.some((url) => selected.has(url));
  const colSpan = (ranged ? 8 : 7) + 1;

  const syncTargets = (accountId == null ? accounts : account ? [account] : []).filter(
    (row) => row.provider === "baidu" && row.status === "valid",
  );
  const baiduAccounts = accounts.filter((row) => row.provider === "baidu");

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
      await loadAccounts();
      setStats(await api.statsQuery(accountId, page, pageSize, ranged ? start : null, ranged ? end : null, nameQuery || null));
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
        {
          label: "总链接",
          value: String(stats.total),
          note: ranged ? "不含开始日，只计其后新建" : "当前有效分享总数",
          tone: "#0f766e",
        },
        {
          label: "总转存",
          value: metricText(stats.transfers.value),
          note: ranged ? (stats.transfers.value == null ? "日表不足，暂无水位差" : "区间水位差") : "当前累计",
          tone: "#9a3412",
        },
        {
          label: "总浏览",
          value: metricText(stats.views.value),
          note: ranged ? (stats.views.value == null ? "日表不足，暂无水位差" : "区间水位差") : "当前累计",
          tone: "#44403c",
        },
        {
          label: "总下载",
          value: metricText(stats.downloads.value),
          note: ranged ? (stats.downloads.value == null ? "日表不足，暂无水位差" : "区间水位差") : "当前累计",
          tone: "#a16207",
        },
      ]
    : [];

  return (
    <div>
      <PageHeader
        title="数据概览"
        description={`首次成功快照：${formatTime(stats?.first_snapshot_at ?? null)}。数字按北京时间统计。`}
        extra={
          <div className="group relative">
            <button type="button" className="btn btn-primary" disabled={syncing || syncTargets.length === 0} onClick={() => void refresh()}>
              {syncing ? "正在同步" : "刷新数据"}
            </button>
            <div className="pointer-events-none absolute right-0 top-full z-20 mt-2 hidden w-72 rounded-xl border border-line bg-white p-3 text-left text-[12px] shadow-lg group-hover:block">
              <p className="mb-2 font-medium text-ink/70">各网盘最近更新</p>
              {baiduAccounts.length === 0 ? (
                <p className="text-ink/45">暂无百度账号</p>
              ) : (
                <ul className="space-y-1.5">
                  {baiduAccounts.map((row) => (
                    <li key={row.id} className="flex items-start justify-between gap-3">
                      <span className="min-w-0 truncate text-ink/80">{row.nickname || "未命名账号"}</span>
                      <span className="shrink-0 tabular-nums text-ink/55">{formatTime(row.last_synced_at)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
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
        <DateRangePicker
          start={start}
          end={end}
          onChange={(nextStart, nextEnd) => {
            setStart(nextStart);
            setEnd(nextEnd);
            setPage(1);
          }}
        />
        {ranged ? (
          <button
            type="button"
            className="h-10 rounded-lg border border-line px-3 text-sm text-ink/70 hover:border-primary hover:text-ink"
            onClick={() => {
              setStart("");
              setEnd("");
              setPage(1);
            }}
          >
            清除日期
          </button>
        ) : (
          <span className="text-sm text-ink/45">未选日期时显示历史累计</span>
        )}
      </div>
      {account && account.status !== "valid" ? <p className="mb-4 text-sm text-ink/55">这个账号需要重新登录后才能刷新。</p> : null}
      {ranged ? (
        <p className="mb-3 text-sm text-ink/55">
          总链接不含开始日当天新建的分享；例如选 10/14～10/15，只统计 10/15 当天新建的链接。
        </p>
      ) : null}
      <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
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
      {ranged ? (
        stats ? (
          <TransferChart dates={stats.dates} lines={stats.lines} start={start} end={end} />
        ) : (
          <section className="mt-4 flex aspect-[720/280] items-center justify-center rounded-2xl border border-line bg-white px-5 text-sm text-ink/45">
            正在读取转存趋势。
          </section>
        )
      ) : null}
      <section className="mt-6 overflow-hidden rounded-2xl border border-line bg-white">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-base font-semibold">分享列表</h2>
            {selected.size > 0 ? (
              <>
                <span className="text-sm text-ink/55">已选 {selected.size}</span>
                <button type="button" className="btn btn-secondary" onClick={() => void copySelected()}>
                  复制全部链接
                </button>
                <button type="button" className="text-sm text-ink/45 hover:text-ink" onClick={() => setSelected(new Set())}>
                  清空
                </button>
              </>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <input
              type="search"
              value={nameInput}
              onChange={(event) => setNameInput(event.target.value)}
              placeholder="按分析名称搜索"
              className="h-9 w-52 rounded-lg border border-line bg-white px-3 text-sm outline-none focus:border-primary"
            />
            <p className="text-xs text-ink/45">{ranged ? "浏览/下载/转存量为结束日水位，转存增量为结束日减开始日" : "指标为当前累计"}</p>
          </div>
        </div>
        <p className="px-4 py-3 text-sm text-ink/55">
          {ranged
            ? "浏览量、下载量、转存量为结束日快照；转存增量为结束日减去开始日。周期内新建的链接，转存增量等于转存量。"
            : "按当前账号，比较各分享当前的浏览、下载和转存累计。"}
        </p>
        <div className="max-h-[32rem] overflow-auto">
          <table className={`w-full border-collapse text-left text-sm ${ranged ? "min-w-[900px]" : "min-w-[800px]"}`}>
            <thead className="sticky top-0 bg-canvas text-[12px] text-ink/50">
              <tr>
                <th className="w-10 px-4 py-3">
                  <input
                    type="checkbox"
                    aria-label="全选本页"
                    checked={pageAllSelected}
                    ref={(node) => {
                      if (node) node.indeterminate = !pageAllSelected && pageSomeSelected;
                    }}
                    disabled={pageUrls.length === 0 || loading}
                    onChange={() => togglePage(pageUrls)}
                  />
                </th>
                <th className="px-4 py-3 font-medium">排名</th>
                <th className="px-4 py-3 font-medium">分析名称</th>
                <th className="px-4 py-3 font-medium">账号名称</th>
                <th className="px-4 py-3 font-medium">分享链接</th>
                <th className="px-4 py-3 font-medium">浏览量</th>
                <th className="px-4 py-3 font-medium">下载量</th>
                <th className="px-4 py-3 font-medium">转存量</th>
                {ranged ? <th className="px-4 py-3 font-medium">转存增量</th> : null}
              </tr>
            </thead>
            <tbody>
              {loading ? <TableLoading colSpan={colSpan} /> : null}
              {!loading && accountsLoaded && accounts.length === 0 ? (
                <tr>
                  <td colSpan={colSpan} className="px-4 py-10 text-center text-ink/45">
                    还没有网盘账号。
                  </td>
                </tr>
              ) : null}
              {!loading && stats && accounts.length > 0 && stats.rows.length === 0 ? (
                <tr>
                  <td colSpan={colSpan} className="px-4 py-10 text-center text-ink/45">
                    {nameQuery ? "没有匹配的分享。" : "还没有可统计的分享。"}
                  </td>
                </tr>
              ) : null}
              {!loading
                ? stats?.rows.map((row, index) => (
                    <tr key={row.url} className="border-t border-line">
                      <td className="px-4 py-3">
                        <input
                          type="checkbox"
                          aria-label={`选择 ${row.name || row.url}`}
                          checked={selected.has(row.url)}
                          onChange={() => toggleUrl(row.url)}
                        />
                      </td>
                      <td className="px-4 py-3 text-ink/70">{(stats.page - 1) * stats.page_size + index + 1}</td>
                      <td className="max-w-40 truncate px-4 py-3 font-medium">{row.name || "—"}</td>
                      <td className="max-w-40 truncate px-4 py-3">{row.account_name || "—"}</td>
                      <td className="max-w-md px-4 py-3">
                        <div className="flex items-start gap-2">
                          <a href={row.url} target="_blank" rel="noreferrer" className="min-w-0 break-all text-ink hover:underline">
                            {row.url}
                          </a>
                          <button
                            type="button"
                            aria-label="复制分享链接"
                            title="复制链接"
                            className="mt-0.5 shrink-0 text-ink/40 hover:text-ink"
                            onClick={() => void copyLink(row.url)}
                          >
                            <CopyIcon />
                          </button>
                        </div>
                      </td>
                      <td className="px-4 py-3">{metricText(row.views)}</td>
                      <td className="px-4 py-3">{metricText(row.downloads)}</td>
                      <td className="px-4 py-3">{metricText(row.transfers)}</td>
                      {ranged ? (
                        <td className={`px-4 py-3 ${(row.transfer_delta ?? 0) > 0 ? "font-medium text-emerald-600" : ""}`}>
                          {deltaText(row.transfer_delta ?? null)}
                        </td>
                      ) : null}
                    </tr>
                  ))
                : null}
            </tbody>
          </table>
        </div>
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
      </section>
      {toast ? (
        <div className="fixed bottom-6 left-1/2 z-40 -translate-x-1/2 rounded-full bg-[#1f2430] px-4 py-2 text-sm text-white shadow-lg">
          {toast}
        </div>
      ) : null}
    </div>
  );
}
