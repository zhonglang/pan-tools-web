export type BatchRenameSide = "front" | "back";

export type BatchRenameItem = {
  name: string;
  created_at: number | null;
};

export type BatchRenameRow<T> = {
  item: T;
  name: string;
};

export function planBatchRename<T extends BatchRenameItem>(
  items: T[],
  side: BatchRenameSide,
  startText: string,
): { ok: true; rows: BatchRenameRow<T>[] } | { ok: false; error: string } {
  const text = startText.trim();
  if (!/^[0-9]+$/.test(text)) return { ok: false, error: "开始数字需要是数字" };
  if (text.length > 9) return { ok: false, error: "开始数字最多 9 位" };
  if (items.length === 0) return { ok: false, error: "请选择要重命名的文件" };
  const width = text.length;
  const start = Number(text);
  const max = 10 ** width - 1;
  if (start + items.length - 1 > max) {
    return { ok: false, error: `编号最多到 ${String(max).padStart(width, "0")}` };
  }
  const ordered = items
    .map((item, index) => ({ item, index }))
    .sort((left, right) => {
      const leftTime = left.item.created_at ?? Number.POSITIVE_INFINITY;
      const rightTime = right.item.created_at ?? Number.POSITIVE_INFINITY;
      if (leftTime !== rightTime) return leftTime - rightTime;
      const byName = left.item.name.localeCompare(right.item.name, "zh-CN");
      if (byName !== 0) return byName;
      return left.index - right.index;
    });
  return {
    ok: true,
    rows: ordered.map(({ item }, offset) => {
      const label = String(start + offset).padStart(width, "0");
      const name = side === "front" ? `${label} ${item.name}` : `${item.name} ${label}`;
      return { item, name };
    }),
  };
}
