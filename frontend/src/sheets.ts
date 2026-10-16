import * as XLSX from "xlsx";

export type ShareSheetRow = { name: string; url: string; password: string };

export async function workbookShareRows(file: File): Promise<ShareSheetRow[]> {
  const book = XLSX.read(await file.arrayBuffer(), { type: "array" });
  const sheet = book.Sheets[book.SheetNames[0] ?? ""];
  if (!sheet) throw new Error("表格是空的");
  const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(sheet, { raw: false, defval: "" });
  if (rows.length === 0) throw new Error("表格里没有分享记录");
  const normalized = rows.map((row) => {
    const mapped: Record<string, string> = {};
    for (const [key, value] of Object.entries(row)) mapped[key.trim()] = String(value ?? "").trim();
    return mapped;
  });
  if (!("名称" in normalized[0]) || !("分享链接" in normalized[0])) throw new Error("请上传分享任务导出的表格");
  return normalized
    .map((row) => ({ name: row["名称"] ?? "", url: row["分享链接"] ?? "", password: row["提取码"] ?? "" }))
    .filter((row) => row.name || row.url);
}

export async function workbookText(file: File): Promise<string> {
  const book = XLSX.read(await file.arrayBuffer(), { type: "array" });
  const lines: string[] = [];
  for (const name of book.SheetNames) {
    const rows = XLSX.utils.sheet_to_json<(string | number | boolean | null)[]>(book.Sheets[name], {
      header: 1,
      raw: false,
      defval: "",
    });
    for (const row of rows) {
      const cells = (row ?? []).map((cell) => String(cell ?? "").trim()).filter(Boolean);
      if (cells.length) lines.push(cells.join(" "));
    }
  }
  return lines.join("\n");
}
