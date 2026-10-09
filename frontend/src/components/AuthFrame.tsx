import type { ReactNode } from "react";
import BrandMark from "./BrandMark";

const points = [
  { title: "扫码绑定", text: "用网盘 App 确认，账号只留在你这边。" },
  { title: "批量转存", text: "分享链接直接收进指定目录。" },
  { title: "任务可回看", text: "转存、分享和下载进度都在一处。" },
];

export function CoverLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-dvh bg-canvas lg:grid lg:grid-cols-[minmax(320px,0.86fr)_minmax(440px,1.14fr)]">
      <aside className="relative hidden min-h-dvh flex-col justify-between overflow-hidden bg-primary px-12 py-12 text-white lg:flex xl:px-16">
        <div className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full bg-white/10" />
        <div className="pointer-events-none absolute -bottom-20 -left-10 h-48 w-48 rounded-full bg-[#14b8a6]" />
        <div className="relative">
          <BrandMark light />
        </div>
        <div className="relative max-w-md">
          <p className="text-sm font-semibold text-white/80">给个人用的网盘工具</p>
          <p className="mt-3 text-[2.75rem] font-extrabold leading-[1.15] tracking-[-0.04em]">
            把转存和分享
            <br />
            放在同一处。
          </p>
        </div>
        <ul className="relative space-y-3">
          {points.map((point) => (
            <li key={point.title} className="rounded-2xl bg-white/15 px-4 py-3">
              <p className="text-sm font-bold">{point.title}</p>
              <p className="mt-1 text-[13px] leading-5 text-white/75">{point.text}</p>
            </li>
          ))}
        </ul>
      </aside>
      <main className="flex min-h-dvh items-center justify-center px-6 py-12 sm:px-10">
        <div className="w-full max-w-[400px]">{children}</div>
      </main>
    </div>
  );
}

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
    <CoverLayout>
      <div className="mb-8 lg:hidden">
        <BrandMark />
      </div>
      <h1 className="text-[2rem] font-extrabold tracking-[-0.04em] text-ink">{title}</h1>
      <p className="mt-2 text-sm leading-6 text-ink/65">{subtitle}</p>
      <div className="mt-8">{children}</div>
    </CoverLayout>
  );
}
