import type { ReactNode } from "react";

export default function PageHeader({
  title,
  description,
  extra,
}: {
  title: string;
  description?: string;
  extra?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-2xl">
        <h1 className="text-[1.65rem] font-extrabold leading-tight tracking-[-0.04em] text-ink">{title}</h1>
        {description ? <p className="mt-1.5 text-sm leading-6 text-ink/60">{description}</p> : null}
      </div>
      {extra}
    </header>
  );
}
