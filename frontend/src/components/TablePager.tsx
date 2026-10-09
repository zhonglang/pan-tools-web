export const PAGE_SIZE = 10;
export const PAGE_SIZES = [10, 20, 50] as const;

export function pageOf<T>(rows: T[], page: number, pageSize = PAGE_SIZE) {
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  const current = Math.min(Math.max(page, 1), pages);
  const start = (current - 1) * pageSize;
  return { page: current, pages, rows: rows.slice(start, start + pageSize), total: rows.length };
}

export function pagerItems(current: number, total: number): Array<number | "ellipsis"> {
  if (total <= 7) return Array.from({ length: total }, (_, index) => index + 1);
  if (current <= 4) return [1, 2, 3, 4, 5, 6, 7, "ellipsis", total];
  if (current >= total - 3) {
    const start = total - 6;
    return [1, "ellipsis", start, start + 1, start + 2, start + 3, start + 4, start + 5, total];
  }
  return [1, "ellipsis", current - 2, current - 1, current, current + 1, current + 2, "ellipsis", total];
}

function Chevron({ direction }: { direction: "left" | "right" | "down" }) {
  const path =
    direction === "left" ? "M7.4 2.4 3.8 6l3.6 3.6" : direction === "right" ? "M4.6 2.4 8.2 6 4.6 9.6" : "M2.4 4.6 6 8.2l3.6-3.6";
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
      <path d={path} stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function TablePager({
  page,
  total,
  onPage,
  pageSize = PAGE_SIZE,
  onPageSize,
}: {
  page: number;
  total: number;
  onPage: (page: number) => void;
  pageSize?: number;
  onPageSize?: (pageSize: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const current = Math.min(Math.max(page, 1), pages);
  const items = pagerItems(current, pages);
  let ellipsis = 0;

  return (
    <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line px-4 py-3">
      <span className="mr-1 text-sm text-[#595959]">共 {total} 条</span>
      <button type="button" className="pager-icon" aria-label="上一页" disabled={current <= 1} onClick={() => onPage(current - 1)}>
        <Chevron direction="left" />
      </button>
      {items.map((item) => {
        if (item === "ellipsis") {
          ellipsis += 1;
          const backward = ellipsis === 1 && current > 4;
          const target = backward ? Math.max(1, current - 5) : Math.min(pages, current + 5);
          return (
            <button key={`${item}-${ellipsis}`} type="button" className="pager-ellipsis" aria-label={backward ? "向前 5 页" : "向后 5 页"} onClick={() => onPage(target)}>
              …
            </button>
          );
        }
        const active = item === current;
        return (
          <button
            key={item}
            type="button"
            className={active ? "pager-page pager-page-active" : "pager-page"}
            aria-current={active ? "page" : undefined}
            onClick={() => onPage(item)}
          >
            {item}
          </button>
        );
      })}
      <button type="button" className="pager-icon" aria-label="下一页" disabled={current >= pages} onClick={() => onPage(current + 1)}>
        <Chevron direction="right" />
      </button>
      {onPageSize ? (
        <label className="relative ml-1">
          <span className="sr-only">每页条数</span>
          <select
            className="pager-size"
            value={pageSize}
            onChange={(event) => onPageSize(Number(event.target.value))}
          >
            {PAGE_SIZES.map((size) => (
              <option key={size} value={size}>
                {size}/页
              </option>
            ))}
          </select>
          <span className="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 text-[#8c8c8c]">
            <Chevron direction="down" />
          </span>
        </label>
      ) : null}
    </div>
  );
}
