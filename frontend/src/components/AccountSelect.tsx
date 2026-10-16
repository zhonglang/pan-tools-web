import { useEffect, useRef, useState, type MouseEvent } from "react";
import type { PanAccount } from "../api";

function CheckIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M3.5 8.2 6.4 11l6.1-6.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ClearIcon() {
  return (
    <svg width="8" height="8" viewBox="0 0 8 8" fill="none" aria-hidden="true">
      <path d="M1.5 1.5l5 5M6.5 1.5l-5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

export default function AccountSelect({
  accounts,
  value,
  onChange,
}: {
  accounts: PanAccount[];
  value: number | null;
  onChange: (id: number | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const selected = accounts.find((account) => account.id === value) ?? null;

  useEffect(() => {
    if (!open) return;
    function close(event: globalThis.MouseEvent) {
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

  function clear(event: MouseEvent) {
    event.stopPropagation();
    onChange(null);
    setOpen(false);
  }

  return (
    <div ref={root} className="relative min-w-56">
      <div
        role="combobox"
        aria-label="选择网盘账号"
        aria-expanded={open}
        aria-controls="account-select-list"
        tabIndex={0}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            setOpen((current) => !current);
          }
        }}
        className={`flex h-10 cursor-pointer items-center gap-2 rounded-full border bg-white px-3 ${
          open ? "border-primary" : "border-line"
        }`}
      >
        {selected ? (
          <span className="min-w-0 flex-1 truncate text-sm text-ink">{selected.nickname}</span>
        ) : (
          <span className="flex-1 text-sm text-ink/35">全部账号</span>
        )}
        <span className="ml-auto flex shrink-0 items-center">
          {selected ? (
            <button
              type="button"
              aria-label="清空账号"
              className="grid h-[14px] w-[14px] place-items-center rounded-full bg-[#c0c4cc] text-white transition-colors hover:bg-[#909399]"
              onClick={clear}
            >
              <ClearIcon />
            </button>
          ) : (
            <span aria-hidden="true" className="text-ink/40">
              ▾
            </span>
          )}
        </span>
      </div>
      {open ? (
        <div id="account-select-list" role="listbox" className="absolute left-0 z-30 mt-1 w-full overflow-hidden rounded-xl border border-line bg-white py-1">
          {accounts.length === 0 ? <p className="px-3 py-2 text-sm text-ink/45">还没有网盘账号</p> : null}
          {accounts.map((account) => {
            const active = account.id === value;
            return (
              <button
                key={account.id}
                type="button"
                role="option"
                aria-selected={active}
                className={`flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm ${
                  active ? "bg-muted text-primary-dark" : "text-ink hover:bg-canvas"
                }`}
                onClick={() => {
                  onChange(account.id);
                  setOpen(false);
                }}
              >
                <span className="truncate">
                  {account.nickname}
                  {account.status === "valid" ? "" : "（需重新登录）"}
                </span>
                {active ? <CheckIcon /> : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
