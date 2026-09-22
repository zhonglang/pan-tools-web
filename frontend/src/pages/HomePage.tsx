import { Link } from "react-router-dom";
import type { User } from "../api";

function formatExpiry(value: string | null) {
  if (!value) return "未设置";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export default function HomePage({ user }: { user: User | null }) {
  if (!user) {
    return (
      <section className="mx-auto flex min-h-[70vh] max-w-3xl flex-col justify-center px-6">
        <p className="text-sm font-semibold text-primary-dark">网盘工具</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-tight text-ink">登录后查看你的会员工作台。</h1>
        <p className="mt-4 max-w-xl text-base leading-7 text-ink/70">
          这里会显示当前等级、到期时间和接下来要开放的转存、分享与数据。
        </p>
        <div className="mt-8 flex gap-3">
          <Link to="/login" className="rounded-full bg-accent px-5 py-3 text-sm font-semibold text-white">
            登录
          </Link>
          <Link to="/register" className="rounded-full border border-line bg-white px-5 py-3 text-sm font-semibold text-ink">
            注册
          </Link>
        </div>
      </section>
    );
  }

  const paid = user.effective_plan === "paid" || user.paid_features;
  return (
    <div className="mx-auto max-w-5xl">
      <p className="text-sm font-medium text-primary-dark">工作台</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">你好，{user.email.split("@")[0]}</h1>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-ink/65">当前账号的会员状态。网盘转存、批量分享和数据会在后续版本放进这里。</p>

      <div className="mt-8 grid gap-4 md:grid-cols-3">
        <article className="rounded-3xl border border-line bg-white p-5">
          <p className="text-xs font-medium text-ink/50">当前有效等级</p>
          <p className="mt-3 text-2xl font-semibold">{user.effective_plan === "paid" ? "付费" : "免费"}</p>
          <p className="mt-2 text-sm text-ink/60">{paid ? "可以使用付费能力" : "付费能力未开通"}</p>
        </article>
        <article className="rounded-3xl border border-line bg-white p-5">
          <p className="text-xs font-medium text-ink/50">记录等级</p>
          <p className="mt-3 text-2xl font-semibold">{user.plan === "paid" ? "付费" : "免费"}</p>
          <p className="mt-2 text-sm text-ink/60">到期后有效等级会回到免费</p>
        </article>
        <article className="rounded-3xl border border-line bg-white p-5">
          <p className="text-xs font-medium text-ink/50">到期时间</p>
          <p className="mt-3 text-2xl font-semibold">{formatExpiry(user.plan_expires_at)}</p>
          <p className="mt-2 text-sm text-ink/60">按北京时间显示</p>
        </article>
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-3">
        {["批量转存", "分享导出", "数据概览"].map((name) => (
          <article key={name} className="rounded-3xl border border-dashed border-line bg-white/70 p-5">
            <p className="text-sm font-semibold">{name}</p>
            <p className="mt-2 text-sm leading-6 text-ink/55">即将开放</p>
          </article>
        ))}
      </div>

      {user.role === "admin" ? (
        <Link
          to="/admin/users"
          className="mt-4 flex items-center justify-between rounded-3xl bg-ink px-6 py-5 text-white transition duration-200 hover:bg-primary-dark"
        >
          <span>
            <span className="block text-sm text-white/70">管理员</span>
            <span className="mt-1 block text-lg font-semibold">去开通或收回会员</span>
          </span>
          <span className="text-sm">进入</span>
        </Link>
      ) : null}
    </div>
  );
}
