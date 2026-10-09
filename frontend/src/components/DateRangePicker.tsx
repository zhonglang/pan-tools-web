import { useEffect, useRef, useState } from "react";

const shortcuts = [
  { id: "today", label: "今天" },
  { id: "week", label: "最近一周" },
  { id: "month", label: "最近一个月" },
] as const;

export function shanghaiToday() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

export function shiftDate(iso: string, days: number) {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day + days)).toISOString().slice(0, 10);
}

export function shortcutRange(kind: "today" | "week" | "month") {
  const end = shanghaiToday();
  if (kind === "week") return { start: shiftDate(end, -6), end };
  if (kind === "month") return { start: shiftDate(end, -29), end };
  return { start: end, end };
}

function addMonths(cursor: string, amount: number) {
  const [year, month] = cursor.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1 + amount, 1)).toISOString().slice(0, 7);
}

function monthCells(cursor: string) {
  const [year, month] = cursor.split("-").map(Number);
  const lead = (new Date(Date.UTC(year, month - 1, 1)).getUTCDay() + 6) % 7;
  const count = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const cells: { iso: string; inMonth: boolean }[] = [];
  for (let index = 0; index < lead; index += 1) cells.push({ iso: shiftDate(`${cursor}-01`, index - lead), inMonth: false });
  for (let day = 1; day <= count; day += 1) cells.push({ iso: shiftDate(`${cursor}-01`, day - 1), inMonth: true });
  while (cells.length % 7 !== 0) cells.push({ iso: shiftDate(cells[cells.length - 1].iso, 1), inMonth: false });
  return { year, month, cells };
}

function CalendarIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <rect x="2" y="3" width="12" height="11" rx="1.5" stroke="currentColor" strokeWidth="1.4" />
      <path d="M2 6.5h12M5 2v2.5M11 2v2.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

function Month({
  cursor,
  from,
  to,
  today,
  onPick,
  onHover,
}: {
  cursor: string;
  from: string;
  to: string;
  today: string;
  onPick: (iso: string) => void;
  onHover: (iso: string | null) => void;
}) {
  const cells = monthCells(cursor).cells;
  return (
    <div className="w-[252px]">
      <div className="grid grid-cols-7 text-center text-[12px] text-ink/40">
        {["一", "二", "三", "四", "五", "六", "日"].map((label) => (
          <span key={label} className="py-1">
            {label}
          </span>
        ))}
      </div>
      <div className="grid grid-cols-7">
        {cells.map((cell) => {
          const disabled = cell.iso > today;
          const isStart = cell.iso === from;
          const isEnd = cell.iso === to;
          const inRange = cell.iso >= from && cell.iso <= to && from !== to;
          return (
            <button
              key={`${cursor}-${cell.iso}`}
              type="button"
              disabled={disabled}
              onMouseEnter={() => onHover(cell.iso)}
              onMouseLeave={() => onHover(null)}
              onClick={() => onPick(cell.iso)}
              className="relative h-9 disabled:cursor-default"
            >
              {inRange ? <span className={`absolute inset-y-1 bg-muted ${isStart ? "left-1/2 right-0" : isEnd ? "left-0 right-1/2" : "inset-x-0"}`} /> : null}
              <span
                className={`relative mx-auto grid h-7 w-7 place-items-center rounded-full text-[13px] ${
                  isStart || isEnd
                    ? "bg-primary text-white"
                    : cell.inMonth
                      ? "text-ink hover:bg-muted"
                      : "text-ink/30"
                } ${disabled ? "text-ink/20 hover:bg-transparent" : ""}`}
              >
                {Number(cell.iso.slice(8))}
              </span>
              {cell.iso === today ? <span className="absolute bottom-0.5 left-1/2 h-1 w-1 -translate-x-1/2 rounded-full bg-primary" /> : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default function DateRangePicker({
  start,
  end,
  onChange,
  label = "选择日期范围",
  align = "left",
}: {
  start: string;
  end: string;
  onChange: (start: string, end: string) => void;
  label?: string;
  align?: "left" | "right";
}) {
  const today = shanghaiToday();
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(start.slice(0, 7));
  const [draftStart, setDraftStart] = useState(start);
  const [draftEnd, setDraftEnd] = useState(end);
  const [awaitingEnd, setAwaitingEnd] = useState(false);
  const [hover, setHover] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function close(event: MouseEvent) {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function openPanel() {
    setCursor(start.slice(0, 7));
    setDraftStart(start);
    setDraftEnd(end);
    setAwaitingEnd(false);
    setHover(null);
    setOpen(true);
  }

  function pick(iso: string) {
    if (iso > today) return;
    if (!awaitingEnd) {
      setDraftStart(iso);
      setDraftEnd(iso);
      setAwaitingEnd(true);
      return;
    }
    const [from, to] = draftStart <= iso ? [draftStart, iso] : [iso, draftStart];
    setDraftStart(from);
    setDraftEnd(to);
    setAwaitingEnd(false);
    setCursor(from.slice(0, 7));
  }

  function useShortcut(kind: (typeof shortcuts)[number]["id"]) {
    const range = shortcutRange(kind);
    setDraftStart(range.start);
    setDraftEnd(range.end);
    setAwaitingEnd(false);
    setCursor(range.start.slice(0, 7));
  }

  const previewEnd = awaitingEnd && hover && hover <= today ? hover : draftEnd;
  const [from, to] = draftStart <= previewEnd ? [draftStart, previewEnd] : [previewEnd, draftStart];

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        onClick={() => (open ? setOpen(false) : openPanel())}
        className={`flex h-10 items-center gap-3 rounded-lg border bg-white px-3 text-sm tabular-nums ${
          open ? "border-primary" : "border-line"
        }`}
      >
        <span>{start}</span>
        <span className="text-ink/35" aria-hidden="true">
          →
        </span>
        <span>{end}</span>
        <span className="text-primary">
          <CalendarIcon />
        </span>
      </button>
      {open ? (
        <div className={`absolute z-30 mt-2 flex max-w-[calc(100vw-2rem)] overflow-auto rounded-xl border border-line bg-white ${align === "right" ? "right-0" : "left-0"}`}>
          <div className="border-r border-line p-3">
            <div className="flex gap-4">
              {[cursor, addMonths(cursor, 1)].map((monthCursor, index) => {
                const { year, month } = monthCells(monthCursor);
                return (
                  <div key={monthCursor} className="w-[252px]">
                    <div className="mb-1 flex items-center justify-between text-ink/55">
                      <span className="flex">
                        <button type="button" className="grid h-7 w-7 place-items-center rounded-md hover:bg-canvas" aria-label={index === 0 ? "上一年" : "上一年 "} onClick={() => setCursor(addMonths(cursor, -12))}>
                          «
                        </button>
                        <button type="button" className="grid h-7 w-7 place-items-center rounded-md hover:bg-canvas" aria-label={index === 0 ? "上个月" : "上个月 "} onClick={() => setCursor(addMonths(cursor, -1))}>
                          ‹
                        </button>
                      </span>
                      <span className="text-sm font-medium text-ink">
                        {year}年{month}月
                      </span>
                      <span className="flex">
                        <button type="button" className="grid h-7 w-7 place-items-center rounded-md hover:bg-canvas" aria-label={index === 0 ? "下个月" : "下个月 "} onClick={() => setCursor(addMonths(cursor, 1))}>
                          ›
                        </button>
                        <button type="button" className="grid h-7 w-7 place-items-center rounded-md hover:bg-canvas" aria-label={index === 0 ? "下一年" : "下一年 "} onClick={() => setCursor(addMonths(cursor, 12))}>
                          »
                        </button>
                      </span>
                    </div>
                    <Month cursor={monthCursor} from={from} to={to} today={today} onPick={pick} onHover={setHover} />
                  </div>
                );
              })}
            </div>
          </div>
          <div className="flex w-36 shrink-0 flex-col p-3">
            <div className="flex flex-col gap-2">
              {shortcuts.map((item) => {
                const range = shortcutRange(item.id);
                const active = range.start === draftStart && range.end === draftEnd && !awaitingEnd;
                return (
                  <button
                    key={item.id}
                    type="button"
                    className={`h-8 rounded-full border px-3 text-[13px] ${
                      active ? "border-primary text-primary-dark" : "border-line text-ink/70 hover:border-primary"
                    }`}
                    onClick={() => useShortcut(item.id)}
                  >
                    {item.label}
                  </button>
                );
              })}
            </div>
            <button type="button" className="mt-auto h-8 rounded-full bg-primary px-4 text-sm font-medium text-white hover:bg-primary-dark" onClick={() => { onChange(draftStart, draftEnd); setOpen(false); }}>
              确认
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
