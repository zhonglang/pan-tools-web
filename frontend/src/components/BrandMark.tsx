export default function BrandMark({ light = false }: { light?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <span
        className={`grid h-10 w-10 place-items-center rounded-2xl ${light ? "bg-white/15 text-white" : "bg-ink text-white"}`}
      >
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path d="M4 7.5 10 4l6 3.5v5L10 16l-6-3.5v-5Z" stroke="currentColor" strokeWidth="1.6" />
          <path d="M10 9.2v6.6M4.4 7.8 10 11l5.6-3.2" stroke="currentColor" strokeWidth="1.6" />
        </svg>
      </span>
      <div>
        <div className={`text-sm font-semibold tracking-wide ${light ? "text-white" : "text-ink"}`}>网盘工具</div>
        <div className={`text-xs ${light ? "text-white/70" : "text-ink/60"}`}>会员工作台</div>
      </div>
    </div>
  );
}
