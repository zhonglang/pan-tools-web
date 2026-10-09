import type { User } from "../api";
import PageHeader from "../components/PageHeader";
import UpgradeContact from "../components/UpgradeContact";

function formatExpiry(value: string | null) {
  if (!value) return "未设置";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function planName(plan: string) {
  return plan === "paid" ? "付费" : "免费";
}

export default function ProfilePage({ user }: { user: User }) {
  const paid = user.effective_plan === "paid" || user.paid_features;
  const rows = [
    { label: "邮箱", value: user.email },
    { label: "角色", value: user.role === "admin" ? "管理员" : user.effective_plan === "paid" ? "付费用户" : "普通用户" },
    { label: "用户等级", value: planName(user.effective_plan) },
    { label: "到期时间", value: formatExpiry(user.plan_expires_at) },
    { label: "付费能力", value: paid ? "已开通" : "未开通" },
  ];

  return (
    <div className="mx-auto max-w-xl">
      <PageHeader title="个人信息" description="会员等级和到期时间。到期后用户等级会回到免费。" />
      <dl className="overflow-hidden rounded-2xl border border-line bg-white">
        {rows.map((row) => (
          <div key={row.label} className="grid grid-cols-[7.5rem_minmax(0,1fr)] gap-3 border-b border-line px-5 py-4 last:border-b-0">
            <dt className="text-sm text-ink/50">{row.label}</dt>
            <dd className="text-sm font-semibold text-ink">{row.value}</dd>
          </div>
        ))}
      </dl>
      {user.paid_features ? null : <UpgradeContact email={user.email} />}
    </div>
  );
}
