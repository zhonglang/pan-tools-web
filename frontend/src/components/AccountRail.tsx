import { Link } from "react-router-dom";
import type { PanAccount } from "../api";

const providerName: Record<string, string> = { baidu: "百度网盘", quark: "夸克", xunlei: "迅雷" };
const providerOrder = ["baidu", "quark", "xunlei"];

function groupedAccounts(rows: PanAccount[]) {
  const order = [...providerOrder];
  for (const row of rows) {
    if (!order.includes(row.provider)) order.push(row.provider);
  }
  return order
    .map((provider) => ({
      provider,
      label: providerName[provider] ?? provider,
      accounts: rows.filter((row) => row.provider === provider),
    }))
    .filter((group) => group.accounts.length > 0);
}

export default function AccountRail({
  accounts,
  accountId,
  onSelect,
}: {
  accounts: PanAccount[];
  accountId: number | null;
  onSelect: (account: PanAccount) => void;
}) {
  return (
    <aside className="flex w-full shrink-0 flex-col border-b border-line bg-white lg:w-[232px] lg:border-r lg:border-b-0">
      <div className="px-4 py-4">
        <p className="text-sm font-semibold text-ink">网盘</p>
      </div>
      <div className="max-h-72 space-y-4 overflow-y-auto px-3 pb-3 lg:max-h-none lg:min-h-0 lg:flex-1">
        {accounts.length === 0 ? (
          <p className="px-2 py-4 text-sm leading-6 text-ink/55">
            还没有网盘。先去
            <Link to="/accounts" className="font-medium text-primary-dark">
              绑定网盘账号
            </Link>
            。
          </p>
        ) : null}
        {groupedAccounts(accounts).map((group) => (
          <div key={group.provider}>
            <p className="px-1 pb-1.5 text-[12px] font-semibold text-ink/40">{group.label}</p>
            <div className="space-y-1 pl-4">
              {group.accounts.map((item) => {
                const active = item.id === accountId;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => onSelect(item)}
                    className={`flex w-full items-center gap-2.5 rounded-xl px-2 py-2.5 text-left ${
                      active ? "bg-muted ring-1 ring-primary/25" : "hover:bg-[#f7f8fa]"
                    }`}
                  >
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-muted text-[13px] font-semibold text-primary-dark">
                      {(providerName[item.provider] ?? "盘").slice(0, 1)}
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-semibold text-ink">{item.nickname}</span>
                      <span className="mt-0.5 block truncate text-xs text-[#8b909a]">
                        {item.status === "valid" ? "已登录" : "请重新登录"}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
}
