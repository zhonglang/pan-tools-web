import type { ReactNode } from "react";
import BrandMark from "./BrandMark";

const points = ["免费与付费等级分开，到期后自动回到免费", "账号由你自己绑定，到期后再重新提交", "转存、分享和数据会放在同一套工作台里"];

export default function AuthFrame({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-canvas lg:grid lg:grid-cols-[minmax(0,1.05fr)_minmax(420px,0.95fr)]">
      <aside className="relative hidden overflow-hidden bg-ink text-white lg:flex lg:flex-col lg:justify-between lg:px-14 lg:py-12">
        <div className="pointer-events-none absolute -right-24 top-16 h-72 w-72 rounded-full bg-primary/30 blur-3xl" />
        <div className="pointer-events-none absolute bottom-0 left-0 h-64 w-64 rounded-full bg-accent/20 blur-3xl" />
        <BrandMark light />
        <div className="relative max-w-md">
          <p className="text-sm font-medium text-teal-100">给个人用户的网盘工作台</p>
          <h1 className="mt-4 max-w-md text-balance text-4xl font-semibold leading-snug tracking-tight">把转存、分享和会员放在一处。</h1>
          <ul className="mt-8 space-y-4 text-sm leading-6 text-white/80">
            {points.map((point) => (
              <li key={point} className="flex gap-3">
                <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                <span>{point}</span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-white/50">当前开放登录、注册和会员管理。网盘能力按阶段接入。</p>
      </aside>
      <main className="flex min-h-screen items-center justify-center px-5 py-10">
        <div className="w-full max-w-md">
          <div className="mb-8 lg:hidden">
            <BrandMark />
          </div>
          <div className="rounded-[28px] border border-line bg-white px-7 py-8 shadow-[0_20px_50px_rgba(19,78,74,0.08)]">
            <h2 className="text-2xl font-semibold tracking-tight text-ink">{title}</h2>
            <p className="mt-2 text-sm leading-6 text-ink/65">{subtitle}</p>
            <div className="mt-7">{children}</div>
          </div>
        </div>
      </main>
    </div>
  );
}
