export default function BrandMark({ light = false }: { light?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <span
        className={`grid h-9 w-9 place-items-center rounded-xl ${light ? "bg-white text-primary" : "bg-primary text-white"}`}
      >
        <svg width="18" height="18" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path d="M2.6 5.15 8 2.25l5.4 2.9v5.7L8 13.75l-5.4-2.9v-5.7Z" stroke="currentColor" strokeWidth="1.5" />
          <path d="M8 7.15v6.35M3.05 5.45 8 8.15l4.95-2.7" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </span>
      <span className={`text-[15px] font-extrabold tracking-[-0.03em] ${light ? "text-white" : "text-ink"}`}>网盘工具</span>
    </div>
  );
}
